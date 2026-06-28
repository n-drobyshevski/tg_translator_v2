import os
from flask import Blueprint, render_template, request, abort, redirect, url_for, flash
from flask_login import login_required
from translator.config import CACHE_DIR

admin_logs_bp = Blueprint("admin_logs_bp", __name__)

@admin_logs_bp.route("/admin/logs", methods=["GET"])
@login_required
def show_logs():
    log_path = os.path.join(CACHE_DIR, "bot.log")
    if not os.path.exists(log_path):
        return render_template("admin_logs.html", log_lines=["Log file not found."], active_page="logs")    
    try:
        # Show only the last 500 lines for performance
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-500:]
    except Exception as e:
        lines = [f"Error reading log file: {e}"]
    return render_template("admin_logs.html", log_lines=lines, active_page="logs")

@admin_logs_bp.route("/admin/logs/clear", methods=["POST"])
@login_required
def clear_logs():
    log_path = os.path.join(CACHE_DIR, "bot.log")
    try:
        open(log_path, "w", encoding="utf-8").close()
        flash("Log file cleared.", "success")
    except Exception as e:
        flash(f"Failed to clear log file: {e}", "error")
    return redirect(url_for("admin_logs_bp.show_logs"))
