"""Cost / billing reporting for the admin DM 'AI Settings → Cost' view.

Two sources, by design (see plan):

* **Local estimate** — sums the per-message token usage recorded on each event
  (``input_tokens`` / ``output_tokens`` / cache tokens / ``model_used``) and
  prices it via :mod:`translator.pricing`. Always available, but only counts
  messages translated *after* token tracking shipped.
* **Authoritative** — when ``CONFIG.ANTHROPIC_ADMIN_API_KEY`` is set, the
  month-to-date headline figure comes from Anthropic's Admin Cost API
  (``GET /v1/organizations/cost_report``). On any failure we silently fall back
  to the local estimate.

Direct API billing is post-paid monthly with no prepaid reset, so "next billing"
is the next month-end invoice — reported here as the 1st of next month (UTC).

``render`` is **synchronous** (the menu/``/cost`` call sites are sync), so the
Admin API fetch uses a short-timeout sync ``httpx`` call; it only runs when an
admin opens the Cost view and an admin key is configured.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from translator import pricing
from translator.config import CONFIG
from translator.db import events_dao
from translator.services.admin_i18n import t

log = logging.getLogger("ADMIN.COST")

_COST_REPORT_URL = "https://api.anthropic.com/v1/organizations/cost_report"
_HTTP_TIMEOUT = 8.0
_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
)


def _summary_since(since_iso: str) -> Dict[str, Any]:
    """Aggregate recorded token usage + estimated cost since an ISO timestamp.

    Groups by ``model_used`` (blank → the currently configured model). Rows with
    no recorded tokens (e.g. pre-tracking events) are omitted. Returns totals and
    per-model rows sorted by cost descending.
    """
    try:
        messages = events_dao.load_messages(since_iso=since_iso)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("cost summary load failed: %s", exc)
        messages = []

    by_model: Dict[str, Dict[str, int]] = {}
    for m in messages:
        model = m.get("model_used") or CONFIG.ANTHROPIC_MODEL
        acc = by_model.setdefault(model, {f: 0 for f in _TOKEN_FIELDS})
        for f in _TOKEN_FIELDS:
            acc[f] += int(m.get(f) or 0)

    rows: List[Dict[str, Any]] = []
    total_cost = 0.0
    total_in = 0
    total_out = 0
    for model, acc in by_model.items():
        if not any(acc.values()):
            continue  # pre-tracking / non-AI events contribute nothing
        cost = pricing.estimate_cost_usd(
            model,
            acc["input_tokens"],
            acc["output_tokens"],
            acc["cache_read_tokens"],
            acc["cache_creation_tokens"],
        )
        total_cost += cost
        total_in += acc["input_tokens"]
        total_out += acc["output_tokens"]
        rows.append(
            {
                "model": model,
                "input_tokens": acc["input_tokens"],
                "output_tokens": acc["output_tokens"],
                "cache_read_tokens": acc["cache_read_tokens"],
                "cache_creation_tokens": acc["cache_creation_tokens"],
                "cost_usd": cost,
            }
        )
    rows.sort(key=lambda r: r["cost_usd"], reverse=True)
    return {
        "since_iso": since_iso,
        "rows": rows,
        "total_input": total_in,
        "total_output": total_out,
        "total_cost_usd": total_cost,
    }


def local_summary(days: int) -> Dict[str, Any]:
    """Local cost/token summary over the last ``days`` days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = _summary_since(cutoff)
    out["days"] = days
    return out


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month_start(now: datetime) -> datetime:
    start = _month_start(now)
    # Jump past the end of this month, then snap back to day 1.
    return _month_start(start + timedelta(days=32))


def billing_period() -> Dict[str, Any]:
    """Current-month billing context: label, MTD local summary, next invoice."""
    now = datetime.now(timezone.utc)
    start = _month_start(now)
    nxt = _next_month_start(now)
    summary = _summary_since(start.isoformat())
    return {
        "month_label": now.strftime("%Y-%m"),
        "month_start_iso": start.isoformat(),
        "next_invoice": nxt.strftime("%Y-%m-%d"),
        "summary": summary,
        "local_mtd_usd": summary["total_cost_usd"],
    }


def anthropic_cost_mtd() -> Optional[float]:
    """Authoritative month-to-date USD cost from the Admin Cost API, or None.

    Returns None when no admin key is configured or on any error (caller falls
    back to the local estimate). Amounts come back as decimal strings in the
    lowest currency unit (cents), so the running total is divided by 100.
    """
    key = getattr(CONFIG, "ANTHROPIC_ADMIN_API_KEY", "")
    if not key:
        return None
    start = _month_start(datetime.now(timezone.utc)).isoformat()
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    params: Dict[str, Any] = {"starting_at": start, "bucket_width": "1d"}
    cents = 0.0
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            for _ in range(12):  # bounded pagination (a month is ≤31 daily buckets)
                r = client.get(_COST_REPORT_URL, headers=headers, params=params)
                if r.status_code != 200:
                    log.warning("cost_report %s: %s", r.status_code, r.text[:200])
                    return None
                body = r.json()
                for bucket in body.get("data", []):
                    for item in bucket.get("results", []):
                        cents += float(item.get("amount") or 0)
                if not body.get("has_more"):
                    break
                params["page"] = body.get("next_page")
                if not params["page"]:
                    break
    except Exception as exc:
        log.warning("cost_report fetch failed: %s", exc)
        return None
    return cents / 100.0


def render(lang: str = "en") -> str:
    """Build the localised cost/billing report shown in the Cost menu."""
    bp = billing_period()
    summary = bp["summary"]
    lines = [t("cost_title", lang)]

    admin = anthropic_cost_mtd()
    if admin is not None:
        lines.append(
            t("cost_mtd_admin", lang, month=bp["month_label"], amount=f"{admin:.2f}")
        )
    else:
        lines.append(
            t(
                "cost_mtd_local",
                lang,
                month=bp["month_label"],
                amount=f"{bp['local_mtd_usd']:.2f}",
            )
        )
    lines.append(t("cost_billing_next", lang, date=bp["next_invoice"]))

    if summary["rows"]:
        lines.append("")
        lines.append(t("cost_breakdown_header", lang))
        for r in summary["rows"]:
            lines.append(
                t(
                    "cost_model_row",
                    lang,
                    model=html.escape(str(r["model"])),
                    in_tok=r["input_tokens"],
                    out_tok=r["output_tokens"],
                    cost=f"{r['cost_usd']:.2f}",
                )
            )
    else:
        lines.append(t("cost_none", lang))

    lines.append("")
    lines.append(t("cost_caveat", lang))
    return "\n".join(lines)
