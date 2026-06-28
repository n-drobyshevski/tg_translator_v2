import pytest
import json
import os
from pathlib import Path
from translator.config import CONFIG, EVENTS_PATH
import logging

def test_get_destination_msg_id_basic(tmp_path, monkeypatch):
    """Test basic message ID mapping functionality"""
    # Create a temporary events.json for testing
    events_data = {
        "messages": [
            {
                "source_channel_id": "-1002657093374",  # Match real channel ID format
                "message_id": "100",
                "dest_message_id": "200",
                "event_type": "create"
            },
            {
                "source_channel_id": "-1002657093374",
                "message_id": "100",
                "dest_message_id": "201",  # More recent mapping
                "event_type": "edit"
            }
        ]
    }
    
    events_path = tmp_path / "events.json"
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(events_data, f, indent=2)

    # Mock EVENTS_PATH directly in config module
    monkeypatch.setattr('translator.config.EVENTS_PATH', str(events_path))
    
    # Should return the most recent mapping (201)
    result = CONFIG.get_destination_msg_id(-1002657093374, "100")
    assert result == "201", f"Expected dest_message_id '201' but got {result}"


def test_get_destination_msg_id_edge_cases(tmp_path, monkeypatch):
    """Test various edge cases for message ID mapping"""
    events_data = {
        "messages": [
            {
                "source_channel_id": "-1002657093374",
                "message_id": "100",
                "dest_message_id": "200",
                "event_type": "create"
            },
            {
                "source_channel_id": "-1002657093374",
                "message_id": "101",
                "dest_message_id": None,  # Test null dest_message_id
                "event_type": "create"
            }
        ]
    }
    
    events_path = tmp_path / "events.json"
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(events_data, f, indent=2)

    monkeypatch.setattr('translator.config.EVENTS_PATH', str(events_path))
    
    # Non-existent message should return None
    assert CONFIG.get_destination_msg_id(-1002657093374, "999") is None
    
    # Invalid source channel should return None
    assert CONFIG.get_destination_msg_id(-999999999999, "100") is None
    
    # Message with null dest_message_id should return None
    assert CONFIG.get_destination_msg_id(-1002657093374, "101") is None

    # Invalid input types should raise ValueError
    with pytest.raises(ValueError):
        CONFIG.get_destination_msg_id("not_an_int", "100")  # type: ignore
    
    with pytest.raises(ValueError):
        CONFIG.get_destination_msg_id(-1002657093374, "")  # Empty message_id


def test_get_destination_msg_id_file_handling(tmp_path, monkeypatch):
    """Test file handling edge cases"""
    events_path = tmp_path / "nonexistent.json"
    monkeypatch.setattr('translator.config.EVENTS_PATH', str(events_path))

    # Missing file should return None
    assert CONFIG.get_destination_msg_id(-1002657093374, "100") is None

    # Create invalid JSON file
    with open(events_path, "w") as f:
        f.write("{ invalid json }")

    # Invalid JSON should raise JSONDecodeError
    with pytest.raises(json.JSONDecodeError):
        CONFIG.get_destination_msg_id(-1002657093374, "100")

    # Create empty but valid JSON
    with open(events_path, "w") as f:
        json.dump({"messages": []}, f)

    # Empty messages list should return None
    assert CONFIG.get_destination_msg_id(-1002657093374, "100") is None
