import time

from flask import current_app, g
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError


def _wait_for_writable_primary(client, attempts, backoff_seconds):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            client.admin.command("ping")
            # Accessing primary forces PyMongo to select a writable primary;
            # this also works with the mongomock client used by the tests.
            client.primary
            return
        except (PyMongoError, OSError, RuntimeError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)
    raise RuntimeError(f"MongoDB primary was unavailable after {attempts} attempt(s); verify Atlas network access and cluster health") from last_error


def init_db(app):
    client = app.config.get("MONGO_CLIENT") or MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=app.config["MONGO_SERVER_SELECTION_TIMEOUT_MS"])
    app.extensions["mongo_client"] = client
    app.extensions["mongo_db"] = client[app.config["MONGO_DB"]]
    with app.app_context():
        _wait_for_writable_primary(client, app.config["MONGO_CONNECT_ATTEMPTS"], app.config["MONGO_CONNECT_BACKOFF_SECONDS"])
        ensure_indexes(app.extensions["mongo_db"])


def db():
    return current_app.extensions["mongo_db"]


def ensure_indexes(database):
    indexes = {
        "users": [([("email", ASCENDING)], {"unique": True})],
        "clients": [([("client_code", ASCENDING)], {"unique": True}), ([('name', ASCENDING)], {})],
        "products": [([("sku", ASCENDING)], {"unique": True}), ([("collection_id", ASCENDING), ("product_code", ASCENDING)], {"unique": True, "sparse": True}), ([("source_system", ASCENDING), ("source_id", ASCENDING)], {"unique": True, "sparse": True})],
        "linesheets": [([("linesheet_number", ASCENDING)], {"unique": True})],
        "orders": [([("po_number", ASCENDING)], {"unique": True}), ([('client_id', ASCENDING), ('status', ASCENDING)], {})],
        "stock_balances": [([("sku", ASCENDING), ("color", ASCENDING), ("size", ASCENDING), ("location", ASCENDING), ("client_id", ASCENDING)], {"unique": True})],
        "stock_ledger": [([("transaction_id", ASCENDING)], {"unique": True}), ([('created_at', DESCENDING)], {})],
        "production_movements": [([("movement_id", ASCENDING)], {"unique": True})],
        "activity_log": [([("created_at", DESCENDING)], {})],
        "documents": [([("family_id", ASCENDING), ("version", ASCENDING)], {"unique": True}), ([("client_linesheet_id", ASCENDING), ("kind", ASCENDING), ("created_at", DESCENDING)], {})],
        "client_linesheets": [([("client_id", ASCENDING), ("uploaded_at", DESCENDING)], {}), ([("client_id", ASCENDING), ("title", ASCENDING)], {})],
        "imports": [([("client_id", ASCENDING), ("file_hash", ASCENDING), ("status", ASCENDING)], {})],
        "linesheet_email_history": [([("request_id", ASCENDING)], {"unique": True}), ([("linesheet_id", ASCENDING), ("created_at", DESCENDING)], {})],
        "workdrive_folders": [([("key", ASCENDING)], {"unique": True})],
        "collections": [([("slug", ASCENDING)], {"unique": True}), ([("code", ASCENDING)], {"unique": True, "sparse": True}), ([("position", ASCENDING)], {}), ([("source_system", ASCENDING), ("source_id", ASCENDING)], {"unique": True, "sparse": True})],
        "product_configurations": [([("linesheet_sku", ASCENDING)], {"unique": True}), ([("product_id", ASCENDING)], {})],
        "inventory_variants": [([("inventory_sku", ASCENDING)], {"unique": True}), ([("configuration_id", ASCENDING), ("size", ASCENDING)], {"unique": True})],
    }
    for collection, definitions in indexes.items():
        for fields, options in definitions:
            database[collection].create_index(fields, **options)
    codes = {"Inaara": "INA", "Hastakala": "HAS", "Aakaar": "AAK"}
    for position, name in enumerate(("Inaara", "Hastakala", "Aakaar"), 1):
        database.collections.update_one({"slug": name.lower()}, {"$setOnInsert": {"name": name, "slug": name.lower(), "position": position, "active": True}, "$set": {"code": codes[name]}}, upsert=True)
