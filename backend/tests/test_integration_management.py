import requests

from app.auth import hash_password
from app.utils import now


class Response:
    def __init__(self, status_code, payload):
        self.status_code, self._payload, self.ok = status_code, payload, status_code < 400
    def json(self):
        return self._payload


def configure(app):
    app.config.update(RK_STOREFRONT_URL="https://storefront.example", RK_STOREFRONT_BOOTSTRAP_SECRET="bootstrap-test-secret", RK_STOREFRONT_CLIENT_ID="rk-stock-linesheets")


def test_status_requires_authentication(client):
    assert client.get("/api/integrations/storefront/status").status_code == 401


def test_missing_configuration_is_reported_without_exposing_values(client, headers, app):
    app.config.update(RK_STOREFRONT_URL="", RK_STOREFRONT_BOOTSTRAP_SECRET="")
    response = client.post("/api/integrations/storefront/connect", headers=headers)
    assert response.status_code == 503
    assert response.json["error_kind"] == "configuration_error"
    assert set(response.json["missing"]) == {"RK_STOREFRONT_URL", "RK_STOREFRONT_BOOTSTRAP_SECRET"}


def test_connect_verifies_without_returning_or_persisting_credentials(client, headers, app, monkeypatch):
    configure(app)
    calls=[]
    def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return Response(201,{"connection_id":"connection-1"}) if url.endswith("/connect") else Response(200,{"status":"connected","client_id":"rk-stock-linesheets"})
    monkeypatch.setattr(requests,"request",request)
    response=client.post("/api/integrations/storefront/connect",headers=headers)
    assert response.status_code == 200 and response.json["status"] == "connected"
    assert "bootstrap-test-secret" not in response.get_data(as_text=True)
    record=app.extensions["mongo_db"].settings.find_one({"_id":"rk_storefront_integration"})
    assert "service_token_encrypted" not in record
    assert len(calls) == 2


def test_rejected_bootstrap_credential_is_reported(client, headers, app, monkeypatch):
    configure(app)
    monkeypatch.setattr(requests,"request",lambda *args,**kwargs: Response(401,{"error":"rejected"}))
    response=client.post("/api/integrations/storefront/connect",headers=headers)
    assert response.status_code == 502 and response.json["error_kind"] == "credential_rejected"


def test_connection_failure_is_safe(client, headers, app, monkeypatch):
    configure(app)
    def fail(*args,**kwargs): raise requests.ConnectionError()
    monkeypatch.setattr(requests,"request",fail)
    response=client.post("/api/integrations/storefront/connect",headers=headers)
    assert response.status_code == 503
    assert app.extensions["mongo_db"].settings.find_one({"_id":"rk_storefront_integration"}) is None


def test_disconnect_revokes_remote_before_removing_local_token(client, headers, app, monkeypatch):
    configure(app)
    app.extensions["mongo_db"].settings.insert_one({"_id":"rk_storefront_integration","status":"connected"})
    monkeypatch.setattr(requests,"request",lambda *args,**kwargs: Response(200,{"status":"disconnected"}))
    response=client.post("/api/integrations/storefront/disconnect",headers=headers)
    record=app.extensions["mongo_db"].settings.find_one({"_id":"rk_storefront_integration"})
    assert response.status_code == 200 and record["status"] == "disconnected"
    assert "service_token_encrypted" not in record


def test_effective_permission_required_for_mutation(client, app):
    configure(app)
    app.extensions["mongo_db"].users.insert_one({"name":"Viewer","email":"viewer@rk.test","password_hash":hash_password("strong-viewer-password"),"role":"sales","active":True,"created_at":now()})
    login=client.post("/api/auth/login",json={"email":"viewer@rk.test","password":"strong-viewer-password"})
    viewer={"Authorization":f"Bearer {login.json['token']}"}
    assert client.get("/api/integrations/storefront/status",headers=viewer).status_code == 200
    assert client.post("/api/integrations/storefront/connect",headers=viewer).status_code == 403
    assert client.post("/api/integrations/storefront/sync-catalog",headers=viewer).status_code == 403
