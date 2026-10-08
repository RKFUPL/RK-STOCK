"""Canonical catalog.sync.v1 protocol support for RK-STOCK.

This module only mutates catalog metadata. Inventory, ledger, linesheet,
order, payment and provider assets are deliberately outside this boundary.
"""
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from bson import ObjectId
from pymongo.errors import DuplicateKeyError


SCHEMA_VERSION = "catalog.sync.v1"
SYSTEM = "rk-stock"
EVENT_TYPES = {
    "PRODUCT_CREATED", "PRODUCT_UPDATED", "PRODUCT_DEACTIVATED", "PRODUCT_DELETED",
    "COLLECTION_CREATED", "COLLECTION_UPDATED", "COLLECTION_DEACTIVATED", "COLLECTION_DELETED",
    "CATEGORY_CREATED", "CATEGORY_UPDATED", "CATEGORY_DEACTIVATED", "CATEGORY_DELETED",
    "PRODUCT_COLLECTION_CHANGED", "MEDIA_CREATED", "MEDIA_UPDATED", "MEDIA_DELETED",
    "MEDIA_REORDERED", "MEDIA_PRIMARY_CHANGED",
}
ENTITY_TYPES = {"product", "collection", "category", "product_collection", "media"}
REQUIRED_FIELDS = {
    "schema_version", "event_id", "event_type", "source_system", "source_id",
    "entity_type", "entity_identity", "entity_version", "observed_versions",
    "occurred_at", "correlation_id", "payload",
}
FORBIDDEN_FIELDS = {
    "stock", "physical_stock", "reserved_stock", "available_stock", "inventory",
    "stock_ledger", "inventory_transactions", "warehouse_quantities",
    "stock_adjustments", "linesheets", "orders", "payments",
}
PRODUCT_FIELDS = {
    "product_code", "sku", "name", "description", "price", "currency",
    "tax_inclusive", "category", "status", "active", "colour",
}


class CatalogEventError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc)


def payload_digest(event):
    value = json.dumps(event.get("payload"), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode()).hexdigest()


def validate_event(event, expected_source=None):
    if not isinstance(event, dict) or REQUIRED_FIELDS - set(event):
        raise CatalogEventError("Missing required catalog event fields.")
    if event["schema_version"] != SCHEMA_VERSION:
        raise CatalogEventError("Unsupported catalog event schema.")
    if event["event_type"] not in EVENT_TYPES or event["entity_type"] not in ENTITY_TYPES:
        raise CatalogEventError("Unsupported catalog event type.")
    if event["source_system"] not in {"rk-web", "rk-stock"} or (expected_source and event["source_system"] != expected_source):
        raise CatalogEventError("Invalid catalog event source.")
    if not isinstance(event["source_id"], str) or not event["source_id"].strip() or len(event["source_id"]) > 200:
        raise CatalogEventError("Invalid catalog source identity.")
    identity = event["entity_identity"]
    if not isinstance(identity, dict) or identity.get("origin_system") not in {"rk-web", "rk-stock"} or not str(identity.get("origin_id") or "").strip():
        raise CatalogEventError("Invalid canonical entity identity.")
    if isinstance(event["entity_version"], bool) or not isinstance(event["entity_version"], int) or event["entity_version"] < 1:
        raise CatalogEventError("Invalid entity version.")
    if not isinstance(event["observed_versions"], dict) or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in event["observed_versions"].values()):
        raise CatalogEventError("Invalid observed versions.")
    if not isinstance(event["payload"], dict) or FORBIDDEN_FIELDS.intersection(event["payload"]):
        raise CatalogEventError("Catalog event contains forbidden operational fields.")
    for key in ("event_id", "correlation_id"):
        try:
            UUID(str(event[key]))
        except (ValueError, TypeError, AttributeError):
            raise CatalogEventError(f"Invalid {key}.")
    if event["entity_type"] == "media":
        media = event["payload"]
        provider = str(media.get("provider") or "").lower()
        if provider not in {"cloudinary", "zoho_workdrive"} or not str(media.get("media_id") or "").strip() or media.get("owner_system") not in {"rk-web", "rk-stock"}:
            raise CatalogEventError("Invalid media identity or ownership.")
        if provider == "cloudinary" and not str(media.get("public_id") or "").strip():
            raise CatalogEventError("Cloudinary media requires public_id.")
        if provider == "zoho_workdrive":
            parsed = urlsplit(str(media.get("permalink") or ""))
            if parsed.scheme != "https" or "/file/" not in parsed.path or "/embed/" in parsed.path:
                raise CatalogEventError("WorkDrive media requires its canonical /file/ permalink.")
        if isinstance(media.get("position", 0), bool) or not isinstance(media.get("position", 0), int) or media.get("position", 0) < 0 or not isinstance(media.get("is_primary", False), bool):
            raise CatalogEventError("Invalid media position or primary state.")
    return event


