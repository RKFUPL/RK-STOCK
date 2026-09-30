from datetime import timedelta
from functools import wraps
import bcrypt
import jwt
from flask import current_app, g, jsonify, request

from .db import db
from .utils import now, oid


ROLE_PERMISSIONS = {
    "admin": {"*"},
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


def token_for(user):
    issued = now()
    return jwt.encode({"sub": str(user["_id"]), "role": user["role"], "iat": issued, "exp": issued + timedelta(seconds=current_app.config["JWT_TTL_SECONDS"])}, current_app.config["JWT_SECRET"], algorithm="HS256")


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        value = request.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            return jsonify(error="Authentication required"), 401
        try:
            payload = jwt.decode(value[7:], current_app.config["JWT_SECRET"], algorithms=["HS256"])
            user = db().users.find_one({"_id": oid(payload["sub"]), "active": True})
        except jwt.PyJWTError:
            user = None
        if not user:
            return jsonify(error="Invalid or expired token"), 401
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
