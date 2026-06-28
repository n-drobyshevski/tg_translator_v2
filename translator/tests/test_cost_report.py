"""Tests for cost/billing aggregation (translator/services/cost_report.py)."""

from datetime import datetime, timezone

from translator.services import cost_report


def _fake_events():
    # Two Haiku posts + one Sonnet post + one pre-tracking (all-zero) row.
    return [
        {
            "model_used": "claude-haiku-4-5",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        },
        {
            "model_used": "claude-haiku-4-5",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        },
        {
            "model_used": "claude-sonnet-4-6",
            "input_tokens": 2000,
            "output_tokens": 1000,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        },
        {  # pre-tracking event: no tokens, no model — must contribute nothing
            "model_used": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        },
    ]


def test_summary_groups_by_model_and_sums(monkeypatch):
    monkeypatch.setattr(
        cost_report.events_dao, "load_messages", lambda since_iso=None: _fake_events()
    )
    out = cost_report._summary_since("2026-06-01T00:00:00+00:00")

    rows = {r["model"]: r for r in out["rows"]}
    # Zero-token rows are omitted; only the two models with usage remain.
    assert set(rows) == {"claude-haiku-4-5", "claude-sonnet-4-6"}
    assert rows["claude-haiku-4-5"]["input_tokens"] == 2000
    assert rows["claude-haiku-4-5"]["output_tokens"] == 1000

    # Haiku: 2000*1/1e6 + 1000*5/1e6 = 0.002 + 0.005 = 0.007
    assert round(rows["claude-haiku-4-5"]["cost_usd"], 6) == 0.007
    # Sonnet: 2000*3/1e6 + 1000*15/1e6 = 0.006 + 0.015 = 0.021
    assert round(rows["claude-sonnet-4-6"]["cost_usd"], 6) == 0.021

    assert out["total_input"] == 4000
    assert out["total_output"] == 2000
    assert round(out["total_cost_usd"], 6) == 0.028
    # Rows are sorted by cost descending (Sonnet first).
    assert out["rows"][0]["model"] == "claude-sonnet-4-6"


def test_summary_empty(monkeypatch):
    monkeypatch.setattr(
        cost_report.events_dao, "load_messages", lambda since_iso=None: []
    )
    out = cost_report._summary_since("2026-06-01T00:00:00+00:00")
    assert out["rows"] == []
    assert out["total_cost_usd"] == 0.0


def test_next_month_start_rolls_over_year():
    dec = datetime(2026, 12, 15, 9, 30, tzinfo=timezone.utc)
    assert cost_report._next_month_start(dec) == datetime(
        2027, 1, 1, tzinfo=timezone.utc
    )


def test_next_month_start_mid_year():
    jun = datetime(2026, 6, 28, tzinfo=timezone.utc)
    assert cost_report._next_month_start(jun) == datetime(
        2026, 7, 1, tzinfo=timezone.utc
    )


def test_month_start_zeroes_time():
    now = datetime(2026, 6, 28, 14, 5, 9, 123, tzinfo=timezone.utc)
    assert cost_report._month_start(now) == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_anthropic_cost_mtd_no_key_returns_none(monkeypatch):
    monkeypatch.setattr(cost_report.CONFIG, "ANTHROPIC_ADMIN_API_KEY", "", raising=False)
    assert cost_report.anthropic_cost_mtd() is None