def make_event(event_type, entity_type, source_id, version, payload, *, observed_versions=None, identity=None, actor_id=None, correlation_id=None, causation_id=None, origin_event_id=None):
    event = {
        "schema_version": SCHEMA_VERSION, "event_id": str(uuid4()), "event_type": event_type,
        "source_system": SYSTEM, "source_id": str(source_id), "entity_type": entity_type,
        "entity_identity": identity or {"origin_system": SYSTEM, "origin_id": str(source_id)},
        "entity_version": int(version), "observed_versions": observed_versions or {SYSTEM: int(version)},
        "occurred_at": now().isoformat(), "correlation_id": correlation_id or str(uuid4()),
        "causation_id": causation_id, "origin_event_id": origin_event_id,
        "actor": {"type": "user", "id": str(actor_id)} if actor_id else None,
        "payload": payload,
    }
    return validate_event(event, expected_source=SYSTEM)


def _ack(event, status, local_id=None):
    return {"schema_version": SCHEMA_VERSION, "status": status, "event_id": event["event_id"], "entity_type": event["entity_type"], "source_id": event["source_id"], "entity_version": event["entity_version"], "local_entity_id": str(local_id) if local_id else None}


def _identity_query(event):
    identity = event["entity_identity"]
    return {"entity_type": event["entity_type"], "origin_system": identity["origin_system"], "origin_id": str(identity["origin_id"])}


def _mapping(db, event, local_id=None):
    query = _identity_query(event)
    current = db.catalog_sync_identities.find_one(query)
    if local_id and not current:
        values = {**query, "rk_web_id": event["source_id"] if event["source_system"] == "rk-web" else None, "rk_stock_id": str(local_id), "versions": {}, "created_at": now(), "updated_at": now()}
        try:
            db.catalog_sync_identities.insert_one(values)
        except DuplicateKeyError:
            pass
        current = db.catalog_sync_identities.find_one(query)
    return current


def _find_product_collision(db, payload):
    clauses = []
    if payload.get("sku"):
        clauses.append({"sku": payload["sku"]})
    if payload.get("product_code"):
        clauses.append({"product_code": payload["product_code"]})
    return db.products.find_one({"$or": clauses}) if clauses else None


