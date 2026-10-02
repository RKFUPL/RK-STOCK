from pathlib import Path

import pytest
import mongomock
from flask import Flask
from pymongo.errors import ServerSelectionTimeoutError

from app.config import Config
from app.db import init_db
from app.db import ensure_indexes
from bson import ObjectId


class _FakeCollection:
    def __init__(self):
        self.index_calls = []

    def create_index(self, fields, **options):
        self.index_calls.append((fields, options))
        return "index"

    def update_one(self, *args, **kwargs):
        return None

    def find_one(self, *args, **kwargs):
        return None

    def insert_one(self, *args, **kwargs):
        return None


class _FakeDatabase:
    def __init__(self):
        self.collections = _FakeCollection()

    def __getattr__(self, name):
        collection = _FakeCollection()
        setattr(self, name, collection)
        return collection

    def __getitem__(self, name):
        return getattr(self, name)


class _FakeAdmin:
    def __init__(self, client):
        self.client = client

    def command(self, command):
        self.client.pings += 1
        if self.client.fail_pings:
            self.client.fail_pings -= 1
            raise ServerSelectionTimeoutError("temporary primary failure")
        return {"ok": 1}


class _FakeClient:
    def __init__(self, fail_pings=0):
        self.fail_pings = fail_pings
        self.pings = 0
        self.admin = _FakeAdmin(self)
        self.database = _FakeDatabase()

    @property
    def primary(self):
        if self.fail_pings:
            raise ServerSelectionTimeoutError("primary unavailable")
        return ("primary", 27017)

    def __getitem__(self, _name):
        return self.database


def _app(client, attempts=3):
    app = Flask(__name__)
    app.config.update(
        MONGO_CLIENT=client,
        MONGO_DB="test_db",
        MONGO_SERVER_SELECTION_TIMEOUT_MS=30000,
        MONGO_CONNECT_ATTEMPTS=attempts,
        MONGO_CONNECT_BACKOFF_SECONDS=0,
    )
    return app


def test_successful_connection_initializes_indexes():
    client = _FakeClient()
    init_db(_app(client))

    assert client.pings == 1
    assert client.database.users.index_calls
    assert client.database.collections.index_calls


def test_temporary_primary_failure_retries_then_initializes_indexes():
    client = _FakeClient(fail_pings=2)
    init_db(_app(client, attempts=3))

    assert client.pings == 3
    assert client.database.users.index_calls


def test_persistent_primary_failure_is_reported():
    client = _FakeClient(fail_pings=10)

    with pytest.raises(RuntimeError, match="MongoDB primary was unavailable"):
        init_db(_app(client, attempts=3))

    assert client.pings == 3
    assert not client.database.users.index_calls


def test_backend_loads_project_root_environment_configuration():
    assert (Path(__file__).resolve().parents[2] / ".env").exists()
    assert Config.MONGO_DB == "RKSTOCKDB"
    assert Config.MONGO_SERVER_SELECTION_TIMEOUT_MS == 30000


def test_collection_seed_reuses_existing_code_record_and_is_idempotent():
    database = mongomock.MongoClient()["test_db"]
    existing_id = ObjectId("6abd086468a0358cad9d179c")
    database.collections.insert_one({"_id": existing_id, "name": "Inaara", "slug": "collections-of-inaara", "code": "INA", "active": True})

    ensure_indexes(database)
    ensure_indexes(database)

    records = list(database.collections.find({"code": "INA"}))
    assert len(records) == 1
    assert records[0]["_id"] == existing_id
    assert records[0]["slug"] == "collections-of-inaara"
