from flask import Blueprint, render_template, jsonify, request
from flask_login import current_user, login_required
from translator.config import DEFAULT_STATS
from html import escape
import bleach
from translator.services.event_logger import EventRecorder
from typing import Dict, Any
import logging

admin_stats_bp = Blueprint("admin_stats_bp", __name__)
event_recorder = EventRecorder()

def escape_json_strings(obj):
    if isinstance(obj, str):
        clean = bleach.clean(obj)            # strip/escape any HTML
        return escape(clean)                 # then HTML-escape for safety
    if isinstance(obj, list):
        return [escape_json_strings(v) for v in obj]
    if isinstance(obj, dict):
        return {k: escape_json_strings(v) for k, v in obj.items()}
    return obj

def get_safe_events() -> Dict[str, Any]:
    """Get events from EventRecorder with proper error handling"""
    try:
        event_recorder._load_base()  # Refresh from disk
        stats = event_recorder.stats
    except Exception as e:
        logging.error(f"Failed to load events: {e}")
        stats = DEFAULT_STATS.copy()
    return stats

@admin_stats_bp.route("/admin/events", methods=["GET"])
@login_required
def admin_stats():
    stats = get_safe_events()
    return render_template("admin_events.html", stats=stats, active_page="events")

@admin_stats_bp.route("/admin/events/detail", methods=["GET"])
def admin_stats_detail():
    # avoid HTML redirect on unauthorized – return JSON 401 for the JS client
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401

    stats = get_safe_events()
    raw = stats.get("messages", [])[-100:]  # Get last 100 events
    safe = escape_json_strings(raw)
    return jsonify({"events_last_100": safe})

@admin_stats_bp.route("/admin/events/edit", methods=["POST"])
@login_required
def edit_event():
    data = request.get_json() or {}
    try:
        # Load current state
        stats = get_safe_events()
        msgs = stats.get("messages", [])
        
        # Find and update/append event
        for idx, ev in enumerate(msgs):
            if (
                str(ev.get("source_channel")) == str(data.get("source_channel"))
                and str(ev.get("message_id")) == str(data.get("message_id"))
            ):
                msgs[idx] = data
                break
        else:
            msgs.append(data)
        
        # Update via EventRecorder
        event_recorder.stats["messages"] = msgs
        event_recorder.finalize()  # This will write to disk
        return jsonify({"status": "ok"})
    except Exception as e:
        logging.error(f"Failed to edit event: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
