from pathlib import Path
from flask import Flask, jsonify
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

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="Not found"), 404

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="File too large"), 413

    return app

