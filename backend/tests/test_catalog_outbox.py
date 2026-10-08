from datetime import datetime, timezone

from app.catalog_outbox import deliver_pending, enqueue, product_payload
from app.db import db


class Client:
    bootstrap_secret = "not persisted"

    def __init__(self):
        self.calls = []
        self.fail = False

    def _request(self, method, path, token, payload):
        self.calls.append((method, path, payload))
        if self.fail:
            raise RuntimeError("temporary upstream failure")
        return {"status": "APPLIED"}


def test_product_event_contains_catalog_fields_only(app):
    with app.app_context():
        database = db()
        product_id = database.products.insert_one({"sku": "HK-1-A", "product_code": "CK1", "name": "One", "description": "D", "price": 10, "active": True, "images": [{"source": "rk-stock", "url": "https://res.cloudinary.com/x/a.jpg"}, {"source": "rk-web", "url": "https://res.cloudinary.com/x/web.jpg"}]}).inserted_id
        payload = product_payload(database.products.find_one({"_id": product_id}))
    assert payload["source_id"] == str(product_id)
    assert len(payload["media"]) == 1
    assert "stock_balances" not in payload
    assert "linesheets" not in payload


def test_delivery_uses_full_canonical_envelope(app):
    with app.app_context():
        enqueue("product.updated", "p1", {"source_system": "rk-stock", "source_id": "p1", "sku": "S"})
        client = Client()
        assert deliver_pending(client)["completed"] == 1
    method, path, envelope = client.calls[0]
    assert (method, path) == ("POST", "/api/integrations/internal/catalog/events")
    assert envelope["schema_version"] == "catalog.sync.v1"
    assert envelope["event_type"] == "PRODUCT_UPDATED"
    assert envelope["entity_identity"] == {"origin_system": "rk-stock", "origin_id": "p1"}
    assert envelope["observed_versions"]["rk-stock"] == 1


def test_outbox_retries_and_is_idempotently_completed(app):
    with app.app_context():
        event = enqueue("product.updated", "p1", {"source_system": "rk-stock", "source_id": "p1", "sku": "S"})
        client = Client(); client.fail = True
        assert deliver_pending(client)["failed"] == 1
        stored = db().catalog_sync_outbox.find_one({"event_id": event["event_id"]})
        assert stored["status"] == "pending"
        db().catalog_sync_outbox.update_one({"_id": stored["_id"]}, {"$set": {"next_attempt_at": datetime.now(timezone.utc)}})
        client.fail = False
        assert deliver_pending(client)["completed"] == 1
        assert db().catalog_sync_outbox.find_one({"_id": stored["_id"]})["status"] == "completed"
