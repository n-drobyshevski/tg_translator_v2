"""aggregator.py – lightweight helpers only

This module has **no Flask side‑effects**.  It provides small utility
functions used by *flask_app.py* and by unit tests.
"""

from __future__ import annotations

import json
import datetime
import os
from collections import Counter, defaultdict
from datetime import timedelta, date, timezone
from typing import Any, Dict, List
import logging
from translator.config import EVENTS_PATH

logger = logging.getLogger(__name__)

###############################################################################
# Public helpers                                                              #
###############################################################################


def load_messages() -> List[Dict[str, Any]]:
    """
    Load all messages from the events file specified by EVENTS_PATH.

    Returns:
        List of message/event dictionaries.
    Raises:
        FileNotFoundError: If the events file does not exist.
    """
    if not os.path.exists(EVENTS_PATH):
        raise FileNotFoundError(f"Events file not found: {EVENTS_PATH}")
    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    msgs = data.get("messages", [])
    return msgs


def build_summary(messages: List[Dict[str, Any]], days: int = 10) -> Dict[str, List]:
    """
    Build a daily summary of message counts for the last `days` days.

    Args:
        messages: List of message/event dictionaries.
        days: Number of days to include in the summary.

    Returns:
        Dict with 'labels' (dates) and 'counts' (message counts per day).
    """
    today = date.today()
    labels = [(today - timedelta(days=d)).isoformat() for d in reversed(range(days))]
    day_counter: Counter[str] = Counter()
    for evt in messages:
        ts = evt.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts)
            day = dt.date().isoformat()
            day_counter[day] += 1
        except ValueError as e:
            logger.warning("build_summary: skip evt, parse error %s", e)
            continue
    counts = [day_counter.get(label, 0) for label in labels]
    # logger.info("build_summary: labels=%s counts=%s", labels, counts)
    return {"labels": labels, "counts": counts}


def build_10d_channels(
    messages: List[Dict[str, Any]], days: int = 10
) -> Dict[str, Any]:
    """
    Build a 10-day per-channel message count matrix.

    Args:
        messages: List of message/event dictionaries.
        days: Number of days to include.

    Returns:
        Dict with 'labels' (dates) and 'series' (per-channel counts).
    """
    today = date.today()
    labels = [(today - timedelta(days=d)).isoformat() for d in reversed(range(days))]
    per_chan: Dict[str, Counter[str]] = {}
    for evt in messages:
        # include every message that has a timestamp
        ts = evt.get("timestamp")
        if not ts:
            logger.warning(
                "build_10d_channels: skip evt %s, no timestamp",
                evt.get("message_id", "unknown"),
            )
            continue
        chan = evt.get("source_channel_name") or evt.get("source_channel", "")
        try:
            dt = datetime.datetime.fromisoformat(ts)
            day = dt.date().isoformat()
            per_chan.setdefault(chan, Counter())[day] += 1
        except ValueError as e:
            logger.warning(
                "build_10d_channels: skip evt %s, parse error %s",
                evt.get("message_id", "unknown"),
                e,
            )
            continue
    series = [
        {"label": chan, "data": [per_chan[chan].get(d, 0) for d in labels]}
        for chan in sorted(per_chan)
    ]
    return {"labels": labels, "series": series}


def build_hourly_matrix(messages: list[dict]) -> dict:
    """
    Build a matrix of message counts by hour of day and day of week.

    Args:
        messages: List of message/event dictionaries.

    Returns:
        Dict with 'data' (matrix), 'xLabels' (hours), 'yLabels' (days), and 'max' (max count).
    """
    counts = Counter()
    maxv = 0
    events_by_cell = defaultdict(list)
    for m in messages:
        # Accept both event_type and event field for 'create'
        evt = m.get("event_type") or m.get("event") or ""
        # Filter: only messages where event_type or event is 'create'
        if evt and evt != "create":
            continue
        ts = m.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except ValueError as e:
            logger.warning(
                "build_hourly_matrix: skip m %s, parse error %s",
                m.get("message_id", "unknown"),
                e,
            )
            continue
        hour = dt.strftime("%H")
        dow = dt.strftime("%a")
        counts[(hour, dow)] += 1
        maxv = max(maxv, counts[(hour, dow)])
        events_by_cell[(hour, dow)].append(m)
    xLabels = [f"{h:02d}" for h in range(24)]
    yLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    data = [
        {
            "x": x,
            "y": y,
            "v": counts.get((x, y), 0),
            "events": events_by_cell.get((x, y), []),
        }
        for y in yLabels
        for x in xLabels
    ]
    return {"data": data, "xLabels": xLabels, "yLabels": yLabels, "max": maxv}


def build_10d_by_channel(messages: list[dict]) -> dict:
    """
    Build a 10-day message count summary by channel.

    Args:
        messages: List of message/event dictionaries.

    Returns:
        Dict with 'labels' (channel names) and 'counts' (message counts).
    """
    logger.info("build_10d_by_channel: messages=%d", len(messages))
    # use timezone-aware UTC now
    cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=10)
    data = defaultdict(int)
    for m in messages:
        if m.get("event") != "create":
            continue
        ts = m.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except ValueError as e:
            logger.info("build_10d_by_channel: skip m, parse error %s", e)
            continue
        if dt > cutoff:
            ch = m.get("source_channel_name", "Unknown")
            data[ch] += 1
    labels = list(data.keys())
    counts = [data[ch] for ch in labels]
    return {"labels": labels, "counts": counts}


def build_throughput_latency(messages):
    """
    Build data for a scatter plot: original_size vs translation_time.

    Args:
        messages: List of message/event dictionaries.

    Returns:
        Dict with 'points' for scatter plot (each point is a dict).
    """
    scatter = [
        {
            "x": m.get("original_size", 0),
            "y": m.get("translation_time", 0),
            "label": m.get("source_channel_name", "") or m.get("source_channel", ""),
            "id": m.get("message_id"),
            "dest_message_id": m.get("dest_message_id"),
        }
        for m in messages
        if m.get("original_size") is not None and m.get("translation_time") is not None
    ]
    return {"points": scatter}
