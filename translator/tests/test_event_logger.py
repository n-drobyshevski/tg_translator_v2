import os
import json
import pytest
from unittest.mock import patch, mock_open, MagicMock
from translator.services.event_logger import EventRecorder
from translator.models import MessageEvent

@pytest.fixture
def mock_events_path(tmp_path):
    """Create a temporary events file for testing"""
    events_file = tmp_path / "events.json"
    events_file.write_text('{"messages": []}')
    return str(events_file)

@pytest.fixture
def mock_channel_cache(tmp_path):
    """Create a temporary channel cache file for testing"""
    cache_file = tmp_path / "channel_cache.json"
    cache_data = {
        "channel1": {"id": 123, "messages": []},
        "channel2": {"id": 456, "messages": []}
    }
    cache_file.write_text(json.dumps(cache_data))
    return str(cache_file)

def test_event_recorder_init():
    """Test EventRecorder initialization"""
    with patch('translator.services.event_logger.EVENTS_PATH', 'nonexistent.json'):
        recorder = EventRecorder()
        assert isinstance(recorder.stats, dict)
        assert "messages" in recorder.stats
        assert isinstance(recorder.stats["messages"], list)

def test_event_recorder_load_base_file_not_found():
    """Test loading base stats with missing file"""
    with patch('translator.services.event_logger.EVENTS_PATH', 'nonexistent.json'):
        recorder = EventRecorder()
        assert recorder.stats == {"messages": []}

def test_event_recorder_load_base_invalid_json():
    """Test loading base stats with invalid JSON"""
    with patch('builtins.open', mock_open(read_data='invalid json')):
        recorder = EventRecorder()
        assert recorder.stats == {"messages": []}

@pytest.mark.parametrize("field_type,expected_value", [
    ("timestamp", ""),  # str field
    ("event_type", ""),  # str field
    ("source_channel_id", ""),  # str field
    ("dest_channel_id", ""),  # str field
])
def test_event_recorder_prefill(field_type, expected_value):
    """Test prefilling event fields with correct types"""
    recorder = EventRecorder()
    assert recorder.payload[field_type] == expected_value

def test_event_recorder_set_valid_field():
    """Test setting valid fields in payload"""
    recorder = EventRecorder()
    recorder.set(timestamp="2025-07-05", event_type="create")
    assert recorder.payload["timestamp"] == "2025-07-05"
    assert recorder.payload["event_type"] == "create"

def test_event_recorder_set_invalid_field():
    """Test setting invalid field raises KeyError"""
    recorder = EventRecorder()
    with pytest.raises(KeyError):
        recorder.set(invalid_field="value")

def test_event_recorder_get_single_field():
    """Test getting a single field value"""
    recorder = EventRecorder()
    recorder.set(event_type="create")
    assert recorder.get("event_type") == "create"

def test_event_recorder_get_multiple_fields():
    """Test getting multiple field values"""
    recorder = EventRecorder()
    recorder.set(event_type="create", timestamp="2025-07-05")
    event_type, timestamp = recorder.get("event_type", "timestamp")
    assert event_type == "create"
    assert timestamp == "2025-07-05"

def test_event_recorder_get_empty_fields():
    """Test get() with no fields raises ValueError"""
    recorder = EventRecorder()
    with pytest.raises(ValueError):
        recorder.get()

@patch('os.path.dirname')
@patch('json.dump')
def test_event_recorder_finalize(mock_dump, mock_dirname, tmp_path):
    """Test finalizing and saving event"""
    mock_dirname.return_value = str(tmp_path)
    
    recorder = EventRecorder()
    recorder.set(
        timestamp="2025-07-05",
        event_type="create",
        source_channel_id="123",
        dest_channel_id="456"
    )
    
    recorder.finalize()
    
    # Verify json.dump was called
    mock_dump.assert_called_once()
    
    # Verify stats were updated
    assert len(recorder.stats["messages"]) == 1
    assert recorder.stats["messages"][0]["event_type"] == "create"

def test_event_recorder_finalize_auto_event_type():
    """Test event_type is automatically set in finalize"""
    recorder = EventRecorder()
    recorder.set(
        timestamp="2025-07-05",
        event_type=None,  # Let it be auto-determined
        edit_timestamp="2025-07-05",  # This should make it an edit event
        source_channel_id="123",
        dest_channel_id="456"
    )
    
    with patch('builtins.open', mock_open()):
        recorder.finalize()
        
    assert recorder.stats["messages"][-1]["event_type"] == "edit"

def test_get_channel_cache_success(mock_channel_cache):
    """Test successful channel cache retrieval"""
    with patch('translator.services.event_logger.EVENTS_PATH', mock_channel_cache):
        recorder = EventRecorder()
        cache = recorder.get_channel_cache()
        assert len(cache) == 2
        assert cache["channel1"]["id"] == 123

def test_get_channel_cache_file_not_found():
    """Test channel cache retrieval when file is missing"""
    with patch('translator.services.event_logger.EVENTS_PATH', 'nonexistent.json'):
        recorder = EventRecorder()
        cache = recorder.get_channel_cache()
        assert cache == {}

def test_get_channel_cache_invalid_json():
    """Test channel cache retrieval with invalid JSON"""
    with patch('builtins.open', mock_open(read_data='invalid json')):
        recorder = EventRecorder()
        cache = recorder.get_channel_cache()
        assert cache == {}

def test_event_recorder_str_representation():
    """Test string representation of EventRecorder"""
    recorder = EventRecorder()
    recorder.set(event_type="create", timestamp="2025-07-05")
    str_repr = str(recorder)
    assert "event_type: 'create'" in str_repr
    assert "timestamp: '2025-07-05'" in str_repr
