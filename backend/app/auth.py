from datetime import timedelta, timezone
from functools import wraps
import hashlib
import secrets
import requests
import bcrypt
import jwt
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from flask import current_app, g, jsonify, request

from .db import db
from .services import activity
from .utils import now, oid


ROLE_PERMISSIONS = {
    "admin": {"*"},
    "staff": {"clients:write", "linesheets:write", "orders:write", "documents:write", "reports:read", "settings:write", "stock:write"},
    "sales": {"clients:write", "linesheets:write", "orders:write", "documents:write", "reports:read"},
    "production_inventory": {"production:write", "stock:write", "orders:read"},
}


def effective_permissions(user):
    role_permissions = ROLE_PERMISSIONS.get(user.get("role"), set())
    if "*" in role_permissions:
        return {"*"}
    return set(role_permissions) | {
        permission for permission in (user.get("permissions") or []) if isinstance(permission, str)
    }


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password, hashed):
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (AttributeError, TypeError, ValueError):
        return False


def _session_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_local_session(user_id, *, sso_bootstrap=False):
    token = secrets.token_urlsafe(48)
    created_at = now()
    expires_at = created_at + timedelta(days=current_app.config.get("LOCAL_SESSION_DAYS", 30))
    db().auth_sessions.insert_one({
        "user_id": user_id,
        "token_hash": _session_hash(token),
        "source": "local",
        "created_at": created_at,
        "last_seen_at": created_at,
        "expires_at": expires_at,
        "revoked_at": None,
        "sso_bootstrap": bool(sso_bootstrap),
    })
    return token


def revoke_local_sessions(user_id, except_token=None):
    query = {"user_id": user_id, "source": "local", "revoked_at": None}
    if except_token:
        query["token_hash"] = {"$ne": _session_hash(except_token)}
    db().auth_sessions.update_many(query, {"$set": {"revoked_at": now()}})


def _local_user_from_cookie():
    token = request.cookies.get(current_app.config.get("LOCAL_SESSION_COOKIE_NAME", "rk_stock_session"), "")
    if not token:
        return None
    session = db().auth_sessions.find_one({"token_hash": _session_hash(token), "source": "local", "revoked_at": None})
    if not session:
        return None
    expires_at = session.get("expires_at")
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not expires_at or expires_at <= now():
        return None
    user = db().users.find_one({"_id": session.get("user_id"), "active": True})
    if not user or user.get("role") not in {"admin", "staff", "sales", "production_inventory"}:
        return None
    refreshed_at = now()
    db().auth_sessions.update_one({"_id": session["_id"], "revoked_at": None}, {"$set": {
        "last_seen_at": refreshed_at,
        "expires_at": refreshed_at + timedelta(days=current_app.config.get("LOCAL_SESSION_DAYS", 30)),
    }})
    g.local_session_token = token
    g.local_session_refresh = token
    g.local_session_sso_bootstrap = bool(session.get("sso_bootstrap"))
    return user


def _provision_shared_identity(payload, web_user_id):
    """Reconcile an operational RK-WEB identity into the local users list.

    SSO does not provide a password. The local record therefore remains
    forced-change/unusable until the signed credential handoff provisions a
    local bcrypt hash.
    """
    role = payload.get("role")
    if role not in {"admin", "staff"} or payload.get("isActive") is False:
        return None
    links = db().user_identity_links
    link = links.find_one({"$or": [{"rk_web_user_id": str(web_user_id)}, {"rk_web_user_id": web_user_id}]})
    user = db().users.find_one({"_id": link.get("rk_stock_user_id")}) if link and link.get("rk_stock_user_id") else None
    timestamp = now()
    email = str(payload.get("email") or "").strip().lower() or None
    username = str(payload.get("username") or "").strip() or None
    name = str(payload.get("displayName") or username or email or "RK-WEB user").strip()
    if not user:
        # Do not merge an unrelated Stock account merely because email matches.
        if email and db().users.find_one({"email": email}):
            return None
        if username and db().users.find_one({"username": username}):
            return None
        user_id = ObjectId()
        user = {"_id": user_id, "name": name, "password_hash": "", "role": role, "active": True, "must_change_password": True, "credential_version": 0, "profile_version": 0, "source": "rk-web-sso", "created_at": timestamp, "updated_at": timestamp}
        if username: user["username"] = username
        if email: user["email"] = email
        db().users.insert_one(user)
        activity(user, "user_provisioned", "user", user_id, {"authentication_method": "shared_sso", "source_system": "rk-web"})
    else:
        if user.get("role") == "admin" and role != "admin" and user.get("active", True) and db().users.count_documents({"role": "admin", "active": True}) <= 1:
            role = "admin"
        update = {"name": name, "role": role, "active": True, "updated_at": timestamp}
        if email: update["email"] = email
        if username: update["username"] = username
        db().users.update_one({"_id": user["_id"]}, {"$set": update})
        user.update(update)
    values = {"rk_stock_user_id": user["_id"], "rk_web_user_id": str(web_user_id), "email": email, "username": username, "status": "active", "updated_at": timestamp}
    if link:
        links.update_one({"_id": link["_id"]}, {"$set": values})
    else:
        values["created_at"] = timestamp
        links.insert_one(values)
    return db().users.find_one({"_id": user["_id"]})


