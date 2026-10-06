"""Safe local foundation for cross-application user synchronization.

This module deliberately stores metadata only. Passwords, password hashes,
session tokens, and service credentials never enter the outbox.
"""
from uuid import uuid4
from datetime import datetime, timezone
import hmac
import jwt
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from flask import current_app, request

from .db import db
from .auth import hash_password, revoke_local_sessions
from .utils import oid
from .utils import now


def ensure_identity_link(stock_user_id, *, web_user_id=None, email=None, username=None, status="pending"):
    query = {"rk_stock_user_id": stock_user_id}
    if web_user_id:
        query = {"$or": [{"rk_stock_user_id": stock_user_id}, {"rk_web_user_id": web_user_id}]}
    link = db().user_identity_links.find_one(query)
    timestamp = now()
    values = {"rk_stock_user_id": stock_user_id, "email": email, "username": username, "status": status, "updated_at": timestamp}
    if web_user_id:
        values["rk_web_user_id"] = web_user_id
    if link:
        db().user_identity_links.update_one({"_id": link["_id"]}, {"$set": values})
        return link["_id"]
    values["created_at"] = timestamp
    return db().user_identity_links.insert_one(values).inserted_id


def queue_credential_event(user, event_type, *, metadata=None, target_system="rk-web"):
    version_field = "credential_version" if event_type in {"PASSWORD_CHANGED", "PASSWORD_RESET", "USER_CREATED"} else "profile_version"
    version = int(user.get(version_field, 0))
    event_id = str(uuid4())
    timestamp = now()
    document = {
        "event_id": event_id,
        "event_type": event_type,
        "source_system": "rk-stock",
        "target_system": target_system,
        "source_user_id": str(user["_id"]),
        "target_user_id": user.get("rk_web_user_id"),
        "credential_version": int(user.get("credential_version", 0)),
        "profile_version": int(user.get("profile_version", 0)),
        "payload_metadata": metadata or {},
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": timestamp,
        "last_error": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
    }
    # Allow-list metadata so future callers cannot accidentally persist a
    # password, hash, token, secret, or arbitrary credential field.
    safe_metadata = {"email", "username", "role", "active", "must_change_password"}
    document["payload_metadata"] = {key: value for key, value in document["payload_metadata"].items() if key in safe_metadata}
    db().credential_sync_outbox.insert_one(document)
    db().activity_log.insert_one({"user_id": user.get("_id"), "user_email": user.get("email"), "action": "credential_sync_queued", "entity_type": "user", "entity_id": str(user["_id"]), "details": {"event_id": event_id, "event_type": event_type, "target_system": target_system, "credential_version": version}, "created_at": timestamp})
    return document


EVENT_TYPES = {"USER_CREATED", "PASSWORD_CHANGED", "PASSWORD_RESET", "USERNAME_CHANGED", "EMAIL_CHANGED", "ROLE_CHANGED", "STATUS_CHANGED"}
PASSWORD_EVENTS = {"USER_CREATED", "PASSWORD_CHANGED", "PASSWORD_RESET"}


def service_scope_authorized():
    supplied = request.headers.get("Authorization", "") if request else ""
    token = supplied[7:] if supplied.startswith("Bearer ") else ""
    configured = str(current_app.config.get("RK_WEB_CREDENTIAL_SYNC_SECRET") or "")
    scopes = current_app.config.get("RK_WEB_CREDENTIAL_SYNC_SCOPES") or set()
    return bool(configured and token and hmac.compare_digest(token, configured) and "credential:sync" in scopes)


def service_scope_status():
    supplied = request.headers.get("Authorization", "") if request else ""
    token = supplied[7:] if supplied.startswith("Bearer ") else ""
    configured = str(current_app.config.get("RK_WEB_CREDENTIAL_SYNC_SECRET") or "")
    if not configured or not token or not hmac.compare_digest(token, configured):
        return 401
    return 200 if "credential:sync" in (current_app.config.get("RK_WEB_CREDENTIAL_SYNC_SCOPES") or set()) else 403


