"""Cross-platform single-instance guard via an exclusive advisory lock.

The relay bot must run as exactly one process — two instances would double-post
every message. The previous check only detected a *locked* session file, which
misses a second idle instance. This holds an OS-level exclusive lock on a
lockfile for the whole process lifetime; the lock is released automatically when
the process exits (so it self-clears after a crash, unlike a bare PID file).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("MAIN")

# Keep the file handle alive for the process lifetime so the lock is held.
_lock_handle = None


class AlreadyRunningError(RuntimeError):
    """Raised when another instance already holds the lock."""


def acquire_single_instance_lock(path: str) -> None:
    """Acquire an exclusive lock at ``path`` or raise AlreadyRunningError."""
    global _lock_handle

    handle = open(path, "a+")
    try:
        if os.name == "nt":  # Windows
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # POSIX (PythonAnywhere production)
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError) as e:
        handle.close()
        raise AlreadyRunningError(
            f"Another bot instance appears to be running (lock held on {path}): {e}"
        ) from e

    # Record our PID for human debugging (not used for locking).
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except OSError:
        pass

    _lock_handle = handle
    logger.info("Acquired single-instance lock: %s (pid %s)", path, os.getpid())
