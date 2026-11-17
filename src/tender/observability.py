"""Local, tenant-separated structured audit events; never records API credentials."""

import hashlib
import json
import os
import threading
from contextvars import ContextVar
from datetime import datetime, timezone

revision_context = ContextVar("revision_context", default="standalone")
_lock = threading.Lock()


def write_event(settings, tenant, revision, event):
    if not settings.logs_enabled:
        return
    tenant_key = hashlib.sha256(tenant.encode()).hexdigest()[:20]
    revision_key = hashlib.sha256(revision.encode()).hexdigest()[:24]
    directory = settings.data_dir / "logs" / tenant_key
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{revision_key}.jsonl"
    record = {
        "schema_version": 1,
        "at": datetime.now(timezone.utc).isoformat(),
        "revision_id": revision,
        **event,
    }
    if settings.logs_redact_text:
        for name in ("input", "output", "context"):
            if name in record:
                raw = json.dumps(record.pop(name), default=str).encode()
                record[name + "_sha256"] = hashlib.sha256(raw).hexdigest()
    with _lock:
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a") as stream:
            stream.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")


def record_model(settings, tenant, role, context, output, usage, elapsed):
    write_event(
        settings,
        tenant,
        revision_context.get(),
        {
            "event": "model_result",
            "role": role,
            "context": context,
            "output": output,
            "usage": usage,
            "duration_ms": round(elapsed * 1000),
            "provider": settings.model_provider,
            "model": settings.model_name,
        },
    )


def purge_logs(settings):
    import time

    cutoff = time.time() - settings.logs_retention_days * 86400
    removed = 0
    for path in (settings.data_dir / "logs").glob("*/*.jsonl"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed
