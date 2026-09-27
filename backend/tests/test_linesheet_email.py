import base64
import io
import zipfile
import pytest
from app.mail import ZohoMailClient


def _create_linesheet(client, headers):
    response = client.post("/api/linesheets", headers=headers, json={"name": "Email Preview", "collection": "Inaara", "items": [{"product_code": "RK900", "description": "Test set", "color": "Ivory", "set_of": 2, "sizes": ["S", "M"], "mrp": 12000}]})
    assert response.status_code == 201
    return response.json["id"]


def test_linesheet_email_generates_pdf_and_excel_bytes(client, headers, monkeypatch):
    linesheet_id = _create_linesheet(client, headers)
    captured = {}
    def send(self, to_address, subject, content, sender_name=None, reply_to=None, attachments=None, cc=None, bcc=None):
        captured.update(to=to_address, cc=cc, bcc=bcc, attachments=attachments)
        return {"accepted": True, "provider_message_id": "message-1"}
    monkeypatch.setattr(ZohoMailClient, "send_message", send)
    response = client.post(f"/api/linesheets/{linesheet_id}/email", headers=headers, json={"to": "buyer@example.com", "cc": "one@example.com; two@example.com", "bcc": "archive@example.com", "subject": "Linesheet", "body": "Attached", "attachments": "both", "request_id": "email-request-1"})
    assert response.status_code == 200
    assert captured["cc"] == "one@example.com,two@example.com"
    assert captured["attachments"][0][1].startswith(b"%PDF")
    assert captured["attachments"][1][1].startswith(b"PK")


def test_linesheet_email_rejects_invalid_cc(client, headers):
    linesheet_id = _create_linesheet(client, headers)
    response = client.post(f"/api/linesheets/{linesheet_id}/email", headers=headers, json={"to": "buyer@example.com", "cc": "not-an-email", "subject": "Linesheet", "body": "Attached", "attachments": "pdf", "request_id": "email-request-2"})
    assert response.status_code == 400
    assert "Invalid email address" in response.json["error"]


def test_excel_preview_returns_generated_workbook_without_download(client, headers):
    linesheet_id = _create_linesheet(client, headers)
    response = client.get(f"/api/linesheets/{linesheet_id}/preview.xlsx", headers=headers)
    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json["worksheets"][0]["rows"][0][0] == "Sr No"
    assert response.json["worksheets"][0]["rows"][1][2] == "RK900"


@pytest.mark.parametrize(("kind", "extensions"), [("pdf", [".pdf"]), ("excel", [".xlsx"]), ("both", [".pdf", ".xlsx"])])
def test_linesheet_email_generates_selected_attachment_formats(client, headers, monkeypatch, kind, extensions):
    linesheet_id = _create_linesheet(client, headers)
    captured = []
    def send(self, to_address, subject, content, sender_name=None, reply_to=None, attachments=None, cc=None, bcc=None):
        captured.extend(attachments or [])
        return {"accepted": True, "provider_message_id": "message-selected"}
    monkeypatch.setattr(ZohoMailClient, "send_message", send)
    response = client.post(f"/api/linesheets/{linesheet_id}/email", headers=headers, json={"to": "buyer@example.com", "subject": "Linesheet", "body": "Attached", "attachments": kind, "request_id": f"selected-{kind}"})
    assert response.status_code == 200
    assert [next(ext for ext in extensions if name.endswith(ext)) for name, _, _ in captured] == extensions


def test_excel_export_and_email_embed_saved_product_image(client, headers, monkeypatch):
    linesheet_id = _create_linesheet(client, headers)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    uploaded = client.post(f"/api/linesheets/{linesheet_id}/images", headers=headers, data={"product_code": "RK900", "file": (io.BytesIO(png), "product.png")}, content_type="multipart/form-data")
    assert uploaded.status_code == 201
    exported = client.get(f"/api/linesheets/{linesheet_id}/export.xlsx", headers=headers)
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
        assert any(name.startswith("xl/media/") for name in archive.namelist())
    captured = []
    monkeypatch.setattr(ZohoMailClient, "send_message", lambda self, to_address, subject, content, sender_name=None, reply_to=None, attachments=None, cc=None, bcc=None: captured.extend(attachments or []) or {"accepted": True, "provider_message_id": "image-email"})
    emailed = client.post(f"/api/linesheets/{linesheet_id}/email", headers=headers, json={"to": "buyer@example.com", "subject": "Images", "body": "Attached", "attachments": "excel", "request_id": "image-email"})
    assert emailed.status_code == 200
    with zipfile.ZipFile(io.BytesIO(captured[0][1])) as archive:
        assert any(name.startswith("xl/media/") for name in archive.namelist())


def test_excel_export_skips_missing_image_without_failing(client, headers, app):
    linesheet_id = _create_linesheet(client, headers)
    from bson import ObjectId
    app.extensions["mongo_db"].linesheets.update_one({"_id": ObjectId(linesheet_id)}, {"$set": {"items.0.images": [{"id": "missing", "path": "missing-file.png", "content_type": "image/png"}]}})
    response = client.get(f"/api/linesheets/{linesheet_id}/export.xlsx", headers=headers)
    assert response.status_code == 200
    assert response.data.startswith(b"PK")
