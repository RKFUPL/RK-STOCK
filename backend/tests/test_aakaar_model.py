from app.fx import FxProvider, FxProviderError


def test_configuration_preserves_source_fields_and_colour_level_price(client, headers, app):
    response = client.post("/api/linesheets", headers=headers, json={
        "name": "Aakaar preparation",
        "collection": "Aakaar",
        "items": [{
            "product_code": "CK-207",
            "vendor_code": "CK-207-Ivory",
            "sku": "RSKC052640",
            "description": "CK-207",
            "color": "Ivory",
            "category": "Saree Set",
            "component_count": 2,
            "mrp": 175001,
            "currency": "INR",
            "tax_inclusive": True,
            "size_quantities": {"M": 1},
            "size_measurements": {"M": {"waist": 30}},
            "po_reference": "OR-432708",
            "po_delivery_date": "2026-07-01",
        }],
    })
    assert response.status_code == 201
    database = app.extensions["mongo_db"]
    configuration = database.product_configurations.find_one({"source_client_sku": "RSKC052640"})
    assert configuration["product_code"] == "CK-207"
    assert configuration["source_vendor_code"] == "CK-207-Ivory"
    assert configuration["color"] == "Ivory"
    assert configuration["set_of"] == 2
    assert configuration["mrp"] == "175001.00"
    assert configuration["currency"] == "INR"
    assert configuration["tax_inclusive"] is True
    assert configuration["source_order_quantities"] == {"M": 1}
    assert database.stock_balances.count_documents({}) == 0


def test_inventory_variant_preserves_order_quantity_without_creating_stock(client, headers, app):
    sheet = client.post("/api/linesheets", headers=headers, json={
        "name": "Aakaar variant test", "collection": "Aakaar", "items": [{
            "product_code": "CK-207", "vendor_code": "CK-207-Red", "sku": "RSKC052641",
            "description": "CK-207", "color": "Red", "component_count": 2,
            "mrp": 175001, "size_quantities": {"M": 1},
        }],
    }).json
    base = client.get(f"/api/linesheets/{sheet['id']}", headers=headers).json["linesheet"]["items"][0]["linesheet_sku"]
    response = client.post("/api/inventory/variants", headers=headers, json={"linesheet_sku": base, "sizes": ["M"], "quantities": {}})
    assert response.status_code == 201
    variant = app.extensions["mongo_db"].inventory_variants.find_one({"linesheet_sku": base})
    assert variant["source_order_quantity"] == 1
    assert app.extensions["mongo_db"].stock_balances.count_documents({}) == 0


def test_physical_inventory_requires_explicit_approved_location(client, headers, app):
    sheet = client.post("/api/linesheets", headers=headers, json={
        "name": "Aakaar stock location test", "collection": "Aakaar", "items": [{
            "product_code": "CK-207", "description": "CK-207", "color": "Red", "set_of": 2,
            "sizes": ["M"], "mrp": 175001,
        }],
    }).json
    base = client.get(f"/api/linesheets/{sheet['id']}", headers=headers).json["linesheet"]["items"][0]["linesheet_sku"]
    missing_location = client.post("/api/inventory/variants", headers=headers, json={"linesheet_sku": base, "sizes": ["M"], "quantities": {"M": 1}})
    assert missing_location.status_code == 400
    assert app.extensions["mongo_db"].stock_balances.count_documents({}) == 0

    physical = client.post("/api/inventory/variants", headers=headers, json={"linesheet_sku": base, "sizes": ["M"], "quantities": {"M": 1}, "location": "MDS Client", "available_for_sale": False, "request_id": "aakaar-location"})
    assert physical.status_code == 201
    balance = app.extensions["mongo_db"].stock_balances.find_one({"sku": f"{base}-M"})
    assert balance["location"] == "MDS Client"
    assert balance["physical"] == 1
    assert balance["available_for_sale"] is False


def test_inventory_locations_are_explicit_and_non_sellable_holders_are_marked(client, headers):
    response = client.get("/api/inventory/locations", headers=headers)
    assert response.status_code == 200
    locations = {item["name"]: item["available_for_sale"] for item in response.json["locations"]}
    assert locations == {"Kolkata Flagship Store": True, "Mumbai Store": True, "MDS Client": False, "PR Team": False}


def test_fx_provider_converts_without_making_inr_non_authoritative(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"rates": {"USD": 0.012}}

    monkeypatch.setattr("app.fx.requests.get", lambda *args, **kwargs: Response())
    provider = FxProvider("https://fx.invalid/latest")
    assert provider.convert("1000", "USD") == 12
    assert provider.convert("1000", "INR") == 1000


def test_fx_provider_failure_is_explicit():
    provider = FxProvider("")
    try:
        provider.convert("1000", "USD")
    except FxProviderError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("Unconfigured FX provider must fail explicitly")