def _shared_user_from_cookie():
    cookie = request.cookies.get(current_app.config.get("SHARED_SESSION_COOKIE_NAME", "rk_shared_session"), "")
    target = current_app.config.get("SHARED_AUTH_URL", "").rstrip("/")
    secret = current_app.config.get("SHARED_SESSION_INTERNAL_SECRET", "")
    # TEMPORARY LOCAL DIAGNOSTIC: status metadata only; never store values.
    diagnostic = {
        "shared_cookie_present": bool(cookie),
        "shared_session_validation_attempted": False,
        "shared_session_validation_status": None,
        "shared_session_user_found": False,
        "shared_session_user_active": False,
        "shared_session_user_role": None,
        "failure_reason": "",
    }
    g.shared_auth_diagnostic = diagnostic
    if not cookie or not target or not secret:
        diagnostic["failure_reason"] = (
            "missing_shared_cookie" if not cookie else
            "shared_auth_url_not_configured" if not target else
            "shared_auth_secret_not_configured"
        )
        return None
    try:
        diagnostic["shared_session_validation_attempted"] = True
        response = requests.get(f"{target}/api/auth/shared/me", headers={"X-RK-Shared-Auth": secret}, cookies={current_app.config.get("SHARED_SESSION_COOKIE_NAME", "rk_shared_session"): cookie}, timeout=3)
        diagnostic["shared_session_validation_status"] = response.status_code
        if not response.ok:
            diagnostic["failure_reason"] = "shared_auth_rejected"
            return None
        payload = response.json().get("user") or {}
        diagnostic["shared_session_user_found"] = bool(payload)
        diagnostic["shared_session_user_active"] = bool(payload and payload.get("isActive") is not False)
        role = payload.get("role")
        diagnostic["shared_session_user_role"] = role if role in {"admin", "staff", "customer"} else None
        user_id = oid(payload.get("id"))
        if not user_id:
            diagnostic["failure_reason"] = "shared_user_id_invalid"
            return None
        if role not in {"admin", "staff"}:
            diagnostic["failure_reason"] = "shared_user_role_rejected"
            return None
        if payload.get("isActive") is False:
            diagnostic["failure_reason"] = "shared_user_inactive"
            return None
        remote_user_id = user_id
        provisioned = _provision_shared_identity(payload, user_id)
        if provisioned:
            user_id = provisioned["_id"]
        remote_permissions = set(payload.get("permissions") or [])
        translated = set()
        if "products:manage" in remote_permissions: translated.add("settings:write")
        if "inventory:manage" in remote_permissions: translated.add("stock:write")
        if "orders:manage" in remote_permissions: translated.add("orders:write")
        if "customers:manage" in remote_permissions: translated.add("clients:write")
        g.shared_session_refresh = cookie
        diagnostic["failure_reason"] = ""
        return {"_id": user_id, "rk_web_user_id": str(remote_user_id), "name": (provisioned or {}).get("name") or payload.get("displayName") or payload.get("username") or payload.get("email"), "email": (provisioned or {}).get("email") or payload.get("email"), "role": (provisioned or {}).get("role") or payload.get("role"), "permissions": sorted(translated), "active": True, "shared": True, "must_change_password": bool((provisioned or {}).get("must_change_password", payload.get("must_change_password")))}
    except (requests.RequestException, ValueError, TypeError):
        diagnostic["failure_reason"] = "shared_auth_unavailable_or_invalid"
        return None


