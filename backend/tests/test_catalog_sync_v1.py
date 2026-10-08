from uuid import uuid4

from app.catalog_sync_v1 import apply_incoming, make_event, manifest, queue_repair_events
from app.db import db


def web_event(event_type="PRODUCT_CREATED", entity_type="product", source_id="web-1", version=1, payload=None, observed=None, identity=None):
    return {
        "schema_version": "catalog.sync.v1", "event_id": str(uuid4()), "event_type": event_type,
        "source_system": "rk-web", "source_id": source_id, "entity_type": entity_type,
        "entity_identity": identity or {"origin_system": "rk-web", "origin_id": source_id},
        "entity_version": version, "observed_versions": observed or {"rk-web": version, "rk-stock": 0},
        "occurred_at": "2026-10-07T00:00:00+00:00", "correlation_id": str(uuid4()),
        "causation_id": None, "origin_event_id": None, "actor": None,
        "payload": payload or {"sku": "WEB-1", "product_code": "WEB-1", "name": "Web product", "active": True},
    }


def test_web_product_create_replay_update_and_operational_protection(app):
    with app.app_context():
        event = web_event()
        ack, status = apply_incoming(db(), event)
        assert (ack["status"], status) == ("APPLIED", 200)
        product = db().products.find_one({"_id": ack["local_entity_id"]})
        # ObjectId lookup uses the identity mapping; no operational defaults are introduced.
        assert product is None
        product = db().products.find_one({"source_system": "rk-web", "source_id": "web-1"})
        assert product["sku"] == "WEB-1"
        assert not {"physical", "reserved", "available", "stock_ledger"}.intersection(product)
        replay, _ = apply_incoming(db(), event)
        assert replay["status"] == "ALREADY_APPLIED"
        assert db().products.count_documents({"source_system": "rk-web", "source_id": "web-1"}) == 1


def test_unrelated_sku_collision_records_conflict(app):
    with app.app_context():
        db().products.insert_one({"sku": "WEB-1", "name": "Stock owned", "source_system": "rk-stock", "source_id": "stock-1"})
        ack, status = apply_incoming(db(), web_event())
        assert (ack["status"], status) == ("CONFLICT", 409)
        assert db().catalog_sync_conflicts.count_documents({"status": "unresolved"}) == 1


def test_concurrent_web_update_is_conflict(app):
    with app.app_context():
        first = web_event()
        ack, _ = apply_incoming(db(), first)
        mapping = db().catalog_sync_identities.find_one({"entity_type": "product", "origin_id": "web-1"})
        db().catalog_sync_identities.update_one({"_id": mapping["_id"]}, {"$set": {"versions.rk-stock": 2}})
        update = web_event("PRODUCT_UPDATED", version=2, observed={"rk-web": 2, "rk-stock": 1})
        conflict, status = apply_incoming(db(), update)
        assert (conflict["status"], status) == ("CONFLICT", 409)


def test_receiver_auth_and_manifest(client, app):
    app.config["RK_STOREFRONT_BOOTSTRAP_SECRET"] = "catalog-test-secret"
    event = web_event()
    assert client.post("/api/integrations/internal/catalog/events", json=event).status_code == 401
    headers = {"Authorization": "Bearer catalog-test-secret"}
    response = client.post("/api/integrations/internal/catalog/events", json=event, headers=headers)
    assert response.status_code == 200
    assert response.json["status"] == "APPLIED"
    manifest = client.get("/api/integrations/internal/catalog/manifest", headers=headers)
    assert manifest.status_code == 200
    assert manifest.json["schema_version"] == "catalog.sync.v1"
    reconcile = client.post("/api/integrations/internal/catalog/reconcile", json={"items": manifest.json["items"]}, headers=headers)
    assert reconcile.status_code == 200
    assert reconcile.json["status"] == "completed"
    assert reconcile.json["result"]["repair_events_queued"] == 0


