"""
LifeLink 2.0 - Core Backend Flask Application
Serves API endpoints, orchestrates peripheral device services,
and serves the touchscreen kiosk frontend.
"""

import os
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request
from backend.config import Config
from backend.database.connection import init_db
from backend.auth.routes import auth_bp
from backend.patients.routes import patients_bp
from backend.admin.routes import admin_bp
from backend.devices.routes import devices_bp
from backend.biometrics.routes import biometrics_bp

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app() -> Flask:
    """Application factory for LifeLink 2.0."""
    app = Flask(
        __name__,
        static_folder=str(FRONTEND_DIR),
        static_url_path="/static"
    )
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    app.config["JSON_SORT_KEYS"] = False

    # Initialize local persistence tables and indices
    init_db()

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(biometrics_bp)

    # Root route serves the Kiosk Single-Page Application
    @app.route("/")
    def index():
        return send_from_directory(str(FRONTEND_DIR), "index.html")

    # Serve static frontend assets (css, js, icons)
    @app.route("/<path:filename>")
    def serve_frontend_assets(filename):
        target = FRONTEND_DIR / filename
        if target.exists() and not target.is_dir():
            return send_from_directory(str(FRONTEND_DIR), filename)
        # Fallback to index.html for SPA client-side routes
        return send_from_directory(str(FRONTEND_DIR), "index.html")

    # Consolidated Health Check API
    @app.route("/api/v1/health", methods=["GET"])
    def system_health():
        return jsonify({
            "status": "healthy",
            "version": "2.0.0",
            "platform": "Raspberry Pi 5 Kiosk Terminal (Fully Wired)",
            "mock_mode": Config.MOCK_MODE,
            "database_type": Config.DB_TYPE
        }), 200

    # Global Error Handlers
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"status": "error", "message": "Bad request", "details": str(e)}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"status": "error", "message": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    print(f"\n=======================================================")
    print(f" LifeLink 2.0 Starting on http://{Config.HOST}:{Config.PORT}")
    print(f" Operational Mode: {'MOCK_MODE' if Config.MOCK_MODE else 'HARDWARE_MODE'}")
    print(f" Database: {Config.DB_TYPE.upper()} ({Config.DB_NAME})")
    print(f"=======================================================\n")
    app.run(host=Config.HOST, port=Config.PORT, debug=False)
