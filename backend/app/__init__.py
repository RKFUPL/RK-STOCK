from pathlib import Path
from flask import Flask, g, jsonify
from flask_cors import CORS

from .config import Config
from .db import init_db
from .routes import api


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    CORS(app, origins=[app.config["FRONTEND_ORIGIN"]], supports_credentials=True)
    init_db(app)
    app.register_blueprint(api, url_prefix="/api")

    @app.after_request
    def refresh_auth_session_cookies(response):
        local_token = getattr(g, "local_session_refresh", None)
        if local_token:
            response.set_cookie(
                app.config["LOCAL_SESSION_COOKIE_NAME"], local_token,
                max_age=app.config.get("LOCAL_SESSION_DAYS", 30) * 86400,
                domain=app.config.get("LOCAL_SESSION_COOKIE_DOMAIN") or None,
                path="/", secure=app.config.get("LOCAL_SESSION_COOKIE_SECURE", False),
                httponly=True, samesite="Lax",
            )
        token = getattr(g, "shared_session_refresh", None)
        if token:
            response.set_cookie(
                app.config["SHARED_SESSION_COOKIE_NAME"], token,
                max_age=app.config.get("SHARED_SESSION_DAYS", 30) * 86400,
                domain=app.config.get("SHARED_SESSION_COOKIE_DOMAIN") or None,
                path="/", secure=app.config.get("SHARED_SESSION_COOKIE_SECURE", False),
                httponly=True, samesite="Lax",
            )
        return response

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="Not found"), 404

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="File too large"), 413

    return app
