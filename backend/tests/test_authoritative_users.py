from app.auth import hash_password
from app.utils import now


def login_user(client, app, *, role="admin", suffix="manager"):
    app.extensions["mongo_db"].users.insert_one({
        "name": "Local Manager", "username": suffix, "email": f"{suffix}@rk.test",
        "password_hash": hash_password("strong-local-password"), "role": role,
        "active": True, "source": "local", "created_at": now(), "updated_at": now(),
    })
    return client.post("/api/auth/login", json={"identifier": suffix, "password": "strong-local-password"})


def test_admin_lists_and_creates_users_in_stock_authority(client, app):
    assert login_user(client, app).status_code == 200
    created = client.post("/api/users", json={"firstName": "Test", "lastName": "User", "username": "testuser", "email": "test@rk.test", "role": "staff", "password": "temporary-password", "isActive": True})
    listed = client.get("/api/users")
    assert created.status_code == 201
    assert listed.status_code == 200
    assert app.extensions["mongo_db"].users.find_one({"email": "test@rk.test"})
    assert "temporary-password" not in created.get_data(as_text=True)


def test_staff_cannot_use_user_management_writes(client, app):
    assert login_user(client, app, role="staff", suffix="staffmanager").status_code == 200
    response = client.post("/api/users", json={"firstName": "No", "username": "forbidden", "email": "forbidden@rk.test", "role": "staff", "password": "temporary-password"})
    assert response.status_code == 403


def test_forced_local_user_can_only_reach_auth_endpoints(client, app):
    app.extensions["mongo_db"].users.insert_one({
        "name": "Forced User", "username": "forced", "email": "forced@rk.test",
        "password_hash": hash_password("temporary-password"), "role": "staff", "active": True,
        "must_change_password": True, "source": "local", "created_at": now(), "updated_at": now(),
    })
    assert client.post("/api/auth/login", json={"identifier": "forced", "password": "temporary-password"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    blocked = client.get("/api/dashboard")
    assert blocked.status_code == 403
    assert blocked.json["must_change_password"] is True


def test_authenticated_user_can_read_profile_without_web(client, app, monkeypatch):
    assert login_user(client, app).status_code == 200
    monkeypatch.setattr("app.routes.requests.get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RK-WEB must not be called")))
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json["email"] == "manager@rk.test"
    assert response.json["role"] == "admin"


def test_admin_can_delete_inactive_user_and_preserve_identity_mapping(client, app):
    assert login_user(client, app).status_code == 200
    database = app.extensions["mongo_db"]
    result = database.users.insert_one({"name": "Inactive", "username": "inactive", "email": "inactive@rk.test", "password_hash": hash_password("inactive-password"), "role": "staff", "active": False, "created_at": now()})
    user_id = result.inserted_id
    database.user_identity_links.insert_one({"rk_stock_user_id": user_id, "rk_web_user_id": "web-inactive", "status": "active"})
    database.auth_sessions.insert_one({"user_id": user_id, "token_hash": "inactive-session", "source": "local", "revoked_at": None})
    response = client.delete(f"/api/users/{user_id}")
    assert response.status_code == 200
    assert database.users.find_one({"_id": user_id}) is None
    assert database.user_identity_links.find_one({"rk_stock_user_id": user_id})["status"] == "deleted"
    assert database.auth_sessions.find_one({"user_id": user_id})["revoked_at"] is not None
    assert database.activity_log.find_one({"entity_id": str(user_id), "action": "user_deleted"})


def test_user_delete_requires_inactive(client, app):
    assert login_user(client, app).status_code == 200
    database = app.extensions["mongo_db"]
    result = database.users.insert_one({"name": "Active", "username": "active", "email": "active@rk.test", "password_hash": hash_password("active-password"), "role": "staff", "active": True, "created_at": now()})
    assert client.delete(f"/api/users/{result.inserted_id}").status_code == 409
