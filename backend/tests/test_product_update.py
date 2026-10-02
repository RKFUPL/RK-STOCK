from bson import ObjectId
from app.auth import hash_password


def seed_product(app):
    database = app.extensions["mongo_db"]
    existing = database.collections.find_one({"name": "Hastakala"})
    first = existing["_id"] if existing else database.collections.insert_one({"name": "Hastakala", "slug": "hastakala", "code": "HAS", "active": True}).inserted_id
    second = database.collections.insert_one({"name": "Product Update Test Collection", "slug": "product-update-test", "code": "PUT", "active": True}).inserted_id
    database.settings.insert_one({"_id": "global", "categories": ["Couture", "Saree"]})
    product = database.products.insert_one({
        "name": "173 - Hot Pink", "sku": "HK-173-HP", "product_code": "HK-173-HP",
        "category": "Couture", "collection": "Hastakala", "collection_id": first,
        "collection_ids": [first], "colors": ["Hot Pink"], "sizes": ["M"],
        "selling_price": "125000.00", "active": True, "status": "active",
        "description": "Original description", "inventory_marker": "preserve",
    }).inserted_id
    return product, first, second


def test_product_update_supports_fields_and_multiple_collections(client, headers, app):
    product, first, second = seed_product(app)
    response = client.patch(f"/api/products/{product}", headers=headers, json={
        "name": "173 - Hot Pink Updated", "sku": "HK-173-HP-UPDATED", "color": "Rose",
        "category": "Couture", "description": "Updated description", "selling_price": 130000,
        "collection_ids": [str(first), str(second)], "active": True,
    })
    assert response.status_code == 200
    saved = app.extensions["mongo_db"].products.find_one({"_id": product})
    assert saved["sku"] == "HK-173-HP-UPDATED"
    assert saved["colors"] == ["Rose"]
    assert saved["collection_ids"] == [first, second]
    assert saved["collection_names"] == ["Hastakala", "Product Update Test Collection"]
    assert saved["collection"] is None
    assert saved["inventory_marker"] == "preserve"


def test_product_update_rejects_unauthorized_user(client, app):
    database = app.extensions["mongo_db"]
    product, _, _ = seed_product(app)
    database.users.insert_one({"name": "Sales", "email": "sales@rk.test", "password_hash": hash_password("sales-password"), "role": "sales", "active": True})
    login = client.post("/api/auth/login", json={"email": "sales@rk.test", "password": "sales-password"})
    assert login.status_code == 200
    response = client.patch(f"/api/products/{product}", headers={"Authorization": f"Bearer {login.json['token']}"}, json={"name": "Nope"})
    assert response.status_code == 403


def test_product_update_rejects_invalid_id_duplicate_sku_and_invalid_collection(client, headers, app):
    product, _, _ = seed_product(app)
    assert client.patch("/api/products/not-an-object-id", headers=headers, json={"name": "Nope"}).status_code == 400
    duplicate = app.extensions["mongo_db"].products.insert_one({"name": "Other", "sku": "OTHER", "product_code": "OTHER", "active": True}).inserted_id
    assert client.patch(f"/api/products/{product}", headers=headers, json={"sku": "OTHER"}).status_code == 409
    assert client.patch(f"/api/products/{product}", headers=headers, json={"product_code": "OTHER"}).status_code == 409
    assert client.patch(f"/api/products/{duplicate}", headers=headers, json={"category": "Unknown"}).status_code == 400
    assert client.patch(f"/api/products/{product}", headers=headers, json={"collection_ids": [str(ObjectId())]}).status_code == 400


def test_product_update_can_clear_collections_without_assigning_aakaar(client, headers, app):
    product, _, _ = seed_product(app)
    response = client.patch(f"/api/products/{product}", headers=headers, json={"collection_ids": []})
    assert response.status_code == 200
    saved = app.extensions["mongo_db"].products.find_one({"_id": product})
    assert saved["collection_ids"] == []
    assert saved["collection_names"] == []
    assert saved["collection"] is None
    assert "Aakaar" not in saved["collection_names"]