def _as_int(value):
    if isinstance(value, bool):
        raise ValueError
    return int(value)


def verify_handoff(token, body):
    secret = str(current_app.config.get("CREDENTIAL_SYNC_HANDOFF_SECRET") or "")
    if not secret or not isinstance(token, str) or not token:
        raise ValueError("credential handoff is unavailable")
    claims = jwt.decode(token, secret, algorithms=["HS256"], issuer="rk-web", audience="rk-stock", leeway=5, options={"require": ["iss", "aud", "event_id", "event_type", "source_user_id", "target_user_id", "credential_version", "profile_version", "iat", "exp", "jti"]})
    for key in ("event_id", "event_type", "source_user_id", "target_user_id"):
        if str(claims.get(key)) != str(body.get(key)):
            raise ValueError("credential handoff does not match the request")
    for key in ("credential_version", "profile_version"):
        if _as_int(claims.get(key)) != _as_int(body.get(key)):
            raise ValueError("credential handoff does not match the request")
    if claims.get("iss") != "rk-web" or claims.get("aud") != "rk-stock":
        raise ValueError("credential handoff issuer or audience is invalid")
    return claims


def _safe_event_body(body):
    required = ("event_id", "event_type", "source_system", "target_system", "source_user_id", "target_user_id", "credential_version", "profile_version")
    if any(not body.get(key) for key in required):
        raise ValueError("required synchronization fields are missing")
    if body["source_system"] != "rk-web" or body["target_system"] != "rk-stock" or body["event_type"] not in EVENT_TYPES:
        raise ValueError("invalid synchronization event")
    metadata = body.get("payload_metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("payload_metadata must be an object")
    return metadata


def apply_user_event(body):
    metadata = _safe_event_body(body)
    source_id = str(body["source_user_id"])
    target_id = oid(body.get("target_user_id"))
    event_id = str(body["event_id"])
    version = _as_int(body["credential_version"])
    profile_version = _as_int(body["profile_version"])
    links = db().user_identity_links
    link = links.find_one({"rk_web_user_id": source_id})
    if link and target_id and link.get("rk_stock_user_id") != target_id:
        raise ConflictError("identity mapping conflict")
    if link and not target_id:
        target_id = link.get("rk_stock_user_id")
    if body["event_type"] == "USER_CREATED" and not target_id:
        email = str(metadata.get("email") or "").strip().lower()
        username = str(metadata.get("username") or "").strip()
        if not email or not username:
            raise ValueError("user metadata is incomplete")
        if db().users.find_one({"$or": [{"email": email}, {"username": username}]}):
            raise ConflictError("existing user conflicts with remote identity")
        target_id = ObjectId()
        db().users.insert_one({"_id": target_id, "name": username, "username": username, "email": email, "password_hash": "", "role": metadata.get("role", "staff"), "active": metadata.get("is_active", True) is not False, "must_change_password": True, "credential_version": version, "profile_version": profile_version, "source": "rk-web", "created_at": now(), "updated_at": now()})
    if not target_id:
        raise ValueError("identity mapping is required")
    user = db().users.find_one({"_id": target_id})
    if not user:
        raise ValueError("target user not found")
    current_version = int(user.get("credential_version", 0))
    if version < current_version:
        return {"status": "STALE", "applied": False, "credential_version": current_version, "target_id": target_id}
    if version == current_version and body["event_type"] != "USER_CREATED":
        raise ConflictError("credential version conflicts with an unprocessed event")
    role = metadata.get("role")
    if role is not None:
        if role not in {"admin", "staff", "customer"}:
            raise ValueError("invalid role")
        if role == "customer" and user.get("role") == "admin" and user.get("active", True) and db().users.count_documents({"role": "admin", "active": True}) <= 1:
            raise ConflictError("the last active admin cannot be downgraded")
    updates = {"credential_version": version, "profile_version": profile_version, "updated_at": now()}
    if "email" in metadata: updates["email"] = str(metadata["email"]).strip().lower()
    if "username" in metadata: updates["username"] = str(metadata["username"]).strip()
    if role is not None: updates["role"] = role
    if "is_active" in metadata: updates["active"] = metadata["is_active"] is not False
    db().users.update_one({"_id": target_id}, {"$set": updates})
    if updates.get("active") is False: revoke_local_sessions(target_id)
    ensure_identity_link(target_id, web_user_id=source_id, email=updates.get("email", user.get("email")), username=updates.get("username", user.get("username")), status="active" if updates.get("active", user.get("active", True)) else "inactive")
    return {"status": "APPLIED", "applied": True, "credential_version": version, "target_id": target_id}


def apply_credential_event(body, password, claims):
    metadata = _safe_event_body(body)
    if body["event_type"] not in PASSWORD_EVENTS:
        raise ValueError("event type does not carry a credential")
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password does not satisfy local policy")
    event_id, jti = str(body["event_id"]), str(claims["jti"])
    existing = db().credential_sync_consumptions.find_one({"event_id": event_id})
    if existing:
        return {"status": "ALREADY_APPLIED", "applied": False, "credential_version": existing.get("credential_version", 0), "target_id": oid(body.get("target_user_id"))}
    if db().credential_sync_consumptions.find_one({"jti": jti}):
        raise ValueError("credential handoff has already been consumed")
    target_id = oid(body.get("target_user_id"))
    link = db().user_identity_links.find_one({"rk_web_user_id": str(body["source_user_id"])})
    if link and target_id and link.get("rk_stock_user_id") != target_id:
        raise ConflictError("identity mapping conflict")
    user = db().users.find_one({"_id": target_id}) if target_id else None
    if not user:
        if body["event_type"] != "USER_CREATED":
            raise ValueError("target user not found")
        metadata = _safe_event_body(body)
        role = metadata.get("role", "staff")
        if role not in {"admin", "staff"}:
            raise ValueError("customer cannot receive Stock access")
        email = str(metadata.get("email") or "").strip().lower()
        username = str(metadata.get("username") or "").strip()
        if not email or not username or db().users.find_one({"$or": [{"email": email}, {"username": username}]}):
            raise ConflictError("user identity conflicts")
        target_id = ObjectId()
        db().users.insert_one({"_id": target_id, "name": username, "username": username, "email": email, "password_hash": hash_password(password), "role": role, "active": metadata.get("is_active", True) is not False, "must_change_password": True, "credential_version": int(body["credential_version"]), "profile_version": int(body["profile_version"]), "source": "rk-web", "created_at": now(), "updated_at": now()})
    else:
        current_version = int(user.get("credential_version", 0))
        incoming = int(body["credential_version"])
        if incoming < current_version:
            return {"status": "STALE", "applied": False, "credential_version": current_version, "target_id": target_id}
        if incoming == current_version:
            raise ConflictError("credential version conflicts with an unprocessed event")
        db().users.update_one({"_id": target_id}, {"$set": {"password_hash": hash_password(password), "credential_version": incoming, "profile_version": int(body["profile_version"]), "must_change_password": body["event_type"] == "USER_CREATED", "updated_at": now()}})
        revoke_local_sessions(target_id)
    try:
        db().credential_sync_consumptions.insert_one({"event_id": event_id, "jti": jti, "source_system": "rk-web", "target_system": "rk-stock", "source_user_id": str(body["source_user_id"]), "target_user_id": target_id, "credential_version": int(body["credential_version"]), "consumed_at": now()})
    except DuplicateKeyError:
        existing = db().credential_sync_consumptions.find_one({"event_id": event_id})
        return {"status": "ALREADY_APPLIED", "applied": False, "credential_version": existing.get("credential_version", 0), "target_id": target_id}
    ensure_identity_link(target_id, web_user_id=str(body["source_user_id"]), email=metadata.get("email"), username=metadata.get("username"), status="active")
    return {"status": "APPLIED", "applied": True, "credential_version": int(body["credential_version"]), "target_id": target_id}


class ConflictError(ValueError):
    pass
