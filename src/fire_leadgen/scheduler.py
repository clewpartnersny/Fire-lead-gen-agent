"""24/7 loop: rotates through every keyword x region query over successive
cycles (the rotation pointer survives restarts via the DB), processes what
was found, exports, sleeps, repeats.
"""

from __future__ import annotations

import logging
import signal
import threading
import time

from .db import Db
from .discovery.search import build_queries
from .pipeline import Pipeline

log = logging.getLogger("fire_leadgen.scheduler")


class Scheduler:
    def __init__(self, config: dict, db: Db, pipeline: Pipeline):
        self.cfg = config["scheduler"]
        self.sector = config.get("sector", "")
        self.db = db
        self.pipeline = pipeline
        self.queries = build_queries(config["discovery"])
        self._stop = False
        # signal handlers can only be installed from the main thread;
        # under `run-all` each sector runs in its own thread and the
        # supervisor propagates shutdown via stop()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self._handle_stop)
            signal.signal(signal.SIGINT, self._handle_stop)

    def stop(self) -> None:
        self._stop = True

    def _handle_stop(self, signum, frame):
        log.info("Received signal %s - finishing current step then stopping", signum)
        self._stop = True

    def _next_query_batch(self) -> list[str]:
        n = self.cfg.get("queries_per_cycle", 10)
        pointer = int(self.db.get_state("query_pointer", "0"))
        batch = [self.queries[(pointer + i) % len(self.queries)] for i in range(n)]
        self.db.set_state("query_pointer", str((pointer + n) % len(self.queries)))
        return batch

    def run_cycle(self) -> None:
        added = self.pipeline.discover(self._next_query_batch())
        processed = self.pipeline.process_new(self.cfg.get("max_companies_per_cycle", 25))
        exported = self.pipeline.export_ready()
        counts = self.db.counts()
        log.info(
            "[%s] Cycle done: +%d discovered, %d processed, %d exported | totals: %s",
            self.sector or "?", added, processed, exported,
            ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        )

    def run_forever(self) -> None:
        delay = self.cfg.get("cycle_delay_seconds", 300)
        log.info(
            "[%s] Starting 24/7 loop: %d queries in rotation, cycle delay %ds",
            self.sector or "?", len(self.queries), delay,
        )
        while not self._stop:
            try:
                self.run_cycle()
            except Exception:
                log.exception("Cycle failed; continuing after delay")
            for _ in range(delay):
                if self._stop:
                    break
                time.sleep(1)
        log.info("Stopped cleanly")
