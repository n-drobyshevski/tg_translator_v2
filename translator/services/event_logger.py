import os
import json
from typing import Any, Dict,  Tuple
import logging
from translator.config import EVENTS_PATH, DEFAULT_STATS

from translator.models import MessageEvent

class EventRecorder:
    stats: Dict[str, Any]
    payload: Dict[str, Any]

    def __init__(self) -> None:
        self._load_base()
        self.reset()

    def _load_base(self) -> None:
        try:
            with open(EVENTS_PATH, "r", encoding="utf-8") as f:
                self.stats = json.load(f)
        except:
            self.stats = DEFAULT_STATS.copy()
        self.stats.setdefault("messages", [])

    def prefill(self) -> None:
        """
        Fill all fields of payload with default values (0, "", or None as appropriate).
        """
        from translator.models import MessageEvent
        self.payload = {}
        for field, typ in MessageEvent.__annotations__.items():
            if typ == int:
                self.payload[field] = 0
            elif typ == float:
                self.payload[field] = False
            else:
                self.payload[field] = ""

    def reset(self) -> None:
        self.prefill()

    def set(self, **kwargs: Any) -> None:
        # Set any of the above fields
        for k, v in kwargs.items():
            if k in self.payload:
                self.payload[k] = v
            else:
                raise KeyError(f"Invalid field: {k}")

    def get(self, *fields: str) -> Any | Tuple[Any, ...]:
        """
        Get the value(s) of one or more fields from the current payload.
        If one field is given, returns its value.
        If multiple fields are given, returns a tuple of values.
        """
        if not fields:
            raise ValueError("At least one field name must be provided")
            
        values = [self.payload.get(f) for f in fields]
        return values[0] if len(fields) == 1 else tuple(values)

    def finalize(self) -> None:
        # Derive event_type if needed
        if self.payload["event_type"] is None:
            self.payload["event_type"] = (
                "edit" if self.payload["edit_timestamp"] else "create"
            )
        # Create MessageEvent and append
        evt = MessageEvent(**self.payload)
        self.stats["messages"].append(evt.to_dict())

        # Write stats
        os.makedirs(os.path.dirname(EVENTS_PATH), exist_ok=True)
        with open(EVENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, ensure_ascii=False, indent=2)
        logging.info("Event recorded")
        # Optionally reset for reuse
        self.reset()

    def get_channel_cache(self) -> Dict[str, Any]:
        """Get the channel cache data for looking up source messages"""
        try:
            # Get path to channel cache
            cache_dir = os.path.dirname(EVENTS_PATH)
            cache_path = os.path.join(cache_dir, "channel_cache.json")
            
            logging.debug(f"Loading channel cache from {cache_path}")
            
            # Load channel cache file
            with open(cache_path, "r", encoding="utf-8") as f:
                channel_cache = json.load(f)
                logging.debug(f"Loaded channel cache with {len(channel_cache)} channels")
                return channel_cache
                
        except FileNotFoundError:
            logging.warning("Channel cache file not found")
            return {}
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse channel cache: {e}")
            return {}
        except Exception as e:
            logging.error(f"Error loading channel cache: {e}")
            return {}

    def __str__(self) -> str:
        lines = ["EventRecorder payload:"]
        for k, v in self.payload.items():
            lines.append(f"  {k}: {v!r}")
        return "\n".join(lines)