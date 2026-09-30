from bson import ObjectId

from app.aakaar_import import build_aakaar_projection
from app.utils import now


def _aakaar_import():
    groups = {
        "CK-201": ["Red", "Beige", "Royal Blue", "Hot Pink"],
        "CK-204": ["Red", "Ivory", "Black"],
        "CK-207": ["Red", "Ivory"],
        "CK-203": ["Beige", "Royal Blue", "Ivory", "Powder Blue"],
        "CK-205": ["Beige", "Black", "Taupe"],
        "CK-211": ["Beige", "Royal Blue"],
        "CK-212": ["Beige", "Hot Pink", "Black"],
        "CK-208": ["Royal Blue", "Ivory", "Black", "Powder Blue"],
        "CK-168": ["Royal Blue"], "CK-213": ["Hot Pink", "Red", "Beige"],
        "CK-90-A": ["Hot Pink", "Powder Blue", "Royal Blue"], "CK-155-A": ["Hot Pink"],
        "CK-202": ["Ivory", "Taupe"], "CK-210": ["Ivory", "Powder Blue"],
        "CK-97": ["Black", "Red"], "CK-191": ["Black", "Powder Blue"],
        "CK-88-A": ["Taupe", "Powder Blue", "Black"], "CK-171": ["Powder Blue"], "CK-209": ["Ivory", "Taupe"],
    }
    rows = []
    row_number = 2
    serial = 1
    for base, colors in groups.items():
        for color in colors:
            source = f"RSKC{serial:06d}"
            component = 3 if base == "CK-207" and color == "Ivory" else 2
            values = [serial, f"{base}-{color}", source, color, "Saree Set", component, 100000 + serial, "OR-TEST"]
            rows.append({"row_number": row_number, "values": values, "sku": source, "size_quantities": {"M": 1}, "size_measurements": {"M": {"waist": 30}}, "references": ["OR-TEST"], "errors": []})
            row_number += 1
            serial += 1
    return {"mapping": {"vendor_code": 1, "sku": 2, "color": 3, "category": 4, "component_count": 5, "mrp": 6, "remark": 7}, "preview": rows}


def test_aakaar_projection_creates_19_products_47_configurations_and_variants():
    projection = build_aakaar_projection(_aakaar_import(), {"name": "Aakaar", "code": "AAK", "slug": "aakaar"})
    assert projection["valid"]
    assert len(projection["products"]) == 19
    assert len(projection["configurations"]) == 47
    assert len(projection["variants"]) == 47
    assert projection["physical_stock_records"] == 0
    assert all(item["physical"] == item["reserved"] == item["available"] == 0 for item in projection["variants"])
    assert all(item["location"] is None and item["available_for_sale"] is False for item in projection["variants"])


def test_aakaar_projection_preserves_ck207_correction_and_source_ids():
    projection = build_aakaar_projection(_aakaar_import(), {"name": "Aakaar", "code": "AAK", "slug": "aakaar"})
    ck207 = {item["color"]: item for item in projection["configurations"] if item["product_code"] == "CK-207"}
    assert set(ck207) == {"Red", "Ivory"}
    assert ck207["Red"]["component_count"] == 2
    assert ck207["Ivory"]["component_count"] == 2
    assert ck207["Red"]["source_vendor_code"] == "CK-207-Red"
    assert ck207["Ivory"]["source_vendor_code"] == "CK-207-Ivory"
    assert all(item["currency"] == "INR" and item["tax_inclusive"] is True for item in projection["configurations"])


def test_aakaar_projection_rejects_duplicates_before_any_write():
    imported = _aakaar_import()
    imported["preview"].append(imported["preview"][0].copy())
    projection = build_aakaar_projection(imported, {"name": "Aakaar", "code": "AAK", "slug": "aakaar"})
    assert not projection["valid"]
    assert any(error["kind"] == "duplicate_source_sku" for error in projection["errors"])
    assert any(error["kind"] == "duplicate_vendor_code" for error in projection["errors"])


def test_aakaar_projection_rejects_identity_collisions():
    projection = build_aakaar_projection(_aakaar_import(), {"name": "Aakaar", "code": "AAK", "slug": "aakaar"}, {"product_codes": {"CK-207"}, "configuration_skus": set(), "inventory_skus": set()})
    assert not projection["valid"]
    assert any(error["kind"] == "product_collision" for error in projection["errors"])


def test_aakaar_commit_returns_json_serializable_success_response(client, headers, app):
    database = app.extensions["mongo_db"]
    test_client = {"_id": ObjectId(), "name": "Aakaar API Test Client", "category": "mds", "status": "active"}
    database.clients.insert_one(test_client)
    imported = _aakaar_import()
    imported.update({
        "import_id": "aakaar-json-response-test",
        "filename": "aakaar-import-source.xlsx",
        "source_path": "tests/aakaar-import-source.xlsx",
        "worksheet": "OutRight Order Details",
        "status": "preview",
        "created_by": ObjectId(),
        "created_at": now(),
    })
    user = database.users.find_one({"email": "admin@rk.test"})
    imported["created_by"] = user["_id"]
    database.imports.insert_one(imported)

    response = client.post(
        f"/api/linesheets/import/{imported['import_id']}/commit",
        headers=headers,
        json={
            "client_id": str(test_client["_id"]),
            "collection": "Aakaar",
            "type": "mds_outright",
            "name": "Aakaar JSON Response Test",
            "model": "aakaar",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["id"] == payload["summary"]["linesheet_id"]
    assert payload["summary"]["products_created"] == 19
    assert payload["summary"]["configurations_created"] == 47
    assert payload["summary"]["variants_created"] == 47
    assert isinstance(payload["summary"]["linesheet_id"], str)
