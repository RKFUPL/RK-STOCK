from app.auth import hash_password


def product(app):
    return app.extensions["mongo_db"].products.insert_one({"name": "Variant Product", "sku": "VP-001", "product_code": "VP-001", "colors": ["Red"], "active": True}).inserted_id


def test_create_edit_deactivate_and_remove_variant(client, headers, app):
    product_id = product(app)
    created = client.post(f"/api/products/{product_id}/variants", headers=headers, json={"size": "M", "inventory_sku": "VP-001-M"})
    assert created.status_code == 201
    variant_id = created.json["_id"]
    edited = client.patch(f"/api/products/{product_id}/variants/{variant_id}", headers=headers, json={"size": "L", "inventory_sku": "VP-001-L"})
    assert edited.status_code == 200
    assert edited.json["size"] == "L"
    deactivated = client.patch(f"/api/products/{product_id}/variants/{variant_id}", headers=headers, json={"active": False})
    assert deactivated.status_code == 200
    assert deactivated.json["status"] == "archived"
    assert client.delete(f"/api/products/{product_id}/variants/{variant_id}", headers=headers).status_code == 200


def test_variant_rejects_invalid_size_duplicate_and_unauthorized(client, headers, app):
    product_id = product(app)
    assert client.post(f"/api/products/{product_id}/variants", headers=headers, json={"size": "XXL"}).status_code == 400
    assert client.post(f"/api/products/{product_id}/variants", headers=headers, json={"size": "M"}).status_code == 201
    assert client.post(f"/api/products/{product_id}/variants", headers=headers, json={"size": "M"}).status_code == 409
    assert client.get(f"/api/products/{product_id}/variants", headers=headers).status_code == 200
    assert client.post(f"/api/products/{product_id}/variants", json={"size": "L"}).status_code == 401


def test_variant_with_stock_or_order_history_cannot_be_removed(client, headers, app):
    database = app.extensions["mongo_db"]
    product_id = product(app)
    created = client.post(f"/api/products/{product_id}/variants", headers=headers, json={"size": "M"})
    variant_id = created.json["_id"]
    sku = created.json["inventory_sku"]
    database.stock_ledger.insert_one({"transaction_id": "variant-history", "sku": sku, "quantity": 1})
    response = client.delete(f"/api/products/{product_id}/variants/{variant_id}", headers=headers)
    assert response.status_code == 409
    assert response.json["references"]["stock_ledger"] == 1


def test_sales_user_cannot_manage_variants(client, app):
    product_id = product(app)
    database = app.extensions["mongo_db"]
    database.users.insert_one({"name": "Sales", "email": "variant-sales@rk.test", "password_hash": hash_password("sales-password"), "role": "sales", "active": True})
    login = client.post("/api/auth/login", json={"email": "variant-sales@rk.test", "password": "sales-password"})
    response = client.post(f"/api/products/{product_id}/variants", headers={"Authorization": f"Bearer {login.json['token']}"}, json={"size": "M"})
    assert response.status_code == 403