def test_stock_make_event_is_uppercase_and_complete():
    event = make_event("CATEGORY_UPDATED", "category", "category:test", 1, {"name": "Test", "slug": "test"})
    assert event["event_type"] == "CATEGORY_UPDATED"
    assert {"causation_id", "origin_event_id", "actor", "observed_versions"}.issubset(event)


def test_reconciliation_queues_product_collection_category_membership_and_media_once(app):
    with app.app_context():
        product_id = db().products.insert_one({"sku": "STOCK-REPAIR-1", "product_code": "STOCK-REPAIR-1", "name": "Stock repair", "active": True, "collection_ids": [], "images": [{"id": "stock-media-1", "provider": "cloudinary", "source": "rk-stock", "owner_system": "rk-stock", "public_id": "rk/stock-media-1", "position": 0, "is_primary": True}]}).inserted_id
        collection_id = db().collections.insert_one({"name": "Repair collection", "slug": "repair-collection", "active": True}).inserted_id
        db().products.update_one({"_id": product_id}, {"$set": {"collection_ids": [collection_id]}})
        db().settings.update_one({"_id": "global"}, {"$set": {"catalog_source_categories": [{"source_system": "rk-stock", "source_id": "category-1", "name": "Repair category", "active": True}]}}, upsert=True)
        db().catalog_sync_identities.insert_many([
            {"entity_type": "product", "origin_system": "rk-stock", "origin_id": "stock-product-1", "rk_stock_id": str(product_id), "versions": {"rk-stock": 2, "rk-web": 0}},
            {"entity_type": "collection", "origin_system": "rk-stock", "origin_id": "stock-collection-1", "rk_stock_id": str(collection_id), "versions": {"rk-stock": 2, "rk-web": 0}},
            {"entity_type": "category", "origin_system": "rk-stock", "origin_id": "category-1", "rk_stock_id": "category-1", "versions": {"rk-stock": 2, "rk-web": 0}},
        ])
        entries = manifest(db())["items"]
        assert any(item["entity_type"] == "product_collection" for item in entries)
        media = next(item for item in entries if item["entity_type"] == "media")
        assert media["payload"]["media_id"] == "stock-media-1"
        assert media["payload"]["product_identity"]["origin_id"] == "stock-product-1"
        first = queue_repair_events(db(), [])
        second = queue_repair_events(db(), [])
        assert {event["event_type"] for event in first} == {"PRODUCT_CREATED", "COLLECTION_CREATED", "CATEGORY_CREATED", "PRODUCT_COLLECTION_CHANGED", "MEDIA_CREATED"}
        assert second == []
        assert db().catalog_sync_outbox.count_documents({}) == 5
        db().catalog_sync_outbox.update_many({}, {"$set": {"status": "completed"}})
        assert queue_repair_events(db(), []) == []
        for event in db().catalog_sync_outbox.find({}):
            assert not {"stock", "physical_stock", "reserved_stock", "available_stock", "orders", "payments"}.intersection(event["payload"])


