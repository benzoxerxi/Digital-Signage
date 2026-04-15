# Gunicorn workers, DB concurrency, and SSE

## Workers vs `TenantDisplay` updates

Playback hot state lives in PostgreSQL (`tenant_displays`). Each Gunicorn worker is a separate process: **do not rely on in-process locks** for correctness. Row updates use SQLAlchemy transactions; design panel and device traffic so concurrent `UPDATE`s are acceptable, or add explicit optimistic locking using `state_version` if you introduce multi-step read-modify-write paths.

**Rule of thumb:** start with **`--workers 2`** to **`(2 × CPU cores) + 1`** on a DB-backed app. If you see lock contention or slow heartbeats, **reduce workers** before scaling up.

## SSE (`GET /api/playback/events`)

Long-lived streams need a **large worker timeout** or the worker will be killed mid-stream.

Example:

```bash
gunicorn --workers 2 --worker-class gthread --threads 4 \
  --timeout 0 \
  --bind 127.0.0.1:8000 app:app
```

(`--timeout 0` disables the worker silent-timeout; ensure nginx/reverse-proxy idle timeouts still suit your network.)

## Nginx in front of SSE

Disable buffering for the events path so chunks reach clients immediately:

```nginx
location /api/playback/events {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 24h;
    chunked_transfer_encoding on;
}
```

Adjust `proxy_read_timeout` to match your operational policy.
