"""Container health check:  python -m app.healthcheck worker:<role> | api"""
import socket, sys, time, urllib.request
from .redis_client import get_redis

kind = sys.argv[1] if len(sys.argv) > 1 else "api"
try:
    r = get_redis()
    r.ping()
    if kind.startswith("worker:"):
        role = kind.split(":")[1]
        beat = float(r.get(f"hb:{role}:{socket.gethostname()}") or 0)
        sys.exit(0 if time.time() - beat < 40 else 1)
    else:
        urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3)
except Exception:
    sys.exit(1)
