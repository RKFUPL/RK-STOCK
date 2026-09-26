from urllib.parse import parse_qs, urlparse
from app.mail import ZohoMailClient


def test_mail_status_is_sanitized_and_missing_without_authorization(client, headers, monkeypatch):
    for key in ("ZOHO_MAIL_CLIENT_ID", "ZOHO_MAIL_CLIENT_SECRET", "ZOHO_MAIL_REDIRECT_URI", "ZOHO_MAIL_TOKEN_ENCRYPTION_KEY"):
        monkeypatch.delenv(key, raising=False)
    response = client.get("/api/mail/status", headers=headers)
    assert response.status_code == 200
    assert response.json["status"] in {"missing_encryption_key", "missing_refresh_token", "incomplete"}
    assert "refresh_token_encrypted" not in response.json


def test_mail_authorization_url_uses_offline_consent_and_callback(client, headers, monkeypatch):
    monkeypatch.setenv("ZOHO_MAIL_CLIENT_ID", "mail-client")
    monkeypatch.setenv("ZOHO_MAIL_CLIENT_SECRET", "mail-secret")
    monkeypatch.setenv("ZOHO_MAIL_REDIRECT_URI", "http://localhost:5006/api/integrations/zoho/mail/callback")
    monkeypatch.setenv("ZOHO_MAIL_TOKEN_ENCRYPTION_KEY", "unused-key")
    response = client.post("/api/mail/connect", headers=headers)
    assert response.status_code == 200
    query = parse_qs(urlparse(response.json["authorization_url"]).query)
    assert query["redirect_uri"] == ["http://localhost:5006/api/integrations/zoho/mail/callback"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert "ZohoMail.accounts.READ" in query["scope"][0]


def test_mail_settings_are_admin_managed_and_sanitized(client, headers):
    response = client.patch("/api/mail/settings", headers=headers, json={"sender_display_name": "RK Fashion", "reply_to_email": "operations@rk.test", "default_signature": "Regards, RK", "notifications_enabled": True})
    assert response.status_code == 200
    status = client.get("/api/mail/status", headers=headers)
    assert status.json["email_settings"] == {"sender_display_name": "RK Fashion", "reply_to_email": "operations@rk.test", "default_signature": "Regards, RK", "notifications_enabled": True}
    assert "client_secret" not in status.json
    assert "refresh_token" not in status.json


def test_mail_connection_test_verifies_account(client, headers, monkeypatch):
    monkeypatch.setattr(ZohoMailClient, "verify_account", lambda self: {"email": "admin@rk.test", "organization": "RK Fashion"})
    response = client.post("/api/mail/test", headers=headers)
    assert response.status_code == 200
    assert response.json["verified"] is True
    assert response.json["account_email"] == "admin@rk.test"


def test_mail_test_email_uses_reusable_service_without_exposing_provider_data(client, headers, monkeypatch):
    monkeypatch.setattr(ZohoMailClient, "send_message", lambda self, to_address, subject, content, sender_name=None, reply_to=None: {"accepted": True, "provider_message_id": "private-id"})
    response = client.post("/api/mail/test-email", headers=headers, json={"to": "recipient@rk.test"})
    assert response.status_code == 200
    assert response.json == {"ok": True, "accepted": True}
