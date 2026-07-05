import logging
from flask import Flask, jsonify
from app import create_app

# Create the Flask app with error handling so serverless platforms
# (like Vercel) receive a valid WSGI app even if initialization fails.
try:
    app = create_app()
except Exception as e:
    logging.exception("Failed to create Flask app")
    # Fallback app that returns the initialization error for debugging
    app = Flask(__name__)

    @app.route("/")
    def startup_error():
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "App failed to start. Check server logs for details.",
                    "error": str(e),
                }
            ),
            500,
        )

if __name__ == "__main__":
    logging.info("Flask app started")
    app.run(host="0.0.0.0", port=8000)