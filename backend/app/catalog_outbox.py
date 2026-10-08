"""Durable RK-STOCK -> RK-WEB catalog delivery.

Only catalog-owned fields are serialized here.  Operational collections are
deliberately never read or included in an event payload.
"""
from datetime import datetime, timezone, timedelta
from secrets import token_hex
import logging

from pymongo import ReturnDocument
from .db import db
from .catalog_sync_v1 import make_event, validate_event


SOURCE = "rk-stock"
LEASE_SECONDS = 60
logger = logging.getLogger("rk-stock.catalog-outbox")


def _now():
    return datetime.now(timezone.utc)


def _stock_media(product):
    result = []
    for item in product.get("images") or []:
        if not isinstance(item, dict) or item.get("source") != SOURCE:
            continue
        result.append({key: item[key] for key in (
            "id", "url", "secure_url", "public_id", "provider", "type",
            "permalink", "source", "position", "is_primary", "description",
            "alt_text", "asset_folder", "view"
        ) if item.get(key) is not None})
    return result


def product_payload(product):
    colours = product.get("colors") or product.get("colours") or []
    if not isinstance(colours, list):
        colours = [colours]
    collections = []
    collection_ids = product.get("collection_ids") or ([product.get("collection_id")] if product.get("collection_id") else [])
    for collection in db().collections.find({"_id": {"$in": [value for value in collection_ids if value]}}):
        collections.append(str(collection.get("source_id") or collection["_id"]))
    for item in product.get("collections") or []:
        if isinstance(item, dict) and item.get("source_id"):
            collections.append(str(item["source_id"]))
    return {
        "source_system": SOURCE,
        "source_id": str(product["_id"]),
        "product_code": product.get("product_code"),
        "sku": product.get("sku"),
        "name": product.get("name"),
        "description": product.get("description"),
        "colour": colours[0] if colours else product.get("color"),
        "category": product.get("category"),
        "price": product.get("selling_price", product.get("price")),
        "currency": product.get("base_currency", product.get("currency", "INR")),
        "tax_inclusive": bool(product.get("tax_inclusive")),
        "active": product.get("active") is not False,
        "status": product.get("status") or ("active" if product.get("active") is not False else "archived"),
        "collection_ids": collections,
        "media": _stock_media(product),
    }


def collection_payload(collection):
    return {
        "source_system": SOURCE,
        "source_id": str(collection["_id"]),
        "name": collection.get("name"),
        "slug": collection.get("slug"),
        "code": collection.get("code"),
        "description": collection.get("description", ""),
        "active": collection.get("active") is not False,
        "status": "active" if collection.get("active") is not False else "archived",
    }


