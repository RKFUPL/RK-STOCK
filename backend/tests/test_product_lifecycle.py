from bson import ObjectId


def seed(app):
    database = app.extensions["mongo_db"]
    return database.products.insert_one({"name": "Lifecycle Product", "sku": "LIFE-001", "product_code": "LIFE-001", "active": True, "status": "active"}).inserted_id


def test_product_can_be_archived_and_reactivated(client, headers, app):
    product_id = seed(app)
    archived = client.patch(f"/api/products/{product_id}", headers=headers, json={"active": False})
    assert archived.status_code == 200
    assert archived.json["active"] is False
    assert archived.json["status"] == "archived"
    restored = client.patch(f"/api/products/{product_id}", headers=headers, json={"active": True})
    assert restored.status_code == 200
    assert restored.json["active"] is True
    assert restored.json["status"] == "active"


def test_delete_is_protected_by_variants_and_preserves_history(client, headers, app):
    database = app.extensions["mongo_db"]
    product_id = seed(app)
    variant_id = database.inventory_variants.insert_one({"product_id": product_id, "configuration_id": ObjectId(), "inventory_sku": "LIFE-001-M", "size": "M"}).inserted_id
    response = client.delete(f"/api/products/{product_id}", headers=headers)
    assert response.status_code == 409
    assert response.json["dependencies"]["variants"] == 1
    assert database.products.find_one({"_id": product_id}) is not None
    assert database.inventory_variants.find_one({"_id": variant_id}) is not None


def test_unreferenced_product_can_be_deleted_and_permission_is_required(client, headers, app):
    product_id = seed(app)
    assert client.delete(f"/api/products/{product_id}", headers=headers).status_code == 200
    assert app.extensions["mongo_db"].products.find_one({"_id": product_id}) is None
    assert client.delete(f"/api/products/{ObjectId()}").status_code == 401
