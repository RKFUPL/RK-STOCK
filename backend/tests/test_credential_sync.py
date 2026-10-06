from app.auth import hash_password
from app.credential_sync import ensure_identity_link, queue_credential_event
from app.utils import now
import jwt
from datetime import datetime, timezone, timedelta


def local_user(app):
    result = app.extensions["mongo_db"].users.insert_one({
        "name": "Sync User", "username": "sync-user", "email": "sync@rk.test",
        "password_hash": hash_password("local-password"), "role": "staff", "active": True,
        "credential_version": 3, "profile_version": 2, "created_at": now(), "updated_at": now(),
    })
    return app.extensions["mongo_db"].users.find_one({"_id": result.inserted_id})


def test_outbox_contains_metadata_only(app):
    with app.app_context():
        user = local_user(app)
        link_id = ensure_identity_link(user["_id"], email=user["email"], username=user["username"])
        event = queue_credential_event(user, "PASSWORD_CHANGED", metadata={"password": "must-not-persist", "password_hash": "must-not-persist", "role": "staff"})
        stored = app.extensions["mongo_db"].credential_sync_outbox.find_one({"event_id": event["event_id"]})
    assert link_id
    assert stored["status"] == "pending"
    assert stored["credential_version"] == 3
    assert stored["profile_version"] == 2
    assert stored["payload_metadata"] == {"role": "staff"}
    assert "must-not-persist" not in str(stored)
    assert app.extensions["mongo_db"].credential_sync_outbox.count_documents({"event_id": event["event_id"]}) == 1


def test_identity_link_is_idempotent(app):
    with app.app_context():
        user = local_user(app)
        first = ensure_identity_link(user["_id"], email=user["email"], username=user["username"])
        second = ensure_identity_link(user["_id"], email=user["email"], username="renamed")
    assert first == second
    assert app.extensions["mongo_db"].user_identity_links.count_documents({"rk_stock_user_id": user["_id"]}) == 1
    assert app.extensions["mongo_db"].user_identity_links.find_one({"_id": first})["username"] == "renamed"


def test_local_user_mutations_queue_events(client, app, headers):
    created = client.post("/api/users", headers=headers, json={"firstName": "Queue", "username": "queue-user", "email": "queue@rk.test", "role": "staff", "password": "temporary-password", "isActive": True})
    assert created.status_code == 201
    user_id = created.json["user"]["id"]
    events = list(app.extensions["mongo_db"].credential_sync_outbox.find({"source_user_id": user_id}))
    assert {event["event_type"] for event in events} == {"USER_CREATED"}
    assert all("temporary-password" not in str(event) and "password_hash" not in str(event) for event in events)


def signed_handoff(payload, secret="handoff-test-secret"):
    claims = dict(payload)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    claims.update({"iss": "rk-web", "aud": "rk-stock", "iat": now_ts, "exp": now_ts + 60, "jti": "jti-" + payload["event_id"]})
    return jwt.encode(claims, secret, algorithm="HS256")


def test_web_credential_receiver_applies_and_replays_idempotently(client, app):
    database = app.extensions["mongo_db"]
    app.config.update(RK_WEB_CREDENTIAL_SYNC_SECRET="service-test-secret", RK_WEB_CREDENTIAL_SYNC_SCOPES={"credential:sync"}, CREDENTIAL_SYNC_HANDOFF_SECRET="handoff-test-secret")
    user = local_user(app)
    payload = {"event_id": "event-1", "event_type": "PASSWORD_CHANGED", "source_system": "rk-web", "target_system": "rk-stock", "source_user_id": "web-1", "target_user_id": str(user["_id"]), "credential_version": 4, "profile_version": 2, "payload_metadata": {"email": user["email"], "username": user["username"], "role": "staff", "is_active": True}, "password": "new-local-password", "credential_handoff": ""}
    payload["credential_handoff"] = signed_handoff(payload)
    headers = {"Authorization": "Bearer service-test-secret"}
    first = client.post("/api/integrations/internal/auth/provision-credential", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json["status"] == "APPLIED"
    assert database.users.find_one({"_id": user["_id"]})["credential_version"] == 4
    assert "new-local-password" not in str(database.credential_sync_consumptions.find_one({"event_id": "event-1"}))
    second = client.post("/api/integrations/internal/auth/provision-credential", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json["status"] == "ALREADY_APPLIED"


def test_current_web_credential_endpoint_provisions_local_login(client, app):
    database = app.extensions["mongo_db"]
    app.config.update(RK_WEB_CREDENTIAL_SYNC_SECRET="service-test-secret", RK_WEB_CREDENTIAL_SYNC_SCOPES={"credential:sync"}, CREDENTIAL_SYNC_HANDOFF_SECRET="handoff-test-secret")
    user = local_user(app)
    payload = {"event_id": "event-current-web-path", "event_type": "PASSWORD_CHANGED", "source_system": "rk-web", "target_system": "rk-stock", "source_user_id": "web-current-path", "target_user_id": str(user["_id"]), "credential_version": 4, "profile_version": 2, "payload_metadata": {"email": user["email"], "username": user["username"], "role": "staff", "is_active": True}, "password": "synced-local-password", "credential_handoff": ""}
    payload["credential_handoff"] = signed_handoff(payload)
    response = client.post("/api/internal/auth/provision-credential", headers={"Authorization": "Bearer service-test-secret"}, json=payload)
    assert response.status_code == 200
    assert response.json["status"] == "APPLIED"
    stored = database.users.find_one({"_id": user["_id"]})
    assert stored.get("password_hash")
    assert "synced-local-password" not in str(database.credential_sync_consumptions.find_one({"event_id": payload["event_id"]}))
    client.delete_cookie("rk_stock_session")
    assert client.post("/api/auth/login", json={"identifier": user["username"], "password": "synced-local-password"}).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"identifier": user["username"], "password": "wrong-password"}).status_code == 401


def test_web_credential_receiver_rejects_bad_signature_and_scope(client, app):
    app.config.update(RK_WEB_CREDENTIAL_SYNC_SECRET="service-test-secret", RK_WEB_CREDENTIAL_SYNC_SCOPES={"catalog:write"}, CREDENTIAL_SYNC_HANDOFF_SECRET="handoff-test-secret")
    assert client.post("/api/integrations/internal/auth/provision-credential", headers={"Authorization": "Bearer service-test-secret"}, json={}).status_code == 403