def _apply_payload(db, event, mapping):
    payload, kind = event["payload"], event["entity_type"]
    stock_id = (mapping or {}).get("rk_stock_id")
    object_id = ObjectId(stock_id) if stock_id and ObjectId.is_valid(str(stock_id)) else None
    if kind == "product":
        product = db.products.find_one({"_id": object_id}) if object_id else None
        if not product:
            collision = _find_product_collision(db, payload)
            if collision and (collision.get("source_system"), str(collision.get("source_id") or "")) != (event["entity_identity"]["origin_system"], str(event["entity_identity"]["origin_id"])):
                raise CatalogEventError("Product identity collides with an unrelated Stock product.")
        values = {key: payload[key] for key in PRODUCT_FIELDS if key in payload}
        if "price" in values:
            values["selling_price"] = values.pop("price")
        if "currency" in values:
            values["base_currency"] = values.pop("currency")
        if "colour" in values:
            values["colors"] = [values.pop("colour")]
        values.update({"source_system": event["entity_identity"]["origin_system"], "source_id": str(event["entity_identity"]["origin_id"]), "updated_at": now()})
        if event["event_type"] in {"PRODUCT_DEACTIVATED", "PRODUCT_DELETED"}:
            values.update({"active": False, "status": "archived"})
        if product:
            db.products.update_one({"_id": product["_id"]}, {"$set": values})
            return product["_id"]
        values["created_at"] = now()
        return db.products.insert_one(values).inserted_id
    if kind == "collection":
        item = db.collections.find_one({"_id": object_id}) if object_id else None
        values = {key: payload[key] for key in ("name", "slug", "code", "description", "status", "active") if key in payload}
        values.update({"source_system": event["entity_identity"]["origin_system"], "source_id": str(event["entity_identity"]["origin_id"]), "updated_at": now()})
        if event["event_type"] in {"COLLECTION_DEACTIVATED", "COLLECTION_DELETED"}:
            values.update({"active": False, "status": "archived"})
        if item:
            db.collections.update_one({"_id": item["_id"]}, {"$set": values})
            return item["_id"]
        values["created_at"] = now()
        return db.collections.insert_one(values).inserted_id
    if kind == "category":
        settings = db.settings.find_one({"_id": "global"}) or {}
        metadata = [item for item in settings.get("catalog_source_categories") or [] if not (item.get("source_system") == event["entity_identity"]["origin_system"] and str(item.get("source_id")) == str(event["entity_identity"]["origin_id"]))]
        metadata.append({**payload, "source_system": event["entity_identity"]["origin_system"], "source_id": str(event["entity_identity"]["origin_id"])})
        names = list(settings.get("categories") or [])
        if payload.get("active", True) is not False and payload.get("name") and payload["name"] not in names:
            names.append(payload["name"])
        db.settings.update_one({"_id": "global"}, {"$set": {"catalog_source_categories": metadata, "categories": names, "updated_at": now()}}, upsert=True)
        return event["source_id"]
    product_identity = payload.get("product_identity") or {}
    product_map = db.catalog_sync_identities.find_one({"entity_type": "product", "origin_system": product_identity.get("origin_system"), "origin_id": str(product_identity.get("origin_id") or "")})
    if not product_map or not ObjectId.is_valid(str(product_map.get("rk_stock_id") or "")):
        raise CatalogEventError("Mapped product is required before relationship events.")
    product_id = ObjectId(product_map["rk_stock_id"])
    if kind == "product_collection":
        ids = list((db.products.find_one({"_id": product_id}) or {}).get("collection_ids") or [])
        for change in payload.get("changes") or []:
            ident = change.get("collection_identity") or {}
            coll_map = db.catalog_sync_identities.find_one({"entity_type": "collection", "origin_system": ident.get("origin_system"), "origin_id": str(ident.get("origin_id") or "")})
            if not coll_map or not ObjectId.is_valid(str(coll_map.get("rk_stock_id") or "")):
                continue
            collection_id = ObjectId(coll_map["rk_stock_id"])
            if change.get("operation") == "REMOVE":
                ids = [value for value in ids if value != collection_id]
            elif collection_id not in ids:
                ids.append(collection_id)
        db.products.update_one({"_id": product_id}, {"$set": {"collection_ids": ids, "updated_at": now()}})
        return product_id
    product = db.products.find_one({"_id": product_id}) or {}
    images = [dict(item) for item in product.get("images") or [] if isinstance(item, dict)]
    media_id = str(payload.get("media_id") or "")
    existing = next((item for item in images if str(item.get("id")) == media_id), None)
    if existing and existing.get("owner_system") not in {None, payload.get("owner_system")}:
        raise CatalogEventError("Media ownership does not permit replacement.")
    images = [item for item in images if str(item.get("id")) != media_id]
    if event["event_type"] != "MEDIA_DELETED":
        images.append({**payload, "id": media_id, "source": payload.get("owner_system")})
    images.sort(key=lambda item: int(item.get("position", 0)))
    db.products.update_one({"_id": product_id}, {"$set": {"images": images, "updated_at": now()}})
    return media_id