def enqueue(event_type, source_id, payload, actor_id=None):
    legacy_map = {
        "product.created": ("PRODUCT_CREATED", "product"), "product.updated": ("PRODUCT_UPDATED", "product"), "product.deactivated": ("PRODUCT_DEACTIVATED", "product"),
        "collection.created": ("COLLECTION_CREATED", "collection"), "collection.updated": ("COLLECTION_UPDATED", "collection"), "collection.deactivated": ("COLLECTION_DEACTIVATED", "collection"),
        "category.created": ("CATEGORY_CREATED", "category"), "category.updated": ("CATEGORY_UPDATED", "category"), "category.deactivated": ("CATEGORY_DEACTIVATED", "category"),
    }
    event_type, entity_type = legacy_map.get(event_type, (event_type, payload.get("entity_type")))
    now = _now()
    payload = dict(payload or {})
    identity = payload.pop("entity_identity", None) or {
        "origin_system": str(payload.get("source_system") or SOURCE),
        "origin_id": str(payload.get("source_id") or source_id),
    }
    mapping_query = {"entity_type": entity_type, "origin_system": identity["origin_system"], "origin_id": identity["origin_id"]}
    mapping = db().catalog_sync_identities.find_one(mapping_query) or {}
    versions = dict(mapping.get("versions") or {})
    version = int(payload.pop("catalog_version", versions.get(SOURCE, 0) + 1))
    observed = payload.pop("observed_versions", None) or {**versions, SOURCE: version}
    causation_id = payload.pop("causation_id", None)
    origin_event_id = payload.pop("origin_event_id", None)
    event = {**make_event(event_type, entity_type, source_id, version, payload, observed_versions=observed, identity=identity, actor_id=actor_id, causation_id=causation_id, origin_event_id=origin_event_id),
        "target_system": "rk-web",
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": now,
        "created_at": now,
        "updated_at": now,
        "actor_id": str(actor_id) if actor_id else None,
    }
    db().catalog_sync_outbox.insert_one(event)
    db().catalog_sync_identities.update_one(
        mapping_query,
        {"$set": {"rk_stock_id": str(source_id), "versions": {**versions, SOURCE: version}, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return event


def _event_request(client, event):
    envelope = {key: event.get(key) for key in (
        "schema_version", "event_id", "event_type", "source_system", "source_id",
        "entity_type", "entity_identity", "entity_version", "observed_versions",
        "occurred_at", "correlation_id", "causation_id", "origin_event_id", "actor", "payload",
    )}
    validate_event(envelope, expected_source=SOURCE)
    return client._request("POST", "/api/integrations/internal/catalog/events", client.bootstrap_secret, envelope)


def claim_due_event(*, worker_id=None, lease_seconds=LEASE_SECONDS):
    now = _now()
    worker_id = worker_id or token_hex(12)
    event = db().catalog_sync_outbox.find_one_and_update(
        {
            "status": "pending",
            "next_attempt_at": {"$lte": now},
            "$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lte": now}}],
        },
        {"$set": {"lease_id": worker_id, "lease_until": now + timedelta(seconds=lease_seconds), "claimed_at": now, "updated_at": now}},
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    return event


def complete_claimed_event(event):
    return db().catalog_sync_outbox.update_one(
        {"_id": event["_id"], "status": "pending", "lease_id": event.get("lease_id")},
        {"$set": {"status": "completed", "completed_at": _now(), "updated_at": _now(), "last_error": None}, "$unset": {"lease_id": "", "lease_until": "", "claimed_at": ""}},
    ).modified_count == 1


def conflict_claimed_event(event):
    return db().catalog_sync_outbox.update_one(
        {"_id": event["_id"], "status": "pending", "lease_id": event.get("lease_id")},
        {"$set": {"status": "conflict", "receiver_status": "CONFLICT", "completed_at": _now(), "updated_at": _now(), "last_error": "Receiver reported a catalog conflict"}, "$unset": {"lease_id": "", "lease_until": "", "claimed_at": ""}},
    ).modified_count == 1


def fail_claimed_event(event, exc):
    now = _now()
    attempts = int(event.get("attempts", 0)) + 1
    delay = min(3600, 2 ** min(attempts, 10))
    return db().catalog_sync_outbox.update_one(
        {"_id": event["_id"], "status": "pending", "lease_id": event.get("lease_id")},
        {"$set": {"status": "pending", "attempts": attempts, "last_error": str(exc)[:500], "next_attempt_at": now + timedelta(seconds=delay), "updated_at": now}, "$unset": {"lease_id": "", "lease_until": "", "claimed_at": ""}},
    ).modified_count == 1


def process_claimed_event(client, event):
    try:
        acknowledgement = _event_request(client, event)
    except Exception as exc:
        fail_claimed_event(event, exc)
        logger.warning("catalog event failed event_id=%s event_type=%s source_id=%s retry=%s", event.get("event_id"), event.get("event_type"), event.get("source_id"), int(event.get("attempts", 0)) + 1)
        return False
    receiver_status = acknowledgement.get("status")
    if receiver_status == "CONFLICT":
        conflict_claimed_event(event)
        return True
    if receiver_status not in {"APPLIED", "ALREADY_APPLIED", "STALE"}:
        fail_claimed_event(event, RuntimeError(f"receiver returned {receiver_status or 'unknown'}"))
        return False
    complete_claimed_event(event)
    logger.info("catalog event completed event_id=%s event_type=%s source_id=%s", event.get("event_id"), event.get("event_type"), event.get("source_id"))
    return True


def deliver_pending(client, *, limit=20):
    now = _now()
    events = list(db().catalog_sync_outbox.find({"status": "pending", "next_attempt_at": {"$lte": now}}).sort("created_at", 1).limit(limit))
    result = {"attempted": 0, "completed": 0, "failed": 0}
    for event in events:
        result["attempted"] += 1
        try:
            acknowledgement = _event_request(client, event)
            if acknowledgement.get("status") == "CONFLICT":
                db().catalog_sync_outbox.update_one({"_id": event["_id"], "status": "pending"}, {"$set": {"status": "conflict", "receiver_status": "CONFLICT", "completed_at": _now(), "updated_at": _now(), "last_error": "Receiver reported a catalog conflict"}})
                result["completed"] += 1
                continue
            if acknowledgement.get("status") not in {"APPLIED", "ALREADY_APPLIED", "STALE"}:
                raise RuntimeError(f"receiver returned {acknowledgement.get('status') or 'unknown'}")
        except Exception as exc:
            attempts = int(event.get("attempts", 0)) + 1
            delay = min(3600, 2 ** min(attempts, 10))
            db().catalog_sync_outbox.update_one({"_id": event["_id"], "status": "pending"}, {"$set": {"status": "pending", "attempts": attempts, "last_error": str(exc)[:500], "next_attempt_at": now + timedelta(seconds=delay), "updated_at": _now()}})
            result["failed"] += 1
            continue
        db().catalog_sync_outbox.update_one({"_id": event["_id"], "status": "pending"}, {"$set": {"status": "completed", "completed_at": _now(), "updated_at": _now(), "last_error": None}})
        result["completed"] += 1
    return result


def deliver_due_with_leases(client, *, limit=20, worker_id=None):
    result = {"attempted": 0, "completed": 0, "failed": 0}
    for _ in range(limit):
        event = claim_due_event(worker_id=worker_id)
        if not event:
            break
        result["attempted"] += 1
        logger.info("catalog event claimed event_id=%s event_type=%s source_id=%s", event.get("event_id"), event.get("event_type"), event.get("source_id"))
        if process_claimed_event(client, event):
            result["completed"] += 1
        else:
            result["failed"] += 1
    return result