def token_for(user):
    issued = now()
    return jwt.encode({"sub": str(user["_id"]), "role": user["role"], "iat": issued, "exp": issued + timedelta(seconds=current_app.config["JWT_TTL_SECONDS"])}, current_app.config["JWT_SECRET"], algorithm="HS256")


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        local_user = _local_user_from_cookie()
        if local_user:
            g.user = local_user
            g.auth_source = "local"
            if local_user.get("must_change_password") and not getattr(g, "local_session_sso_bootstrap", False) and request.path not in {"/api/auth/me", "/api/auth/logout", "/api/auth/password/change"}:
                return jsonify(error="Password change required before continuing", must_change_password=True), 403
            return fn(*args, **kwargs)
        shared_cookie = request.cookies.get(current_app.config.get("SHARED_SESSION_COOKIE_NAME", "rk_shared_session"), "")
        shared_user = _shared_user_from_cookie() if shared_cookie else None
        if shared_user:
            remote_id = shared_user.get("rk_web_user_id", str(shared_user["_id"]))
            mapped = db().user_identity_links.find_one({"$or": [{"rk_web_user_id": str(remote_id)}, {"rk_web_user_id": remote_id}]})
            local_user = db().users.find_one({"_id": mapped.get("rk_stock_user_id"), "active": True}) if mapped and mapped.get("rk_stock_user_id") else None
            g.user = local_user or shared_user
            if local_user:
                g.local_session_refresh = create_local_session(local_user["_id"], sso_bootstrap=True)
                bootstrap = {"shared_session_hash": _session_hash(shared_cookie), "user_id": local_user["_id"], "created_at": now()}
                try:
                    db().sso_bootstrap_events.insert_one(bootstrap)
                except DuplicateKeyError:
                    pass
                else:
                    login_time = now()
                    db().users.update_one({"_id": local_user["_id"]}, {"$set": {"last_login_at": login_time, "updated_at": login_time}})
                    local_user["last_login_at"] = login_time
                    activity(local_user, "sso_login", "auth", local_user["_id"], {"authentication_method": "shared_sso", "source_system": "rk-web"})
            g.auth_source = "sso"
            return fn(*args, **kwargs)
        value = request.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            payload = {"error": "Authentication required"}
            if current_app.config.get("MONGO_DB") == "RK_TEST_DB":
                diagnostic = dict(getattr(g, "shared_auth_diagnostic", {}) or {})
                diagnostic["jwt_present"] = bool(value)
                diagnostic["failure_reason"] = diagnostic.get("failure_reason") or "jwt_missing"
                payload["debug"] = diagnostic
            return jsonify(payload), 401
        try:
            payload = jwt.decode(value[7:], current_app.config["JWT_SECRET"], algorithms=["HS256"])
            user = db().users.find_one({"_id": oid(payload["sub"]), "active": True})
        except jwt.PyJWTError:
            user = None
        if not user:
            response = {"error": "Invalid or expired token"}
            if current_app.config.get("MONGO_DB") == "RK_TEST_DB":
                diagnostic = dict(getattr(g, "shared_auth_diagnostic", {}) or {})
                diagnostic["jwt_present"] = True
                diagnostic["failure_reason"] = "jwt_invalid_or_user_not_found"
                response["debug"] = diagnostic
            return jsonify(response), 401
        g.user = user
        g.auth_source = "legacy_jwt"
        return fn(*args, **kwargs)
    return wrapper


def permission_required(permission):
    def decorator(fn):
        @auth_required
        @wraps(fn)
        def wrapper(*args, **kwargs):
            permissions = effective_permissions(g.user)
            if "*" not in permissions and permission not in permissions:
                return jsonify(error="Permission denied"), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
