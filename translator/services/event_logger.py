import os
import json
from typing import Any, Dict,  Tuple
import logging
from translator import config as _cfg
from translator.config import EVENTS_PATH, DEFAULT_STATS

from translator.models import MessageEvent

# Default value per annotated field type. Looked up by the annotation object so
# it is robust even if annotations are strings (PEP 563). float -> 0.0 (NOT False,
# which was a long-standing bug that stored translation_time as `false`).
_TYPE_DEFAULTS = {int: 0, float: 0.0, bool: False, str: ""}

class EventRecorder:
    stats: Dict[str, Any]
    payload: Dict[str, Any]

    def __init__(self) -> None:
        # The legacy JSON path keeps an in-memory copy of the whole file; the
        # SQLite path appends row-by-row and needs no base load.
        if _cfg.STORAGE_BACKEND == "json":
            self._load_base()
        else:
            self.stats = {"messages": []}
        self.reset()

    def _load_base(self) -> None:
        try:
            with open(EVENTS_PATH, "r", encoding="utf-8") as f:
                self.stats = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logging.warning("Could not load %s (%s); starting fresh", EVENTS_PATH, e)
            self.stats = DEFAULT_STATS.copy()
        self.stats.setdefault("messages", [])

    def prefill(self) -> None:
        """
        Fill all fields of payload with type-appropriate defaults (0, 0.0, False, "").
        """
        from translator.models import MessageEvent
        self.payload = {
            field: _TYPE_DEFAULTS.get(typ, "")
            for field, typ in MessageEvent.__annotations__.items()
        }

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
        # Derive event_type if not set (prefill leaves it as "").
        if self.payload.get("event_type") in (None, ""):
            self.payload["event_type"] = (
                "edit" if self.payload.get("edit_timestamp") else "create"
            )

        if _cfg.STORAGE_BACKEND == "json":
            # Legacy path: append to the in-memory list and rewrite the whole file.
            evt = MessageEvent(**self.payload)
            self.stats["messages"].append(evt.to_dict())
            os.makedirs(os.path.dirname(EVENTS_PATH), exist_ok=True)
            with open(EVENTS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        else:
            # SQLite path: single-row append, multi-process safe under WAL.
            from translator.db import events_dao
            events_dao.insert_event(self.payload)

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