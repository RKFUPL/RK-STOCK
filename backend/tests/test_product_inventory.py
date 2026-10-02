from bson import ObjectId


def setup_product(app):
    database = app.extensions["mongo_db"]
    product_id = database.products.insert_one({"name": "Inventory Product", "sku": "INV-001", "product_code": "INV-001", "colors": ["Red"], "active": True}).inserted_id
    configuration_id = database.product_configurations.insert_one({"product_id": product_id, "linesheet_sku": "INV-001", "product_code": "INV-001", "color": "Red", "set_of": 1}).inserted_id
    variant_id = database.inventory_variants.insert_one({"configuration_id": configuration_id, "product_id": product_id, "inventory_sku": "INV-001-M", "product_code": "INV-001", "color": "Red", "size": "M", "active": True}).inserted_id
    return product_id, variant_id


def adjust(client, headers, product_id, variant_id, quantity, direction="add", reason="manual_adjustment", key=None):
    return client.post(f"/api/products/{product_id}/inventory/adjust", headers={**headers, "Idempotency-Key": key or str(ObjectId())}, json={"variant_id": str(variant_id), "quantity": quantity, "direction": direction, "reason": reason, "notes": "test"})


def test_add_remove_stock_creates_ledger_and_calculates_balance(client, headers, app):
    product_id, variant_id = setup_product(app)
    received = adjust(client, headers, product_id, variant_id, 10, reason="production_received", key="receive-1")
    assert received.status_code == 201
    removed = adjust(client, headers, product_id, variant_id, 3, direction="remove", reason="manual_adjustment", key="remove-1")
    assert removed.status_code == 201
    rows = client.get(f"/api/products/{product_id}/inventory", headers=headers).json["items"]
    assert rows[0]["physical"] == 7
    assert rows[0]["reserved"] == 0
    assert rows[0]["available"] == 7
    assert rows[0]["total"] == 7
    assert app.extensions["mongo_db"].stock_ledger.count_documents({"sku": "INV-001-M"}) == 2


def test_inventory_rejects_insufficient_stock_and_unauthorized_adjustment(client, headers, app):
    product_id, variant_id = setup_product(app)
    assert adjust(client, headers, product_id, variant_id, 1, direction="remove", key="too-much").status_code == 400
    assert client.post(f"/api/products/{product_id}/inventory/adjust", json={"variant_id": str(variant_id), "quantity": 1, "direction": "add", "reason": "manual_adjustment"}).status_code == 401


def test_repeated_adjustment_is_idempotent_and_history_remains(client, headers, app):
    product_id, variant_id = setup_product(app)
    first = adjust(client, headers, product_id, variant_id, 4, key="same-request")
    second = adjust(client, headers, product_id, variant_id, 4, key="same-request")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json["created"] is False
    assert app.extensions["mongo_db"].stock_ledger.count_documents({"transaction_id": "same-request"}) == 1
    assert app.extensions["mongo_db"].stock_balances.find_one({"sku": "INV-001-M"})["physical"] == 4


def test_multiple_variants_and_historical_records_are_preserved(client, headers, app):
    product_id, variant_id = setup_product(app)
    database = app.extensions["mongo_db"]
    database.inventory_variants.insert_one({"configuration_id": ObjectId(), "product_id": product_id, "inventory_sku": "INV-001-S", "product_code": "INV-001", "color": "Red", "size": "S", "active": True})
    adjust(client, headers, product_id, variant_id, 2, key="history-1")
    assert database.stock_ledger.count_documents({"transaction_id": "history-1"}) == 1
    rows = client.get(f"/api/products/{product_id}/inventory", headers=headers).json["items"]
    assert {row["size"] for row in rows} == {"M", "S"}
    assert database.stock_ledger.find_one({"transaction_id": "history-1"}) is not None