def apply_incoming(db, raw_event):
    event = validate_event(raw_event, expected_source="rk-web")
    digest = payload_digest(event)
    applied = db.catalog_applied_events.find_one({"event_id": event["event_id"]})
    if applied:
        return (_ack(event, "INVALID"), 400) if applied.get("payload_digest") != digest else (_ack(event, "ALREADY_APPLIED", applied.get("local_entity_id")), 200)
    mapping = _mapping(db, event)
    versions = dict((mapping or {}).get("versions") or {})
    known_source = int(versions.get("rk-web", 0))
    if event["entity_version"] <= known_source:
        return _ack(event, "STALE", (mapping or {}).get("rk_stock_id")), 200
    if int(event["observed_versions"].get("rk-stock", 0)) < int(versions.get("rk-stock", 0)):
        db.catalog_sync_conflicts.insert_one({"conflict_id": str(uuid4()), "event_id": event["event_id"], "entity_type": event["entity_type"], "entity_identity": event["entity_identity"], "local_versions": versions, "incoming_versions": event["observed_versions"], "incoming_payload": event["payload"], "status": "unresolved", "detected_at": now()})
        return _ack(event, "CONFLICT", (mapping or {}).get("rk_stock_id")), 409
    try:
        local_id = _apply_payload(db, event, mapping)
    except CatalogEventError as error:
        db.catalog_sync_conflicts.insert_one({"conflict_id": str(uuid4()), "event_id": event["event_id"], "entity_type": event["entity_type"], "entity_identity": event["entity_identity"], "incoming_payload": event["payload"], "reason": str(error), "status": "unresolved", "detected_at": now()})
        return _ack(event, "CONFLICT", (mapping or {}).get("rk_stock_id")), 409
    mapping = _mapping(db, event, local_id)
    versions["rk-web"] = event["entity_version"]
    db.catalog_sync_identities.update_one(_identity_query(event), {"$set": {"versions": versions, "rk_web_id": event["source_id"], "rk_stock_id": str(local_id), "updated_at": now()}})
    db.catalog_applied_events.insert_one({"event_id": event["event_id"], "source_system": "rk-web", "entity_type": event["entity_type"], "source_id": event["source_id"], "entity_version": event["entity_version"], "payload_digest": digest, "result": "APPLIED", "local_entity_id": str(local_id), "correlation_id": event["correlation_id"], "applied_at": now()})
    db.catalog_sync_logs.insert_one({"event_id": event["event_id"], "event_type": event["event_type"], "entity_type": event["entity_type"], "source_id": event["source_id"], "status": "APPLIED", "correlation_id": event["correlation_id"], "created_at": now()})
    return _ack(event, "APPLIED", local_id), 200


