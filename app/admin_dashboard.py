from flask import Blueprint, render_template, redirect, url_for
import os
import sys
# ensure translator package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from flask_login import login_required
import logging
import json
from translator.config import EVENTS_PATH

admin_bp = Blueprint("admin_bp", __name__)
logger = logging.getLogger(__name__)  # add logger

def compute_stats(messages):
    logger.debug("compute_stats: received %d messages", len(messages))
    # count only actual post attempts (success or failure)
    total_posts = sum(1 for m in messages if m.get("posting_success") is not None)
    success_count = sum(1 for m in messages if m.get("posting_success") is True)
    fail_count = total_posts - success_count
    # Count errors: posting_success is False or api_error_code or exception_message present
    error_count = sum(
        1 for m in messages
        if m.get("posting_success") is False 
    )
    success_rate = round(100 * success_count / total_posts, 1) if total_posts > 0 else 0
    logger.debug(
        "compute_stats: total_posts=%d, success_count=%d, fail_count=%d, error_count=%d, success_rate=%.1f",
        total_posts, success_count, fail_count, error_count, success_rate
    )

    # Calculate average message size
    msg_sizes = [m.get("original_size", 0) for m in messages if m.get("original_size") is not None]
    avg_msg_size = round(sum(msg_sizes) / len(msg_sizes)) if msg_sizes else 0
    logger.debug("compute_stats: avg_msg_size=%d chars", avg_msg_size)

    # Avg latency
    latencies = [m.get("translation_time", 0) for m in messages if m.get("translation_time") is not None]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0
    logger.debug("compute_stats: avg_latency=%.2f", avg_latency)

    # Latest timestamp
    latest = max((m.get("timestamp") for m in messages if m.get("timestamp")), default="-")

    # Busiest channel pair
    from collections import Counter
    pairs = [
        f'{m.get("source_channel_name","") or m.get("source_channel","")}'

        f' → '

        f'{m.get("dest_channel_name","") or m.get("dest_channel","")}'

        for m in messages
    ]
    if pairs:
        busiest, count = Counter(pairs).most_common(1)[0]
        busiest_percent = round(100 * count / total_posts)
    else:
        busiest, busiest_percent = "-", 0

    logger.debug(
        "compute_stats: busiest_pair=%s, busiest_pair_percent=%d",
        busiest, busiest_percent
    )
    stats = {
        "total_posts": total_posts,
        "successful_posts": success_count,
        "failed_posts":  fail_count,
        "error_count":   error_count,
        "success_rate":   success_rate,
        "avg_latency":    avg_latency,
        "avg_msg_size":   avg_msg_size,
        "latest_timestamp": latest,
        "busiest_pair":   busiest,
        "busiest_pair_percent": busiest_percent,
    }
    logger.info("compute_stats: stats computed: %s", stats)
    return stats


@admin_bp.route("/admin", methods=["GET"], strict_slashes=False)
@login_required
def admin_dashboard():
    # Show only summary info and links
    info = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", "")[:8] + "..." if os.getenv("TELEGRAM_BOT_TOKEN") else "",
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "")[:8] + "..." if os.getenv("ANTHROPIC_API_KEY") else "",
        "CHRISTIANVISION_CHANNEL": os.getenv("CHRISTIANVISION_CHANNEL", ""),
        "SHALTNOTKILL_CHANNEL": os.getenv("SHALTNOTKILL_CHANNEL", ""),
    }
    try:
        with open(EVENTS_PATH, "r", encoding="utf-8") as f:
            stats_json = json.load(f)
        messages = stats_json.get("messages", [])
        stats = compute_stats(messages)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.exception("Failed to compute stats, using default values.")
        stats = {
            "total_posts": 0,
            "successful_posts": 0,
            "failed_posts": 0,
            "error_count": 0,
            "success_rate": 0,
            "avg_latency": 0,
            "latest_timestamp": "-",
            "busiest_pair": "-",
            "busiest_pair_percent": 0,
        }
        
    return render_template("admin_dashboard.html", info=info, stats=stats, active_page="dashboard")
