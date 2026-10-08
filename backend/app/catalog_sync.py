from copy import deepcopy

from .db import db
from .sku import collection_code
from .utils import money, now


SOURCE_SYSTEM = "rk-web"


class CatalogSyncError(RuntimeError):
    pass


def _text(value):
    return str(value or "").strip()


def _require_items(payload, name):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise CatalogSyncError(f"RK-WEB returned a malformed {name} catalog response")
    return payload["items"]


def _changed(existing, updates):
    return any(existing.get(key) != value for key, value in updates.items())


def _media_items(item):
    source = item.get("media") if isinstance(item.get("media"), list) else item.get("images")
    source = source if isinstance(source, list) else []
    normalized = []
    for position, media in enumerate(source):
        if isinstance(media, str):
            url, values = media.strip(), {}
        elif isinstance(media, dict):
            url = _text(media.get("url") or media.get("src"))
            values = media
        else:
            continue
        if not url:
            continue
        normalized.append({
            "url": url,
            "position": int(values.get("position", position)),
            "is_main": bool(values.get("is_primary") or values.get("is_main")),
            "source": _text(values.get("source") or SOURCE_SYSTEM),
            **{key: values[key] for key in ("provider", "type", "permalink", "secure_url", "public_id", "alt_text", "description") if values.get(key) is not None},
        })
    if normalized and not any(media["is_main"] for media in normalized):
        normalized[0]["is_main"] = True
    return normalized


def _media_identity(media):
    return media.get("permalink") or media.get("secure_url") or media.get("public_id") or media.get("url")


def _merge_media(existing, incoming):
    """Reconcile RK-WEB-owned media while retaining Stock-owned relationships."""
    remote = list(incoming or [])
    remote_identities = {_media_identity(item) for item in remote if _media_identity(item)}
    stock_owned = [
        dict(item) for item in (existing or [])
        if isinstance(item, dict) and item.get("source") != SOURCE_SYSTEM and _media_identity(item) not in remote_identities
    ]
    return remote + stock_owned


class CatalogSyncService:
    def __init__(self, storefront_client):
        self.storefront = storefront_client

    def sync(self, actor_id):
        started_at = now()
        snapshot = self.storefront.catalog_snapshot()
        products = _require_items(snapshot.get("products"), "products")
        categories = _require_items(snapshot.get("categories"), "categories")
        collections = _require_items(snapshot.get("collections"), "collections")
        validated = {
            "products": [self._product(item) for item in products],
            "categories": [self._category(item) for item in categories],
            "collections": [self._collection(item) for item in collections],
        }
        collection_counts = self._sync_collections(validated["collections"])
        collection_map = {item["source_id"]: item for item in db().collections.find({"source_system": SOURCE_SYSTEM})}
        result = {
            "status": "completed",
            "products": self._sync_products(validated["products"], collection_map),
            "categories": self._sync_categories(validated["categories"], actor_id),
            "collections": collection_counts,
            "started_at": started_at,
            "completed_at": now(),
        }
        db().settings.update_one(
            {"_id": self.storefront.record_id},
            {"$set": {"catalog_sync_status": "completed", "catalog_last_successful_sync": result["completed_at"], "catalog_last_result": deepcopy(result), "updated_at": result["completed_at"]}},
            upsert=True,
        )
        return result

    def _product(self, item):
        if not isinstance(item, dict):
            return None
        source_id, sku, name = _text(item.get("id")), _text(item.get("sku")).upper(), _text(item.get("name"))
        if not source_id or not sku or not name:
            return None
        return {
            "source_system": SOURCE_SYSTEM,
            "source_id": source_id,
            "source_slug": _text(item.get("slug")),
            "sku": sku,
            "product_code": _text(item.get("product_code") or sku),
            "name": name,
            "description": _text(item.get("description")),
            "category": _text(item.get("category")),
            "selling_price": money(item.get("price")) if item.get("price") is not None else None,
            "base_currency": _text(item.get("currency") or "INR").upper(),
            "tax_inclusive": bool(item.get("tax_inclusive")),
            "images": _media_items(item),
            "colors": item.get("colours") if isinstance(item.get("colours"), list) else [],
            "sizes": item.get("sizes") if isinstance(item.get("sizes"), list) else [],
            "active": bool(item.get("active")),
            "source_status": _text(item.get("status")),
            "source_collection_ids": [_text(value) for value in item.get("collection_ids") or [] if _text(value)],
        }

    def _category(self, item):
        if not isinstance(item, dict):
            return None
        source_id, name = _text(item.get("id")), _text(item.get("name"))
        return {"source_system": SOURCE_SYSTEM, "source_id": source_id, "name": name, "slug": _text(item.get("slug"))} if source_id and name else None

    def _collection(self, item):
        if not isinstance(item, dict):
            return None
        source_id, name, slug = _text(item.get("id")), _text(item.get("name")), _text(item.get("slug"))
        if not source_id or not name or not slug:
            return None
        return {"source_system": SOURCE_SYSTEM, "source_id": source_id, "name": name, "slug": slug, "code": _text(item.get("code") or collection_code(name)), "active": bool(item.get("active")), "source_status": _text(item.get("status"))}

    def _sync_products(self, records, collection_map):
        counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
        for updates in records:
            if not updates:
                counts["skipped"] += 1
                continue
            memberships = [collection_map[source_id] for source_id in updates["source_collection_ids"] if source_id in collection_map]
            collection_names = [item["name"] for item in memberships]
            updates = {
                **updates,
                "collection_ids": [item["_id"] for item in memberships],
                "collection_names": collection_names,
                "collections": [{"id": item["_id"], "source_id": item["source_id"], "name": item["name"], "slug": item["slug"], "code": item.get("code")} for item in memberships],
                "collection": collection_names[0] if len(collection_names) == 1 else None,
            }
            existing = db().products.find_one({"source_system": SOURCE_SYSTEM, "source_id": updates["source_id"]})
            if not existing and db().products.find_one({"sku": updates["sku"]}):
                counts["skipped"] += 1
                continue
            if not existing:
                db().products.insert_one({**updates, "created_at": now(), "updated_at": now()})
                counts["created"] += 1
            else:
                updates["images"] = _merge_media(existing.get("images"), updates.get("images"))
                if _changed(existing, updates):
                    db().products.update_one({"_id": existing["_id"]}, {"$set": {**updates, "updated_at": now()}})
                    counts["updated"] += 1
                else:
                    counts["unchanged"] += 1
        return counts

    def _sync_categories(self, records, actor_id):
        counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
        setting = db().settings.find_one({"_id": "global"}) or {}
        names = list(setting.get("categories") or [])
        metadata = list(setting.get("catalog_source_categories") or [])
        by_id = {item.get("source_id"): item for item in metadata if isinstance(item, dict)}
        for item in records:
            if not item:
                counts["skipped"] += 1
                continue
            existing = by_id.get(item["source_id"])
            if not existing:
                metadata.append(item)
                by_id[item["source_id"]] = item
                if item["name"].casefold() not in {name.casefold() for name in names if isinstance(name, str)}:
                    names.append(item["name"])
                counts["created"] += 1
            elif _changed(existing, item):
                existing.update(item)
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
        if counts["created"] or counts["updated"]:
            db().settings.update_one({"_id": "global"}, {"$set": {"categories": names, "catalog_source_categories": metadata, "updated_at": now(), "updated_by": actor_id}, "$inc": {"categories_revision": 1}}, upsert=True)
        return counts

    def _sync_collections(self, records):
        counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
        for updates in records:
            if not updates:
                counts["skipped"] += 1
                continue
            existing = db().collections.find_one({"source_system": SOURCE_SYSTEM, "source_id": updates["source_id"]})
            if not existing:
                collision = db().collections.find_one({"slug": updates["slug"]}) or db().collections.find_one({"code": updates["code"]})
                if collision:
                    if collision.get("source_system") not in {None, SOURCE_SYSTEM} or collision.get("source_id") not in {None, updates["source_id"]}:
                        counts["skipped"] += 1
                        continue
                    db().collections.update_one({"_id": collision["_id"]}, {"$set": {**updates, "updated_at": now()}})
                    counts["updated"] += 1
                    continue
            if not existing:
                position = db().collections.count_documents({}) + 1
                db().collections.insert_one({**updates, "position": position, "created_at": now(), "updated_at": now()})
                counts["created"] += 1
            elif _changed(existing, updates):
                db().collections.update_one({"_id": existing["_id"]}, {"$set": {**updates, "updated_at": now()}})
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
        if counts["created"] or counts["updated"]:
            db().settings.update_one({"_id": "global"}, {"$inc": {"collections_revision": 1}, "$set": {"updated_at": now()}}, upsert=True)
        return counts
