from datetime import datetime, timedelta, timezone

import requests


class SharedAuthority:
    def __init__(self):
        self.sessions = {}

    def login(self, token, user, expires_at=None):
        self.sessions[token] = {
            "user": dict(user),
            "expiresAt": expires_at or datetime.now(timezone.utc) + timedelta(days=30),
            "revoked": False,
        }

    def response(self, method, url, **kwargs):
        token = (kwargs.get("cookies") or {}).get("rk_shared_session", "")
        session = self.sessions.get(token)
        if url.endswith("/api/auth/shared/logout"):
            if session:
                session["revoked"] = True
            return FakeResponse(200, {"message": "Logged out."})
        if not session or session["revoked"] or session["expiresAt"] <= datetime.now(timezone.utc):
            return FakeResponse(401, {"error": "Invalid or expired shared session."})
        if session["user"].get("isActive") is False:
            return FakeResponse(401, {"error": "Invalid or expired shared session."})
        session["expiresAt"] = datetime.now(timezone.utc) + timedelta(days=30)
        return FakeResponse(200, {"user": session["user"]})


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = payload

    def json(self):
        return self._payload


def configure(app):
    app.config.update(
        SHARED_AUTH_URL="https://rashikapoor.test",
        SHARED_SESSION_INTERNAL_SECRET="test-only-shared-secret",
        SHARED_SESSION_COOKIE_NAME="rk_shared_session",
        SHARED_SESSION_COOKIE_DOMAIN=".rashikapoor.test",
        SHARED_SESSION_COOKIE_SECURE=True,
    )


def use_session(client, token):
    client.set_cookie("rk_shared_session", token, domain="localhost")


def user(role="staff", active=True):
    return {
        "id": "6abd086468a0358cad9d179e",
        "email": f"{role}@rk.test",
        "displayName": f"{role.title()} User",
        "role": role,
        "isActive": active,
        "permissions": ["products:manage", "inventory:manage", "orders:manage", "customers:manage"],
    }


def test_web_session_is_accepted_by_stock_with_same_identity(client, app, monkeypatch):
    configure(app)
    authority = SharedAuthority()
    authority.login("staff-session", user("staff"))
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: authority.response("GET", url, **kwargs))
    use_session(client, "staff-session")
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json["email"] == "staff@rk.test"
    assert response.json["_id"] == user()["id"]
    cookie_header = response.headers.getlist("Set-Cookie")[0]
    assert cookie_header.startswith("rk_shared_session=")
    assert "Domain=rashikapoor.test" in cookie_header
    assert "Secure" in cookie_header and "HttpOnly" in cookie_header and "SameSite=Lax" in cookie_header


def test_customer_denied_staff_and_admin_allowed(client, app, monkeypatch):
    configure(app)
    authority = SharedAuthority()
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: authority.response("GET", url, **kwargs))
    for role, expected in (("customer", 401), ("staff", 200), ("admin", 200)):
        token = f"{role}-session"
        authority.login(token, user(role))
        use_session(client, token)
        assert client.get("/api/auth/me").status_code == expected


def test_inactive_and_expired_sessions_are_rejected_and_valid_session_rolls(client, app, monkeypatch):
    configure(app)
    authority = SharedAuthority()
    authority.login("inactive", user("staff", False))
    authority.login("expired", user("staff"), datetime.now(timezone.utc) - timedelta(seconds=1))
    authority.login("rolling", user("staff"), datetime.now(timezone.utc) + timedelta(minutes=1))
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: authority.response("GET", url, **kwargs))
    for token in ("inactive", "expired"):
        use_session(client, token)
        assert client.get("/api/auth/me").status_code == 401
    before = authority.sessions["rolling"]["expiresAt"]
    use_session(client, "rolling")
    assert client.get("/api/auth/me").status_code == 200
    assert authority.sessions["rolling"]["expiresAt"] > before


def test_logout_from_stock_revokes_web_session(client, app, monkeypatch):
    configure(app)
    authority = SharedAuthority()
    authority.login("logout-session", user("admin"))
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: authority.response("GET", url, **kwargs))
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: authority.response("POST", url, **kwargs))
    use_session(client, "logout-session")
    assert client.post("/api/auth/logout").status_code == 200
    assert authority.sessions["logout-session"]["revoked"] is True
    use_session(client, "logout-session")
    assert client.get("/api/auth/me").status_code == 401


def test_stock_logout_fails_closed_when_web_revocation_is_unavailable(client, app, monkeypatch):
    configure(app)
    authority = SharedAuthority()
    authority.login("retry-session", user("staff"))
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: authority.response("GET", url, **kwargs))
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.ConnectionError()))
    use_session(client, "retry-session")
    response = client.post("/api/auth/logout")
    assert response.status_code == 503
    assert authority.sessions["retry-session"]["revoked"] is False
    assert not any("Max-Age=0" in value for value in response.headers.getlist("Set-Cookie"))
