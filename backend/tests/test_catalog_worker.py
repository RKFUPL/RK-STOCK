from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread

from app.catalog_outbox import claim_due_event, deliver_due_with_leases, enqueue
from app.db import db
from catalog_worker import _required_database_name


class Client:
    bootstrap_secret = "test-only"

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def _request(self, method, path, token, payload):
        self.calls += 1
        if self.fail:
            raise RuntimeError("upstream unavailable")
        return {"status": "APPLIED"}


def test_worker_database_name_must_be_explicit():
    assert _required_database_name({"MONGO_DB": "RK_TEST_DB"}) == "RK_TEST_DB"
    assert _required_database_name({"MONGO_DB": "RKSTOCKDB"}) == "RKSTOCKDB"
    import pytest
    with pytest.raises(RuntimeError, match="explicitly configured"):
        _required_database_name({})


def test_compose_api_and_worker_share_required_database_configuration():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    required = "MONGO_DB: ${MONGO_DB:?MONGO_DB must be explicitly configured}"
    assert compose.count(required) == 2
    assert "MONGO_DB: RKSTOCKDB" not in compose


def test_future_event_is_not_claimed(app):
    with app.app_context():
        event = enqueue("product.updated", "future", {"source_system": "rk-stock", "source_id": "future"})
        db().catalog_sync_outbox.update_one({"_id": event["_id"]}, {"$set": {"next_attempt_at": datetime.now(timezone.utc) + timedelta(minutes=5)}})
        assert claim_due_event(worker_id="worker-a") is None


def test_due_event_completes_and_failure_backoff_is_preserved(app):
    with app.app_context():
        success = enqueue("product.updated", "success", {"source_system": "rk-stock", "source_id": "success"})
        result = deliver_due_with_leases(Client(), worker_id="worker-a")
        assert result["completed"] == 1
        assert db().catalog_sync_outbox.find_one({"_id": success["_id"]})["status"] == "completed"
        failed = enqueue("product.updated", "failed", {"source_system": "rk-stock", "source_id": "failed"})
        before = datetime.now(timezone.utc)
        result = deliver_due_with_leases(Client(fail=True), worker_id="worker-b")
        stored = db().catalog_sync_outbox.find_one({"_id": failed["_id"]})
        assert result["failed"] == 1
        assert stored["status"] == "pending"
        assert stored["attempts"] == 1
        assert stored["next_attempt_at"].replace(tzinfo=timezone.utc) > before


def test_active_lease_blocks_second_worker_and_expired_lease_is_reclaimable(app):
    with app.app_context():
        event = enqueue("product.updated", "leased", {"source_system": "rk-stock", "source_id": "leased"})
        first = claim_due_event(worker_id="worker-a")
        assert first["_id"] == event["_id"]
        assert claim_due_event(worker_id="worker-b") is None
        db().catalog_sync_outbox.update_one({"_id": event["_id"]}, {"$set": {"lease_until": datetime.now(timezone.utc) - timedelta(seconds=1)}})
        reclaimed = claim_due_event(worker_id="worker-b")
        assert reclaimed["_id"] == event["_id"]
        assert reclaimed["lease_id"] == "worker-b"


def test_concurrent_workers_claim_an_event_once(app):
    with app.app_context():
        event = enqueue("product.updated", "concurrent", {"source_system": "rk-stock", "source_id": "concurrent"})
        results = []
        def claim(worker):
            with app.app_context():
                result = claim_due_event(worker_id=worker)
                results.append(result["_id"] if result else None)
        threads = [Thread(target=claim, args=(f"worker-{i}",)) for i in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert results.count(event["_id"]) == 1
        assert results.count(None) == 1
