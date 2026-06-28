"""Tests for the atomic, secret-preserving .env upsert."""

import os

import pytest
from dotenv import dotenv_values

from translator.services import env_store


@pytest.fixture
def env_path(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    monkeypatch.setattr(env_store, "_root_env_path", lambda: p)
    return p


def test_replace_preserves_other_lines(env_path):
    env_path.write_text(
        "# comment\nSECRET_KEY=abc123\nANTHROPIC_API_KEY=sk-live\nANTHROPIC_MODEL=old\n",
        encoding="utf-8",
    )
    env_store.set_env_var("ANTHROPIC_MODEL", "new")
    text = env_path.read_text(encoding="utf-8")
    assert "# comment" in text
    assert "SECRET_KEY=abc123" in text
    assert "ANTHROPIC_API_KEY=sk-live" in text
    assert "ANTHROPIC_MODEL=new" in text
    assert "ANTHROPIC_MODEL=old" not in text
    assert os.environ["ANTHROPIC_MODEL"] == "new"


def test_append_when_missing(env_path):
    env_path.write_text("FOO=1", encoding="utf-8")  # note: no trailing newline
    env_store.set_env_var("BAR", "2")
    vals = dotenv_values(str(env_path))
    assert vals["FOO"] == "1"
    assert vals["BAR"] == "2"


def test_duplicate_keys_collapse(env_path):
    env_path.write_text("FOO=1\nFOO=2\n", encoding="utf-8")
    env_store.set_env_var("FOO", "3")
    assert env_path.read_text(encoding="utf-8").count("FOO=") == 1
    assert dotenv_values(str(env_path))["FOO"] == "3"


def test_value_with_spaces_roundtrips(env_path):
    env_store.set_env_var("GREETING", "hello world # not a comment")
    assert dotenv_values(str(env_path))["GREETING"] == "hello world # not a comment"


def test_export_prefix_recognized(env_path):
    env_path.write_text("export FOO=1\n", encoding="utf-8")
    env_store.set_env_var("FOO", "9")
    assert dotenv_values(str(env_path))["FOO"] == "9"
    assert env_path.read_text(encoding="utf-8").count("FOO") == 1


def test_unset_removes(env_path):
    env_path.write_text("FOO=1\nBAR=2\n", encoding="utf-8")
    os.environ["FOO"] = "1"
    env_store.unset_env_var("FOO")
    vals = dotenv_values(str(env_path))
    assert "FOO" not in vals
    assert vals["BAR"] == "2"
    assert "FOO" not in os.environ


def test_no_leftover_tmp_files(env_path):
    env_store.set_env_var("A", "1")
    env_store.set_env_var("B", "2")
    env_store.unset_env_var("A")
    leftovers = list(env_path.parent.glob(".env.*.tmp"))
    assert leftovers == []
