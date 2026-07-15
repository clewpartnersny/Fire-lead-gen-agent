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
    )
    pipeline = Pipeline(config, db, screener, writer)
    scheduler = Scheduler(config, db, pipeline)
    return db, pipeline, scheduler


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
    parser.add_argument("--config-dir", default="config", help="directory with the YAML config files")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run 24/7 (until stopped)")
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
        scheduler.run_forever()
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
