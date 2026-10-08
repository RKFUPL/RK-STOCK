from app.catalog_sync import CatalogSyncService


class Storefront:
    record_id = "rk_storefront_integration"

    def __init__(self, product_name="Web Saree", invalid=False):
        self.product_name = product_name
        self.invalid = invalid

    def catalog_snapshot(self):
        product = {"id": "web-product-1", "sku": "HK-173-HP", "name": self.product_name, "slug": "173-hot-pink", "description": "Storefront description", "category": "Couture", "collection_ids": ["web-hastakala", "web-runway"], "price": 125000, "currency": "INR", "tax_inclusive": True, "status": "active", "active": True, "images": ["https://legacy.invalid/ignored.jpg"], "media": [{"url": "https://res.cloudinary.com/example/image/upload/primary.jpg", "position": 0, "is_primary": True, "source": "rk-web"}, {"url": "https://res.cloudinary.com/example/image/upload/gallery.jpg", "position": 1, "is_primary": False, "source": "rk-web"}], "sizes": ["M"], "colours": ["Hot Pink"]}
        if self.invalid:
            product.pop("id")
        return {
            "products": {"items": [product]},
            "categories": {"items": [{"id": "category:couture", "name": "Couture", "slug": "couture"}]},
            "collections": {"items": [{"id": "web-hastakala", "name": "Hastakala", "slug": "collections-of-hasthkala", "code": "HAS", "active": True, "status": "collection"}, {"id": "web-runway", "name": "Runway", "slug": "runway", "code": "RUN", "active": True, "status": "collection"}]},
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
    assert first["collections"]["created"] + first["collections"]["updated"] == 2
    assert second["products"]["unchanged"] == 1
    assert second["categories"]["unchanged"] == 1
    assert second["collections"]["unchanged"] == 2
    product = database.products.find_one({"source_system": "rk-web", "source_id": "web-product-1"})
    assert product["sku"] == "HK-173-HP"
    assert product["collection_names"] == ["Hastakala", "Runway"]
    assert product["collection"] is None
    assert len(product["collection_ids"]) == 2
    assert product["images"][0] == {"url": "https://res.cloudinary.com/example/image/upload/primary.jpg", "position": 0, "is_main": True, "source": "rk-web"}
    assert product["images"][1]["url"] == "https://res.cloudinary.com/example/image/upload/gallery.jpg"
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


def test_existing_matching_collection_is_linked_without_duplicate_or_aakaar_assignment(app):
    database = app.extensions["mongo_db"]
    actor = database.users.find_one({"email": "admin@rk.test"})["_id"]
    existing = database.collections.find_one({"name": "Hastakala"})
    existing_id = existing["_id"]

    with app.app_context():
        CatalogSyncService(Storefront()).sync(actor)

    product = database.products.find_one({"source_id": "web-product-1"})
    assert database.collections.count_documents({"slug": "collections-of-hasthkala"}) == 1
    assert database.collections.find_one({"_id": existing_id})["source_id"] == "web-hastakala"
    assert existing_id in product["collection_ids"]
    assert "Aakaar" not in product["collection_names"]


def test_catalog_sync_preserves_stock_owned_media_and_operational_fields(app):
    database = app.extensions["mongo_db"]
    actor = database.users.find_one({"email": "admin@rk.test"})["_id"]
    product_id = database.products.insert_one({
        "source_system": "rk-web", "source_id": "web-product-1", "sku": "HK-173-HP",
        "name": "Existing", "images": [
            {"id": "stock-workdrive", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/stock-media", "url": "https://workdrive.zoho.in/file/stock-media", "source": "rk-stock", "position": 4, "is_primary": True},
            {"url": "https://res.cloudinary.com/stock/owned.jpg", "source": "rk-stock", "position": 5, "is_main": False},
        ], "physical": 8, "reserved": 2, "available": 6, "stock_only_note": "preserve",
    }).inserted_id
    with app.app_context():
        CatalogSyncService(Storefront()).sync(actor)
    product = database.products.find_one({"_id": product_id})
    assert {item.get("permalink") for item in product["images"] if item.get("provider") == "zoho_workdrive"} == {"https://workdrive.zoho.in/file/stock-media"}
    assert "https://res.cloudinary.com/stock/owned.jpg" in {item.get("url") for item in product["images"]}
    assert product["physical"] == 8
    assert product["reserved"] == 2
    assert product["available"] == 6
    assert product["stock_only_note"] == "preserve"
