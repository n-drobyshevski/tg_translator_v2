import os
import pytest
from translator.config import CONFIG

def test_config_env(monkeypatch):
    # Set all required environment variables
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "api")
    monkeypatch.setenv("TEST_CHANNEL", "1")  # Test source channel
    
    # Source channels
    monkeypatch.setenv("CHRISTIANVISION_CHANNEL", "11")
    monkeypatch.setenv("SHALTNOTKILL_CHANNEL", "22")
    monkeypatch.setenv("TEST_CHANNEL", "33")
    
    # Destination channels
    monkeypatch.setenv("CHRISTIANVISION_EN_CHANNEL_ID", "12")
    monkeypatch.setenv("SHALTNOTKILL_EN_CHANNEL_ID", "23")
    monkeypatch.setenv("TEST_EN_CHANNEL_ID", "34")
    
    # Optional channel names
    monkeypatch.setenv("CHRISTIANVISION_CHANNEL_NAME", "christianvision")
    monkeypatch.setenv("CHRISTIANVISION_EN_CHANNEL_NAME", "christianvision_en")
    monkeypatch.setenv("SHALTNOTKILL_CHANNEL_NAME", "shaltnotkill")
    monkeypatch.setenv("SHALTNOTKILL_EN_CHANNEL_NAME", "shaltnotkill_en")
    monkeypatch.setenv("TEST_CHANNEL_NAME", "test")
    monkeypatch.setenv("TEST_EN_CHANNEL_NAME", "test_en")
    
    CONFIG.reload()  # Reload config with new env vars
    d = CONFIG.as_dict()
    assert d["TELEGRAM_BOT_TOKEN"] == "tok"
    assert "channels" in d
    assert len(d["channels"]) == 6  # 3 pairs of source/destination channels


def set_all_env(monkeypatch):
    """Helper to set minimal required environment variables"""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "api")
    monkeypatch.setenv("TEST_CHANNEL", "33")
    
    # Source and destination channel pairs
    monkeypatch.setenv("CHRISTIANVISION_CHANNEL", "11")
    monkeypatch.setenv("CHRISTIANVISION_EN_CHANNEL_ID", "12")
    monkeypatch.setenv("SHALTNOTKILL_CHANNEL", "22")
    monkeypatch.setenv("SHALTNOTKILL_EN_CHANNEL_ID", "23")
    monkeypatch.setenv("TEST_CHANNEL", "33")
    monkeypatch.setenv("TEST_EN_CHANNEL_ID", "34")


def test_config_reload(monkeypatch):
    set_all_env(monkeypatch)
    CONFIG.reload()
    assert CONFIG.TELEGRAM_BOT_TOKEN == "tok"
    assert CONFIG.TELEGRAM_API_ID == 1
    assert CONFIG.get_channel_id("test") == 33  # Test channel ID from TEST_CHANNEL
    assert CONFIG.get_channel_id("test_en") == 34  # Test destination channel from TEST_EN_CHANNEL_ID


def test_config_validate_missing(monkeypatch):
    """Test validation fails when required vars are missing"""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "api")
    monkeypatch.setenv("TEST_CHANNEL", "33")
    monkeypatch.setenv("CHRISTIANVISION_CHANNEL", "11")
    monkeypatch.setenv("SHALTNOTKILL_CHANNEL", "22")
    with pytest.raises(RuntimeError) as e:
        CONFIG.reload()  # Use reload instead of creating new instance
    assert "TELEGRAM_BOT_TOKEN" in str(e.value)


def test_config_as_dict(monkeypatch):
    """Test config serialization includes all expected fields"""
    set_all_env(monkeypatch)
    CONFIG.reload()
    d = CONFIG.as_dict()
    assert d["TELEGRAM_BOT_TOKEN"] == "tok"
    assert "channels" in d
    assert len(d["channels"]) == 6  # 3 pairs of source/destination channels
    assert "LOG_LEVEL" in d


def test_channel_pairs(monkeypatch):
    """Test channel pairs are correctly configured"""
    set_all_env(monkeypatch)
    CONFIG.reload()
    
    # Test source channels
    assert CONFIG.get_channel_id("christianvision") == 11
    assert CONFIG.get_channel_id("shaltnotkill") == 22
    assert CONFIG.get_channel_id("test") == 33
    
    # Test destination channels
    assert CONFIG.get_channel_id("christianvision_en") == 12
    assert CONFIG.get_channel_id("shaltnotkill_en") == 23
    assert CONFIG.get_channel_id("test_en") == 34
    
    # Test channel name lookup
    assert CONFIG.get_channel_name(11) == "christianvision"
    assert CONFIG.get_channel_name(23) == "shaltnotkill_en"
    
    # Test destination ID lookup
    assert CONFIG.get_destination_id(11) == 12  # christianvision -> christianvision_en
    assert CONFIG.get_destination_id(22) == 23  # shaltnotkill -> shaltnotkill_en
    assert CONFIG.get_destination_id(33) == 34  # test -> test_en
