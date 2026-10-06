import requests

from app.auth import hash_password
from app.utils import now


def add_user(app, *, email="staff@rk.test", username="stockstaff", password="stock-password", role="staff", active=True, must_change=False):
    return app.extensions["mongo_db"].users.insert_one({
        "name": "Stock Staff", "username": username, "email": email,
        "password_hash": hash_password(password), "role": role, "active": active,
        "must_change_password": must_change, "source": "local", "created_at": now(), "updated_at": now(),
    }).inserted_id


def unavailable(*args, **kwargs):
    raise requests.ConnectionError("offline")


def test_local_login_and_existing_session_work_with_web_offline(client, app, monkeypatch):
    add_user(app)
    app.config.update(SHARED_AUTH_URL="https://web.invalid", SHARED_SESSION_INTERNAL_SECRET="test-secret")
    monkeypatch.setattr(requests, "get", unavailable)
    monkeypatch.setattr(requests, "post", unavailable)

    login = client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "stock-password"})
    assert login.status_code == 200
    assert login.json["shared"] is False
    assert "password_hash" not in login.get_data(as_text=True)
    assert "rk_stock_session=" in login.headers.get("Set-Cookie", "")
    stored_session = app.extensions["mongo_db"].auth_sessions.find_one({})
    assert stored_session and "token_hash" in stored_session and "token" not in stored_session
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/dashboard").status_code == 200


def test_local_login_does_not_call_web_for_500_or_timeout(client, app, monkeypatch):
    add_user(app)
    app.config.update(SHARED_AUTH_URL="https://web.invalid", SHARED_SESSION_INTERNAL_SECRET="test-secret")
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RK-WEB login must not be called")))
    assert client.post("/api/auth/login", json={"identifier": "staff@rk.test", "password": "stock-password"}).status_code == 200


def test_invalid_password_inactive_and_customer_are_rejected(client, app):
    add_user(app)
    add_user(app, email="inactive@rk.test", username="inactive", active=False)
    add_user(app, email="customer@rk.test", username="customer", role="customer")
    assert client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"identifier": "inactive", "password": "stock-password"}).status_code == 403
    assert client.post("/api/auth/login", json={"identifier": "customer", "password": "stock-password"}).status_code == 403


def test_forced_change_rotates_session_and_replaces_password(client, app):
    add_user(app, must_change=True)
    login = client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "stock-password"})
    assert login.status_code == 200
    assert login.json["user"]["must_change_password"] is True
    assert client.get("/api/dashboard").status_code == 403
    changed = client.post("/api/auth/password/change", json={"current_password": "stock-password", "password": "new-stock-password", "confirm_password": "new-stock-password"})
    assert changed.status_code == 200
    assert client.get("/api/dashboard").status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "stock-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "new-stock-password"}).status_code == 200


def test_password_change_rejects_wrong_current_weak_and_mismatched_passwords(client, app):
    add_user(app, must_change=True)
    client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "stock-password"})
    assert client.post("/api/auth/password/change", json={"current_password": "wrong-password", "password": "new-stock-password", "confirm_password": "new-stock-password"}).status_code == 400
    assert client.post("/api/auth/password/change", json={"current_password": "stock-password", "password": "short", "confirm_password": "short"}).status_code == 400
    assert client.post("/api/auth/password/change", json={"current_password": "stock-password", "password": "new-stock-password", "confirm_password": "different-password"}).status_code == 400
    stored = app.extensions["mongo_db"].users.find_one({"email": "staff@rk.test"})
    assert stored["must_change_password"] is True


