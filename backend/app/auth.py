from datetime import timedelta
from functools import wraps
import requests
import bcrypt
import jwt
from flask import current_app, g, jsonify, request

from .db import db
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
    return bcrypt.checkpw(password.encode(), hashed.encode())


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
        remote_permissions = set(payload.get("permissions") or [])
        translated = set()
        if "products:manage" in remote_permissions: translated.add("settings:write")
        if "inventory:manage" in remote_permissions: translated.add("stock:write")
        if "orders:manage" in remote_permissions: translated.add("orders:write")
        if "customers:manage" in remote_permissions: translated.add("clients:write")
        g.shared_session_refresh = cookie
        diagnostic["failure_reason"] = ""
        return {"_id": user_id, "name": payload.get("displayName") or payload.get("username") or payload.get("email"), "email": payload.get("email"), "role": payload.get("role"), "permissions": sorted(translated), "active": True, "shared": True}
    except (requests.RequestException, ValueError, TypeError):
        diagnostic["failure_reason"] = "shared_auth_unavailable_or_invalid"
        return None


def token_for(user):
    issued = now()
    return jwt.encode({"sub": str(user["_id"]), "role": user["role"], "iat": issued, "exp": issued + timedelta(seconds=current_app.config["JWT_TTL_SECONDS"])}, current_app.config["JWT_SECRET"], algorithm="HS256")


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        shared_user = _shared_user_from_cookie()
        if shared_user:
            g.user = shared_user
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
