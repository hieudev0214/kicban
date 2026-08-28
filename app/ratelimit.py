import threading
import time

from app.config import MAX_JOBS_PER_HOUR_PER_IP

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}

WINDOW_SECONDS = 3600


def check_and_record(client_ip: str) -> bool:
    """Return True if the request is allowed, recording it; False if the
    per-IP hourly job limit has been exceeded."""
    now = time.time()
    with _lock:
        timestamps = [t for t in _hits.get(client_ip, []) if now - t < WINDOW_SECONDS]
        if len(timestamps) >= MAX_JOBS_PER_HOUR_PER_IP:
            _hits[client_ip] = timestamps
            return False
        timestamps.append(now)
        _hits[client_ip] = timestamps
        return True