def test_admin_manages_local_users_and_passwords_without_web(client, app, headers, monkeypatch):
    app.config.update(SHARED_AUTH_URL="https://web.invalid", SHARED_SESSION_INTERNAL_SECRET="test-secret")
    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("user management must remain local")))
    created = client.post("/api/users", headers=headers, json={"firstName": "Local", "lastName": "Staff", "username": "localstaff", "email": "localstaff@rk.test", "role": "staff", "password": "temporary-password", "isActive": True})
    assert created.status_code == 201
    payload = created.get_data(as_text=True)
    assert "temporary-password" not in payload and "password_hash" not in payload
    user_id = created.json["user"]["id"]
    assert client.patch(f"/api/users/{user_id}/role", headers=headers, json={"role": "admin"}).status_code == 200
    assert client.patch(f"/api/users/{user_id}/status", headers=headers, json={"isActive": False}).status_code == 200
    assert client.patch(f"/api/users/{user_id}/status", headers=headers, json={"isActive": True}).status_code == 200
    assert client.patch(f"/api/users/{user_id}/password", headers=headers, json={"password": "replacement-password"}).status_code == 200
    stored = app.extensions["mongo_db"].users.find_one({"email": "localstaff@rk.test"})
    assert stored["must_change_password"] is True
    audit = list(app.extensions["mongo_db"].activity_log.find({"entity_id": user_id}))
    assert {item["action"] for item in audit} >= {"user_created", "role_changed", "user_deactivated", "user_activated", "password_reset"}
    audit_text = str([item.get("details", {}) for item in audit])
    assert "temporary-password" not in audit_text and "replacement-password" not in audit_text and "password_hash" not in audit_text


def test_staff_cannot_manage_users(client, app):
    add_user(app)
    client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "stock-password"})
    assert client.get("/api/users").status_code == 403


def test_local_logout_succeeds_with_web_offline(client, app, monkeypatch):
    add_user(app)
    app.config.update(SHARED_AUTH_URL="https://web.invalid", SHARED_SESSION_INTERNAL_SECRET="test-secret")
    monkeypatch.setattr(requests, "post", unavailable)
    client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "stock-password"})
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_shared_session_is_primary_and_bootstraps_mapped_local_session(client, app, monkeypatch):
    local_id = add_user(app, email="sso@rk.test", username="sso-user")
    web_id = "507f1f77bcf86cd799439011"
    app.extensions["mongo_db"].user_identity_links.insert_one({"rk_web_user_id": web_id, "rk_stock_user_id": local_id, "status": "active"})
    app.config.update(SHARED_AUTH_URL="http://web.test", SHARED_SESSION_INTERNAL_SECRET="internal-test")
    class Response:
        ok = True
        status_code = 200
        def json(self):
            return {"user": {"id": web_id, "displayName": "Web Staff", "email": "sso@rk.test", "role": "staff", "isActive": True, "permissions": ["products:manage"]}}
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    client.set_cookie("rk_shared_session", "shared-token")
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json["email"] == "sso@rk.test"
    assert any("rk_stock_session=" in value for value in response.headers.getlist("Set-Cookie"))
    assert app.extensions["mongo_db"].auth_sessions.count_documents({"user_id": local_id, "source": "local"}) == 1


def test_sso_bootstrap_session_survives_complete_web_outage(client, app, monkeypatch):
    local_id = add_user(app, email="offline-admin@rk.test", username="offline-admin", role="admin")
    web_id = "507f1f77bcf86cd799439021"
    database = app.extensions["mongo_db"]
    database.user_identity_links.insert_one({"rk_web_user_id": web_id, "rk_stock_user_id": local_id, "status": "active"})
    app.config.update(SHARED_AUTH_URL="http://web.test", SHARED_SESSION_INTERNAL_SECRET="internal-test")

    class Response:
        ok = True
        status_code = 200

        def json(self):
            return {"user": {"id": web_id, "displayName": "Offline Admin", "email": "offline-admin@rk.test", "role": "admin", "isActive": True, "permissions": []}}

    remote_calls = []

    def shared_me(*args, **kwargs):
        remote_calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr(requests, "get", shared_me)
    client.set_cookie("rk_shared_session", "shared-offline-token")
    bootstrap = client.get("/api/auth/me")
    assert bootstrap.status_code == 200
    assert any(value.startswith("rk_stock_session=") for value in bootstrap.headers.getlist("Set-Cookie"))
    session = database.auth_sessions.find_one({"user_id": local_id, "source": "local", "revoked_at": None})
    assert session and session.get("token_hash") and "token" not in session
    assert len(remote_calls) == 1

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("valid Stock session must not contact RK-WEB")))
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/stock").status_code == 200
    assert client.get("/api/users").status_code == 200
    assert database.activity_log.count_documents({"entity_id": str(local_id), "action": "sso_login"}) == 1