def manifest(db):
    items = []
    for mapping in db.catalog_sync_identities.find({}):
        payload = None
        local_id = mapping.get("rk_stock_id")
        if mapping.get("entity_type") == "product" and local_id and ObjectId.is_valid(str(local_id)):
            product = db.products.find_one({"_id": ObjectId(local_id)}) or {}
            payload = {"product_code": product.get("product_code"), "sku": product.get("sku"), "name": product.get("name"), "description": product.get("description", ""), "price": product.get("selling_price", product.get("price")), "currency": product.get("base_currency", product.get("currency", "INR")), "category": product.get("category"), "active": product.get("active") is not False, "status": product.get("status") or "active"}
        elif mapping.get("entity_type") == "collection" and local_id and ObjectId.is_valid(str(local_id)):
            collection = db.collections.find_one({"_id": ObjectId(local_id)}) or {}
            payload = {key: collection.get(key) for key in ("name", "slug", "code", "description", "status", "active") if collection.get(key) is not None}
        elif mapping.get("entity_type") == "category":
            setting = db.settings.find_one({"_id": "global"}) or {}
            category = next((item for item in setting.get("catalog_source_categories") or [] if item.get("source_system") == mapping.get("origin_system") and str(item.get("source_id")) == str(mapping.get("origin_id"))), None)
            payload = {key: category[key] for key in ("name", "slug", "description", "status", "active") if category and category.get(key) is not None} if category else None
        items.append({"entity_type": mapping.get("entity_type"), "entity_identity": {"origin_system": mapping.get("origin_system"), "origin_id": mapping.get("origin_id")}, "versions": mapping.get("versions") or {}, "rk_web_id": mapping.get("rk_web_id"), "rk_stock_id": mapping.get("rk_stock_id")})
        items[-1]["payload"] = payload
    expanded = list(items)
    for item in list(items):
        if item.get("entity_type") != "product" or not item.get("payload"):
            continue
        mapping = db.catalog_sync_identities.find_one({"entity_type": "product", "origin_system": item["entity_identity"]["origin_system"], "origin_id": item["entity_identity"]["origin_id"]}) or {}
        product = db.products.find_one({"_id": ObjectId(item["rk_stock_id"])}) if ObjectId.is_valid(str(item.get("rk_stock_id") or "")) else None
        product_identity = item["entity_identity"]
        for collection_id in (product or {}).get("collection_ids") or []:
            collection_map = db.catalog_sync_identities.find_one({"entity_type": "collection", "rk_stock_id": str(collection_id)})
            if collection_map:
                collection_identity = {"origin_system": collection_map.get("origin_system"), "origin_id": str(collection_map.get("origin_id"))}
                membership_id = f"{product_identity['origin_system']}:{product_identity['origin_id']}->{collection_identity['origin_system']}:{collection_identity['origin_id']}"
                expanded.append({"entity_type": "product_collection", "entity_identity": {"origin_system": product_identity["origin_system"], "origin_id": membership_id}, "product_identity": product_identity, "collection_identity": collection_identity, "versions": mapping.get("versions") or {}, "payload": {"product_identity": product_identity, "collection_identity": collection_identity, "display_order": 0, "active": True}})
        for media in (product or {}).get("images") or []:
            if isinstance(media, dict) and media.get("id"):
                owner = media.get("owner_system") or media.get("source") or SYSTEM
                media_payload = {key: media[key] for key in ("url", "secure_url", "public_id", "provider", "type", "permalink", "position", "is_primary", "description", "alt_text", "asset_folder", "view") if media.get(key) is not None}
                media_payload.update({"media_id": str(media["id"]), "owner_system": owner, "product_identity": product_identity})
                expanded.append({"entity_type": "media", "entity_identity": {"origin_system": owner, "origin_id": str(media.get("id"))}, "product_identity": product_identity, "versions": mapping.get("versions") or {}, "payload": media_payload})
    return {"schema_version": SCHEMA_VERSION, "source_system": SYSTEM, "generated_at": now().isoformat(), "items": expanded}


def classify_manifest_difference(local_item, remote_item):
    if not local_item and remote_item: return "LOCAL_MISSING"
    if local_item and not remote_item: return "REMOTE_MISSING"
    if not local_item and not remote_item: return "UNSAFE_TO_REPAIR"
    local_versions = local_item.get("versions") or {}; remote_versions = remote_item.get("versions") or {}
    local_version = int(local_versions.get(SYSTEM, 0)); remote_version = int(remote_versions.get(SYSTEM, 0))
    if local_version == remote_version and local_item.get("payload") == remote_item.get("payload"): return "IDENTICAL"
    if local_version > remote_version: return "LOCAL_NEWER"
    if remote_version > local_version: return "REMOTE_NEWER"
    return "CONCURRENT_CONFLICT"


