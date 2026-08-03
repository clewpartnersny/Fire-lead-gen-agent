from __future__ import annotations

import argparse
import os
import sys

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .db import Db
from .output.sheets import SheetWriter
from .pipeline import Pipeline
from .scheduler import Scheduler
from .screening.pe_screen import PeScreener
from .utils import setup_logging


def load_config(path: str) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def build(config_dir: str, config: dict) -> tuple[Db, Pipeline, Scheduler]:
    db = Db(config["storage"]["database"])
    screener = PeScreener(os.path.join(config_dir, "pe_firms.yaml"))
    writer = SheetWriter(
        os.path.join(config_dir, "sheet_columns.yaml"),
        config["storage"].get("csv_fallback", "out/leads.csv"),
        config.get("output", {}),
    )
    pipeline = Pipeline(config, db, screener, writer)
    scheduler = Scheduler(config, db, pipeline)
    return db, pipeline, scheduler


def run_all(sectors_dir: str = "sectors") -> int:
    """Run every enabled sector's 24/7 loop, one thread per sector."""
    import glob
    import signal
    import threading

    sector_dirs = sorted(
        os.path.dirname(p) for p in glob.glob(os.path.join(sectors_dir, "*", "config.yaml"))
    )
    schedulers = []
    threads = []
    for config_dir in sector_dirs:
        config = load_config(os.path.join(config_dir, "config.yaml"))
        name = config.get("sector", config_dir)
        if not config.get("enabled", True):
            print(f"skipping {name} (enabled: false)")
            continue
        lock = _acquire_lock(config["storage"]["database"] + ".lock")
        if lock is None:
            print(f"skipping {name} (another instance holds its lock)")
            continue
        _db, _pipeline, scheduler = build(config_dir, config)
        schedulers.append(scheduler)
        thread = threading.Thread(
            target=scheduler.run_forever, name=name, daemon=True
        )
        threads.append((thread, lock))
        thread.start()
        print(f"started sector: {name}")
    if not threads:
        print("no enabled sectors found")
        return 1

    def _stop_all(signum, frame):
        for s in schedulers:
            s.stop()

    signal.signal(signal.SIGTERM, _stop_all)
    signal.signal(signal.SIGINT, _stop_all)

    _start_stall_watchdog()

    for thread, lock in threads:
        while thread.is_alive():
            thread.join(timeout=5)
        lock.close()
    return 0


def _start_stall_watchdog(stall_seconds: int = 1200, check_every: int = 30) -> None:
    """Force-exit the process if no sector makes progress for stall_seconds.

    Sector loops run on daemon threads; a hung network call (e.g. the ddgs
    HTTP layer stalling through the proxy) can freeze a thread with no clean
    way to interrupt it from Python. Rather than sit wedged, we os._exit(1)
    so an external restart wrapper (run-forever.sh) brings the fleet back.
    Every healthy sector beats once per second even while sleeping, so a
    quiet global heartbeat means genuine wedge, not normal idle time.
    """
    import threading
    import time

    from .scheduler import newest_heartbeat

    def _watch():
        # grace period so heartbeats can populate before the first cycle
        time.sleep(stall_seconds)
        while True:
            last = newest_heartbeat()
            age = time.time() - last if last else 0.0
            if last and age > stall_seconds:
                print(
                    f"STALL WATCHDOG: no sector progress for {int(age)}s "
                    f"(threshold {stall_seconds}s) - exiting for restart",
                    flush=True,
                )
                os._exit(1)
            time.sleep(check_every)

    threading.Thread(target=_watch, name="stall-watchdog", daemon=True).start()


def _acquire_lock(path: str):
    """Exclusive flock so only one 'run' instance works the database.
    Returns an open file handle (keep it alive) or None if already held."""
    import fcntl

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    handle = open(path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def test_sheet(config_dir: str, config: dict) -> int:
    """Send one labeled test row through the configured sheet output."""
    from .models import Company
    from .utils import now_iso

    writer = SheetWriter(
        os.path.join(config_dir, "sheet_columns.yaml"),
        config["storage"].get("csv_fallback", "out/leads.csv"),
    )
    row = Company(
        name="TEST ROW - safe to delete",
        domain="test.example.com",
        website="https://test.example.com",
        industry="Fire Protection",
        notes=f"connectivity test sent {now_iso()}",
    )
    try:
        written = writer.upsert([row])
    except Exception as exc:
        print(f"FAILED: {exc}")
        print(
            "\nMost common causes:\n"
            "  - SHEETS_WEBHOOK_SECRET in .env doesn't match SECRET in the Apps Script\n"
            "  - the web app deployment isn't set to 'Who has access: Anyone'\n"
            "    (URLs containing /a/macros/<yourdomain>/ usually mean domain-restricted;\n"
            "    redeploy with access 'Anyone' and use the plain\n"
            "    https://script.google.com/macros/s/.../exec URL)\n"
            "  - after editing the script you must create a NEW deployment version"
        )
        return 1
    print(f"OK - wrote {written} test row. Check the sheet, then delete the row.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fire-leadgen",
        description="Lead-gen agent for independent fire protection & life safety companies",
    )
    parser.add_argument(
        "--config-dir", default="sectors/fire-protection",
        help="sector directory with the YAML config files",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run this sector 24/7 (until stopped)")
    sub.add_parser("run-all", help="run every enabled sector in sectors/ (until stopped)")
    sub.add_parser("once", help="run a single discovery/process/export cycle and exit")
    sub.add_parser("export", help="re-export all 'ready' leads to the sheet")
    sub.add_parser("stats", help="show pipeline counts")
    ppp_cmd = sub.add_parser(
        "ppp-import",
        help="index SBA PPP loan CSVs (data.sba.gov/dataset/ppp-foia) for size/revenue estimates",
    )
    ppp_cmd.add_argument("csv_files", nargs="+", help="PPP CSV file paths")
    sub.add_parser(
        "test-sheet",
        help="send one labeled TEST row to the configured sheet output and report the result",
    )
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    if args.command == "run-all":
        return run_all()
    config = load_config(os.path.join(args.config_dir, "config.yaml"))

    if args.command == "ppp-import":
        from .enrichment import ppp

        db = Db(config["storage"]["database"])
        n = ppp.import_csvs(db.conn, args.csv_files)
        print(f"Indexed {n} PPP loan rows")
        return 0

    if args.command == "test-sheet":
        return test_sheet(args.config_dir, config)

    db, pipeline, scheduler = build(args.config_dir, config)

    if args.command == "run":
        lock_path = config["storage"]["database"] + ".lock"
        lock = _acquire_lock(lock_path)
        if lock is None:
            print(f"Another 'fire-leadgen run' instance holds {lock_path}; exiting.")
            return 1
        try:
            scheduler.run_forever()
        finally:
            lock.close()
    elif args.command == "once":
        scheduler.run_cycle()
    elif args.command == "export":
        pipeline.export_ready()
    elif args.command == "stats":
        for status, n in sorted(db.counts().items()):
            print(f"{status:10s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
