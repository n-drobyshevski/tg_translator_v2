import os
import sys
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, flash, Blueprint, jsonify, current_app
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from admin_dashboard import admin_bp
from admin_prompt import admin_prompt_bp
from admin_config import admin_config_bp  
from admin_manager import admin_manager_bp
from admin_logs import admin_logs_bp
from aggregator import (
    build_summary,
    build_10d_channels,
    build_hourly_matrix,
    build_throughput_latency,
    load_messages
)
from app.admin_events import admin_stats_bp
from translator.config import PROMPT_TEMPLATE_PATH
# make sure project root is on sys.path so 'translator' can be found
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


app = Flask(__name__)
app.config["DEBUG"] = True
app.secret_key = os.getenv("SECRET_KEY") or "dev_secret_key"  # ensure non-empty default

# --- Setup Flask-Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"  # type: ignore

# --- Static Admin User ---
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")


class Admin(UserMixin):
    """Admin user class for Flask-Login authentication."""

    def __init__(self):
        self.id = "admin"

    def get_id(self):
        return self.id


@login_manager.user_loader
def load_user(user_id):
    if user_id == "admin":
        return Admin()
    return None


# --- Login Route ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == ADMIN_PASSWORD:
            user = Admin()
            login_user(user)
            flash("Logged in, let’s go 🚀", "success")
            return redirect(
                request.args.get("next") or url_for("admin_bp.admin_dashboard")
            )
        else:
            flash("Wrong password, try again!", "error")
    return render_template("login.html")

# --- Logout Route ---
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out 👋", "info")
    return redirect(url_for("login"))


bp = Blueprint("metrics", __name__, url_prefix="/api")


@bp.route("/metrics/summary")
def metrics_summary():
    """Return post counts and KPIs with a flexible time window."""
    try:
        messages = load_messages()
        # Get the days parameter, default to 10 if not provided
        days = int(request.args.get("days", 10))
        include_test = request.args.get("include_test_channels", "1") not in ("0", "false", "False")
        # Filter out test channels if needed
        if not include_test:
            test_ids = set()
            for envvar in ("TEST_CHANNEL", "TEST_EN_CHANNEL_ID"):
                val = os.getenv(envvar)
                if val:
                    test_ids.add(str(val))
            def not_test(m):
                return (
                    str(m.get("source_channel_id")) not in test_ids and
                    str(m.get("dest_channel_id")) not in test_ids and
                    str(m.get("source_channel_name", "")).lower() != "test" and
                    str(m.get("dest_channel_name", "")).lower() != "test"
                )
            messages = [m for m in messages if not_test(m)]
        payload = {
            "posts_10d": build_summary(messages, days),
            "posts_10d_channels": build_10d_channels(messages, days),
            "posts_matrix": build_hourly_matrix(messages),
            "throughput_latency": build_throughput_latency(messages),  # <--- ADD THIS
        }
    except Exception as exc:
        current_app.logger.exception("summary route failed")
        return jsonify(error=str(exc)), 500
    return jsonify(payload)


app.register_blueprint(admin_bp)
app.register_blueprint(admin_prompt_bp)
app.register_blueprint(admin_config_bp)  # add this
app.register_blueprint(admin_manager_bp)  # renamed blueprint
app.register_blueprint(admin_stats_bp)  # register stats blueprint
app.register_blueprint(admin_logs_bp)
app.register_blueprint(bp)

@app.route("/")
def home_page():
    return render_template("home.html")

# Override datetimeformat to handle ISO strings
@app.template_filter("datetimeformat")
def datetimeformat_iso(value, fmt="%H:%M %d/%m/%y"):
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z",""))
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value)
        else:
            return value
        return dt.strftime(fmt)
    except Exception:
        return value

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

if __name__ == "__main__":
    # Ensure the template file exists
    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template file not found: {PROMPT_TEMPLATE_PATH}")
    # Start the Flask application
    app.run(host="0.0.0.0", port=5000)