def queue_repair_events(db, remote_items, actor_id=None):
    for item in remote_items:
        identity = item.get("entity_identity") if isinstance(item, dict) else None
        if not isinstance(identity, dict) or identity.get("origin_system") not in {"rk-web", "rk-stock"} or not str(identity.get("origin_id") or "").strip():
            fingerprint = payload_digest({"payload": item if isinstance(item, dict) else {"invalid": True}})
            if not db.catalog_sync_conflicts.find_one({"reason": "ambiguous_reconciliation_authority", "fingerprint": fingerprint, "status": "unresolved"}):
                db.catalog_sync_conflicts.insert_one({"conflict_id": str(uuid4()), "entity_type": item.get("entity_type") if isinstance(item, dict) else None, "entity_identity": identity, "reason": "ambiguous_reconciliation_authority", "fingerprint": fingerprint, "status": "unresolved", "detected_at": now()})
    remote = {(item.get("entity_type"), (item.get("entity_identity") or {}).get("origin_system"), str((item.get("entity_identity") or {}).get("origin_id") or "")): item for item in remote_items if isinstance(item, dict)}
    queued = []
    for mapping in db.catalog_sync_identities.find({}):
        key = (mapping.get("entity_type"), mapping.get("origin_system"), str(mapping.get("origin_id") or "")); versions = mapping.get("versions") or {}
        local_version = int(versions.get(SYSTEM, 0)); remote_version = int((remote.get(key) or {}).get("versions", {}).get(SYSTEM, 0))
        local_item = next((item for item in manifest(db)["items"] if (item.get("entity_type"), (item.get("entity_identity") or {}).get("origin_system"), str((item.get("entity_identity") or {}).get("origin_id") or "")) == key), None)
        if local_version and local_version == remote_version and remote.get(key) and payload_digest({"payload": (local_item or {}).get("payload")}) != payload_digest({"payload": (remote.get(key) or {}).get("payload")}):
            if not db.catalog_sync_conflicts.find_one({"entity_type": mapping.get("entity_type"), "entity_identity": {"origin_system": mapping.get("origin_system"), "origin_id": mapping.get("origin_id")}, "status": "unresolved", "reason": "reconciliation_payload_divergence"}):
                db.catalog_sync_conflicts.insert_one({"conflict_id": str(uuid4()), "entity_type": mapping.get("entity_type"), "entity_identity": {"origin_system": mapping.get("origin_system"), "origin_id": mapping.get("origin_id")}, "local_versions": versions, "incoming_versions": (remote.get(key) or {}).get("versions") or {}, "reason": "reconciliation_payload_divergence", "status": "unresolved", "detected_at": now()})
            continue
        if not local_version or local_version <= remote_version: continue
        local_id = mapping.get("rk_stock_id"); entity_type = mapping.get("entity_type")
        if entity_type == "product" and ObjectId.is_valid(str(local_id)):
            product = db.products.find_one({"_id": ObjectId(local_id)}) or {}; payload = {"product_code": product.get("product_code"), "sku": product.get("sku"), "name": product.get("name"), "description": product.get("description", ""), "price": product.get("selling_price", product.get("price")), "currency": product.get("base_currency", product.get("currency", "INR")), "category": product.get("category"), "active": product.get("active") is not False, "status": product.get("status") or "active"}; event_type = "PRODUCT_CREATED" if key not in remote else "PRODUCT_UPDATED"
        elif entity_type == "collection" and ObjectId.is_valid(str(local_id)):
            collection = db.collections.find_one({"_id": ObjectId(local_id)}) or {}; payload = {key: collection.get(key) for key in ("name", "slug", "code", "description", "status", "active") if collection.get(key) is not None}; event_type = "COLLECTION_CREATED" if key not in remote else "COLLECTION_UPDATED"
        elif entity_type == "category":
            setting = db.settings.find_one({"_id": "global"}) or {}; category = next((item for item in setting.get("catalog_source_categories") or [] if item.get("source_system") == mapping.get("origin_system") and str(item.get("source_id")) == str(mapping.get("origin_id"))), None)
            if not category: continue
            payload = {field: category[field] for field in ("name", "slug", "description", "status", "active") if category.get(field) is not None}; event_type = "CATEGORY_CREATED" if key not in remote else "CATEGORY_DEACTIVATED" if payload.get("active") is False else "CATEGORY_UPDATED"
        else: continue
        existing = db.catalog_sync_outbox.find_one({"entity_type": entity_type, "entity_identity": {"origin_system": mapping["origin_system"], "origin_id": mapping["origin_id"]}, "entity_version": local_version, "status": {"$in": ["pending", "completed"]}})
        if existing:
            continue
        queued.append(__import__("app.catalog_outbox", fromlist=["enqueue"]).enqueue(event_type, local_id, {**payload, "entity_type": entity_type, "entity_identity": {"origin_system": mapping["origin_system"], "origin_id": mapping["origin_id"]}, "catalog_version": local_version, "observed_versions": versions, "causation_id": "reconciliation"}, actor_id))
    local_manifest = manifest(db)["items"]
    for item in local_manifest:
        entity_type = item.get("entity_type"); identity = item.get("entity_identity") or {}; payload = item.get("payload") or {}
        if entity_type not in {"media", "product_collection"} or not identity.get("origin_system") or not identity.get("origin_id"):
            continue
        key = (entity_type, identity["origin_system"], str(identity["origin_id"]))
        remote_item = remote.get(key); versions = item.get("versions") or {}; local_version = int(versions.get(SYSTEM, 0)); remote_version = int((remote_item or {}).get("versions", {}).get(SYSTEM, 0))
        if local_version and local_version == remote_version and remote_item and payload_digest({"payload": payload}) != payload_digest({"payload": remote_item.get("payload")}):
            if not db.catalog_sync_conflicts.find_one({"entity_type": entity_type, "entity_identity": identity, "status": "unresolved", "reason": "reconciliation_payload_divergence"}):
                db.catalog_sync_conflicts.insert_one({"conflict_id": str(uuid4()), "entity_type": entity_type, "entity_identity": identity, "local_versions": versions, "incoming_versions": remote_item.get("versions") or {}, "reason": "reconciliation_payload_divergence", "status": "unresolved", "detected_at": now()})
            continue
        if not local_version or local_version <= remote_version:
            continue
        event_type = "PRODUCT_COLLECTION_CHANGED" if entity_type == "product_collection" else "MEDIA_CREATED" if not remote_item else "MEDIA_UPDATED"
        if entity_type == "media" and remote_item and payload.get("position") != (remote_item.get("payload") or {}).get("position"): event_type = "MEDIA_REORDERED"
        if entity_type == "media" and remote_item and payload.get("is_primary") != (remote_item.get("payload") or {}).get("is_primary"): event_type = "MEDIA_PRIMARY_CHANGED"
        duplicate = db.catalog_sync_outbox.find_one({"event_type": event_type, "entity_type": entity_type, "entity_identity": identity, "entity_version": local_version, "status": {"$in": ["pending", "completed"]}})
        if duplicate: continue
        event_payload = dict(payload)
        if entity_type == "product_collection":
            event_payload = {"entity_type": entity_type, "product_identity": item.get("product_identity"), "changes": [{"operation": "ADD", "collection_identity": item.get("collection_identity"), "display_order": payload.get("display_order", 0)}]}
        queued.append(__import__("app.catalog_outbox", fromlist=["enqueue"]).enqueue(event_type, identity["origin_id"], {**event_payload, "entity_type": entity_type, "entity_identity": identity, "catalog_version": local_version, "observed_versions": versions, "causation_id": "reconciliation"}, actor_id))
    return queued
