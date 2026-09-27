from io import BytesIO


def test_client_linesheet_and_multiple_purchase_orders_persist(client, headers, app):
    db = app.extensions["mongo_db"]
    result = client.post("/api/clients", json={"name": "Aakar Test", "client_code": "AAK-T", "category": "direct", "contact_person": "Test Contact", "email": "client@example.com", "phone": "9999999999", "address": "Test address"}, headers=headers)
    assert result.status_code == 201
    client_id = result.json["id"]
    upload = client.post(f"/api/clients/{client_id}/linesheets", data={"title": "Wedding Collection", "type": "consignment", "file": (BytesIO(b"PK\x03\x04workbook"), "collection.xlsx")}, headers=headers, content_type="multipart/form-data")
    assert upload.status_code == 201
    sheet_id = upload.json["id"]
    assert "stored_path" not in upload.json["item"]
    assert db.client_linesheets.count_documents({"_id": __import__("bson").ObjectId(sheet_id)}) == 1
    downloaded_sheet = client.get(f"/api/client-linesheets/{sheet_id}/download", headers=headers)
    assert downloaded_sheet.status_code == 200
    assert downloaded_sheet.data.startswith(b"PK\x03\x04")
    document_ids = []
    for name in ("PO-001.pdf", "PO-002.pdf"):
        response = client.post(f"/api/client-linesheets/{sheet_id}/purchase-orders", data={"file": (BytesIO(b"%PDF-1.7 test"), name)}, headers=headers, content_type="multipart/form-data")
        assert response.status_code == 201
        document_ids.append(response.json["id"])
    listing = client.get(f"/api/clients/{client_id}/linesheets", headers=headers)
    assert listing.status_code == 200
    assert listing.json["items"][0]["purchase_order_count"] == 2
    assert client.get(f"/api/client-linesheets/{sheet_id}/purchase-orders", headers=headers).json["items"]
    downloaded_po = client.get(f"/api/documents/{document_ids[0]}/download", headers=headers)
    assert downloaded_po.status_code == 200
    assert downloaded_po.data.startswith(b"%PDF")
