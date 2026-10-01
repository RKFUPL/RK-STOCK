from app.catalog_sync import CatalogSyncService


class Storefront:
    record_id = "rk_storefront_integration"

    def __init__(self, product_name="Web Saree", invalid=False):
        self.product_name = product_name
        self.invalid = invalid

    def catalog_snapshot(self):
        product = {"id": "web-product-1", "sku": "WEB-001", "name": self.product_name, "slug": "web-saree", "description": "Storefront description", "category": "Saree", "collection_ids": ["web-collection-1"], "price": 12500, "currency": "INR", "tax_inclusive": True, "status": "active", "active": True, "images": ["https://example.invalid/saree.jpg"], "sizes": ["M"], "colours": ["Red"]}
        if self.invalid:
            product.pop("id")
        return {
            "products": {"items": [product]},
            "categories": {"items": [{"id": "category:saree", "name": "Saree", "slug": "saree"}]},
            "collections": {"items": [{"id": "web-collection-1", "name": "Web Collection", "slug": "web-collection", "code": "WEB", "active": True, "status": "collection"}]},
        }


def test_catalog_sync_creates_then_is_idempotent_and_preserves_inventory(app):
    database = app.extensions["mongo_db"]
    database.stock_balances.insert_one({"sku": "EXISTING-M", "color": "Red", "size": "M", "physical": 7, "reserved": 2, "available": 5})
    before_balance = database.stock_balances.find_one({"sku": "EXISTING-M"})
    before_ledger = database.stock_ledger.count_documents({})
    actor = database.users.find_one({"email": "admin@rk.test"})["_id"]

    with app.app_context():
        first = CatalogSyncService(Storefront()).sync(actor)
        second = CatalogSyncService(Storefront()).sync(actor)

    assert first["products"]["created"] == 1
    assert first["categories"]["created"] == 1
    assert first["collections"]["created"] == 1
    assert second["products"]["unchanged"] == 1
    assert second["categories"]["unchanged"] == 1
    assert second["collections"]["unchanged"] == 1
    product = database.products.find_one({"source_system": "rk-web", "source_id": "web-product-1"})
    assert product["sku"] == "WEB-001"
    assert len(product["collection_ids"]) == 1
    assert database.products.count_documents({"source_system": "rk-web", "source_id": "web-product-1"}) == 1
    assert database.stock_balances.find_one({"sku": "EXISTING-M"}) == before_balance
    assert database.stock_ledger.count_documents({}) == before_ledger
    assert database.inventory_variants.count_documents({}) == 0


def test_changed_web_product_updates_same_source_record(app):
    database = app.extensions["mongo_db"]
    actor = database.users.find_one({"email": "admin@rk.test"})["_id"]
    with app.app_context():
        CatalogSyncService(Storefront()).sync(actor)
    original = database.products.find_one({"source_id": "web-product-1"})

    with app.app_context():
        result = CatalogSyncService(Storefront(product_name="Updated Web Saree")).sync(actor)
    updated = database.products.find_one({"source_id": "web-product-1"})

    assert result["products"]["updated"] == 1
    assert updated["_id"] == original["_id"]
    assert updated["name"] == "Updated Web Saree"


def test_invalid_product_is_skipped_without_partial_product_write(app):
    database = app.extensions["mongo_db"]
    actor = database.users.find_one({"email": "admin@rk.test"})["_id"]

    with app.app_context():
        result = CatalogSyncService(Storefront(invalid=True)).sync(actor)

    assert result["products"]["skipped"] == 1
    assert database.products.count_documents({"source_system": "rk-web"}) == 0
    assert database.inventory_variants.count_documents({}) == 0
