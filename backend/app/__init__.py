import os
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from .config import Config
from .extensions import db, jwt, migrate
from .utils import ApiError

def create_app(overrides=None):
    frontend = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
    app = Flask(__name__, static_folder=frontend, static_url_path="/static-app")
    app.config.from_object(Config)
    app.config.update(overrides or {})
    if not (app.config.get("SECRET_KEY") and app.config.get("JWT_SECRET_KEY")):
        raise RuntimeError("SECRET_KEY and JWT_SECRET_KEY must be set in backend/.env")
    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)
    from . import models  # noqa: F401  (registers tables for migrations)
    from .routes import api
    app.register_blueprint(api)

    def fail(msg, code):
        return jsonify(success=False, message=msg), code

    @jwt.unauthorized_loader
    @jwt.invalid_token_loader
    def _unauth(_):
        return fail("Please log in to continue", 401)

    @jwt.expired_token_loader
    def _expired(_h, _p):
        return fail("Your session has expired. Please log in again", 401)

    @app.errorhandler(ApiError)
    def _api(e):
        db.session.rollback()
        return fail(e.message, e.status)

    @app.errorhandler(HTTPException)
    def _http(e):
        return fail(e.description if request.path.startswith("/api") else e.name, e.code)

    @app.errorhandler(Exception)
    def _500(e):
        db.session.rollback()
        app.logger.exception("Unhandled error")
        return fail("Something went wrong. Please try again.", 500)

    @app.get("/")
    def index():
        return send_from_directory(frontend, "index.html")

    return app
