"""
Watches the Java controller/dto/payload/entity source tree for changes and
automatically re-runs the parser + re-embeds the catalog a few seconds
after edits go quiet — so a newly-added @PostMapping in the Java backend
shows up in the agent without anyone remembering to run a script.

This only works when the agent process can actually see that source tree
on disk (same host, or a shared volume in Docker/k8s — see the
`java-source` mount commented into docker-compose.yml). If the agent is
deployed separately from the Java repo with no filesystem access to it,
use POST /api/agent/catalog/refresh-from-source from a CI/CD step after
deploy instead (same end result, different trigger).

Debouncing matters here: editors/IDEs fire several filesystem events per
save (temp files, atomic renames), and a save-in-progress can briefly
contain invalid Java. We wait for JAVA_SOURCE_WATCH_DEBOUNCE_SECONDS of
quiet before re-parsing rather than reacting to every single event.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.config import get_settings

logger = logging.getLogger("xevyte_agent.watcher")

REPO_ROOT = Path(__file__).resolve().parents[2]
PARSER_SCRIPT = REPO_ROOT / "scripts" / "parse_java_endpoints.py"


def run_parser(src_dir: str, out_dir: str) -> tuple[bool, str]:
    """Shells out to the (already-tested) parser script rather than
    importing its internals — keeps this watcher decoupled from parser
    implementation details and gives us process isolation: a parser crash
    on a mid-edit/invalid Java file can't take the agent process down."""
    result = subprocess.run(
        [sys.executable, str(PARSER_SCRIPT), "--src", src_dir, "--out", out_dir],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output


def refresh_catalog_and_rag(src_dir: str, out_dir: str | None = None) -> dict:
    """Re-parses the Java source, reloads the in-memory catalog, and
    re-embeds it into Chroma. Used by both the file watcher and the
    manual/CI-triggered /catalog/refresh-from-source endpoint."""
    settings = get_settings()
    out_dir = out_dir or str(Path(settings.ENDPOINT_CATALOG_PATH).parent)

    ok, output = run_parser(src_dir, out_dir)
    if not ok:
        logger.error(f"Parser failed:\n{output}")
        return {"success": False, "message": output}

    # local imports so this module doesn't force-load the RAG stack (and
    # its OPENAI_API_KEY requirement) for callers that only want the parser
    from app.catalog.loader import load_catalog
    from app.rag.ingest import ingest

    catalog = load_catalog()
    n_chunks = ingest(catalog)
    logger.info(f"Auto-refreshed catalog: {len(catalog)} endpoints, {len(catalog.modules())} modules, "
                f"{n_chunks} chunks re-embedded.")
    return {
        "success": True,
        "endpoints_discovered": len(catalog),
        "modules": len(catalog.modules()),
        "chunks_ingested": n_chunks,
        "parser_output": output,
    }


class _DebouncedJavaChangeHandler(FileSystemEventHandler):
    def __init__(self, src_dir: str, out_dir: str, debounce_seconds: float):
        self.src_dir = src_dir
        self.out_dir = out_dir
        self.debounce_seconds = debounce_seconds
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def _schedule_refresh(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._run_refresh)
            self._timer.daemon = True
            self._timer.start()

    def _run_refresh(self):
        logger.info("Java source changed and settled — re-parsing endpoint catalog...")
        try:
            refresh_catalog_and_rag(self.src_dir, self.out_dir)
        except Exception:
            logger.exception("Auto-refresh failed")

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return
        if event.src_path.endswith(".java"):
            self._schedule_refresh()


def start_watcher(src_dir: str, out_dir: str, debounce_seconds: float = 4.0) -> Observer:
    handler = _DebouncedJavaChangeHandler(src_dir, out_dir, debounce_seconds)
    observer = Observer()
    observer.schedule(handler, src_dir, recursive=True)
    observer.start()
    logger.info(f"Watching {src_dir} for .java changes (debounce={debounce_seconds}s) — catalog will "
                f"auto-refresh when new endpoints are added.")
    return observer