def test_web_membership_and_media_repairs_apply_once(app):
    with app.app_context():
        product_id = db().products.insert_one({"name": "Product", "collection_ids": [], "images": []}).inserted_id
        collection_id = db().collections.insert_one({"name": "Collection"}).inserted_id
        db().catalog_sync_identities.insert_many([
            {"entity_type": "product", "origin_system": "rk-web", "origin_id": "web-product", "rk_stock_id": str(product_id), "versions": {"rk-web": 1, "rk-stock": 0}},
            {"entity_type": "collection", "origin_system": "rk-web", "origin_id": "web-collection", "rk_stock_id": str(collection_id), "versions": {"rk-web": 1, "rk-stock": 0}},
        ])
        membership = web_event("PRODUCT_COLLECTION_CHANGED", "product_collection", "membership-1", 2, {"product_identity": {"origin_system": "rk-web", "origin_id": "web-product"}, "changes": [{"operation": "ADD", "collection_identity": {"origin_system": "rk-web", "origin_id": "web-collection"}, "display_order": 3}]}, {"rk-web": 2, "rk-stock": 0}, {"origin_system": "rk-web", "origin_id": "membership-1"})
        assert apply_incoming(db(), membership)[0]["status"] == "APPLIED"
        assert apply_incoming(db(), membership)[0]["status"] == "ALREADY_APPLIED"
        assert db().products.find_one({"_id": product_id})["collection_ids"] == [collection_id]
        cloud = {"media_id": "cloud-web-1", "provider": "cloudinary", "owner_system": "rk-web", "public_id": "rk/cloud-web-1", "position": 1, "is_primary": False, "product_identity": {"origin_system": "rk-web", "origin_id": "web-product"}}
        media = web_event("MEDIA_CREATED", "media", "cloud-web-1", 2, cloud, {"rk-web": 2, "rk-stock": 0}, {"origin_system": "rk-web", "origin_id": "cloud-web-1"})
        assert apply_incoming(db(), media)[0]["status"] == "APPLIED"
        assert apply_incoming(db(), media)[0]["status"] == "ALREADY_APPLIED"
        images = db().products.find_one({"_id": product_id})["images"]
        assert len(images) == 1 and images[0]["public_id"] == "rk/cloud-web-1" and images[0]["owner_system"] == "rk-web"
        changed = {**cloud, "position": 4, "is_primary": True, "description": "Updated"}
        reorder = web_event("MEDIA_REORDERED", "media", "cloud-web-1", 3, changed, {"rk-web": 3, "rk-stock": 0}, {"origin_system": "rk-web", "origin_id": "cloud-web-1"})
        assert apply_incoming(db(), reorder)[0]["status"] == "APPLIED"
        cloud_stored = next(item for item in db().products.find_one({"_id": product_id})["images"] if item["id"] == "cloud-web-1")
        assert cloud_stored["position"] == 4 and cloud_stored["is_primary"] is True and cloud_stored["description"] == "Updated"
        workdrive = {"media_id": "wd-web-1", "provider": "zoho_workdrive", "owner_system": "rk-web", "permalink": "https://workdrive.zoho.in/file/abc", "position": 0, "is_primary": True, "product_identity": {"origin_system": "rk-web", "origin_id": "web-product"}}
        wd_event = web_event("MEDIA_CREATED", "media", "wd-web-1", 4, workdrive, {"rk-web": 4, "rk-stock": 0}, {"origin_system": "rk-web", "origin_id": "wd-web-1"})
        assert apply_incoming(db(), wd_event)[0]["status"] == "APPLIED"
        stored = db().products.find_one({"_id": product_id})["images"]
        assert next(item for item in stored if item["id"] == "wd-web-1")["permalink"] == "https://workdrive.zoho.in/file/abc"
        assert queue_repair_events(db(), manifest(db())["items"]) == []


def test_web_category_repair_and_ambiguous_authority_conflict(app):
    with app.app_context():
        event = web_event("CATEGORY_CREATED", "category", "web-category", 1, {"name": "Couture", "slug": "couture", "active": True}, {"rk-web": 1, "rk-stock": 0}, {"origin_system": "rk-web", "origin_id": "web-category"})
        assert apply_incoming(db(), event)[0]["status"] == "APPLIED"
        assert apply_incoming(db(), event)[0]["status"] == "ALREADY_APPLIED"
        stored = db().settings.find_one({"_id": "global"})["catalog_source_categories"]
        assert len(stored) == 1 and stored[0]["name"] == "Couture"
        assert queue_repair_events(db(), [{"entity_type": "product", "payload": {"name": "Unknown"}}]) == []
        assert db().catalog_sync_conflicts.count_documents({"reason": "ambiguous_reconciliation_authority"}) == 1
        queue_repair_events(db(), [{"entity_type": "product", "payload": {"name": "Unknown"}}])
        assert db().catalog_sync_conflicts.count_documents({"reason": "ambiguous_reconciliation_authority"}) == 1