def test_explicit_logout_revokes_sso_bootstrap_session_but_local_password_still_works(client, app, monkeypatch):
    local_id = add_user(app, email="logout-admin@rk.test", username="logout-admin", role="admin")
    web_id = "507f1f77bcf86cd799439022"
    database = app.extensions["mongo_db"]
    database.user_identity_links.insert_one({"rk_web_user_id": web_id, "rk_stock_user_id": local_id, "status": "active"})
    app.config.update(SHARED_AUTH_URL="http://web.test", SHARED_SESSION_INTERNAL_SECRET="internal-test")

    class Response:
        ok = True
        status_code = 200

        def json(self):
            return {"user": {"id": web_id, "displayName": "Logout Admin", "email": "logout-admin@rk.test", "role": "admin", "isActive": True, "permissions": []}}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    client.set_cookie("rk_shared_session", "shared-logout-token")
    assert client.get("/api/auth/me").status_code == 200
    client.delete_cookie("rk_shared_session")
    monkeypatch.setattr(requests, "post", unavailable)
    assert client.post("/api/auth/logout").status_code == 200
    assert database.auth_sessions.count_documents({"user_id": local_id, "revoked_at": None}) == 0
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"identifier": "logout-admin", "password": "stock-password"}).status_code == 200


def test_invalid_shared_session_falls_back_to_local_session(client, app, monkeypatch):
    add_user(app)
    client.post("/api/auth/login", json={"identifier": "stockstaff", "password": "stock-password"})
    app.config.update(SHARED_AUTH_URL="http://web.test", SHARED_SESSION_INTERNAL_SECRET="internal-test")
    class Response:
        ok = False
        status_code = 401
        def json(self): return {"error": "rejected"}
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    client.set_cookie("rk_shared_session", "invalid-token")
    assert client.get("/api/dashboard").status_code == 200


def test_shared_admin_without_mapping_is_provisioned_into_local_users(client, app, monkeypatch):
    web_id = "507f1f77bcf86cd799439012"
    app.config.update(SHARED_AUTH_URL="http://web.test", SHARED_SESSION_INTERNAL_SECRET="internal-test")
    class Response:
        ok = True
        status_code = 200
        def json(self):
            return {"user": {"id": web_id, "displayName": "RK Local Admin", "username": "rk-admin", "email": "rk-admin@rk.test", "role": "admin", "isActive": True, "permissions": []}}
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    client.set_cookie("rk_shared_session", "shared-token")
    assert client.get("/api/auth/me").status_code == 200
    stored = app.extensions["mongo_db"].users.find_one({"email": "rk-admin@rk.test"})
    assert stored and stored["source"] == "rk-web-sso" and stored["must_change_password"] is True
    assert app.extensions["mongo_db"].user_identity_links.find_one({"rk_web_user_id": web_id, "rk_stock_user_id": stored["_id"]})
    assert any(user["email"] == "rk-admin@rk.test" for user in client.get("/api/users").json["users"])
    assert app.extensions["mongo_db"].users.count_documents({"email": "rk-admin@rk.test"}) == 1
    stored = app.extensions["mongo_db"].users.find_one({"email": "rk-admin@rk.test"})
    first_login = stored["last_login_at"]
    assert {item["action"] for item in app.extensions["mongo_db"].activity_log.find({"entity_id": str(stored["_id"])})} >= {"user_provisioned", "sso_login"}
    client.get("/api/auth/me")
    again = app.extensions["mongo_db"].users.find_one({"_id": stored["_id"]})
    assert again["last_login_at"] == first_login
    assert app.extensions["mongo_db"].activity_log.count_documents({"entity_id": str(stored["_id"]), "action": "sso_login"}) == 1


def test_customer_shared_session_is_not_provisioned(client, app, monkeypatch):
    app.config.update(SHARED_AUTH_URL="http://web.test", SHARED_SESSION_INTERNAL_SECRET="internal-test")
    class Response:
        ok = True
        status_code = 200
        def json(self): return {"user": {"id": "507f1f77bcf86cd799439013", "email": "customer@rk.test", "role": "customer", "isActive": True, "permissions": []}}
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    client.set_cookie("rk_shared_session", "shared-token")
    assert client.get("/api/auth/me").status_code == 401
    assert app.extensions["mongo_db"].users.find_one({"email": "customer@rk.test"}) is None
