"""Scheduler: automates the two jobs.

  * Price refresh  -> 4x/day at REFRESH_HOURS (default 12,15,18,21)
  * Catalog discovery -> 1x/day at DISCOVERY_HOUR (default 03:00)

Run as a long-lived process:
    python -m app.jobs.scheduler            # blocks, runs on schedule
    python -m app.jobs.scheduler --now refresh    # run one cycle now and exit
    python -m app.jobs.scheduler --now discovery
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.jobs import refresh_prices, run_discovery

sys.stdout.reconfigure(encoding="utf-8")

SOURCES = ["sumashtech", "rio", "kry", "dazzle"]


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def refresh_all() -> None:
    _log("PRICE REFRESH starting")
    for src in SOURCES:
        try:
            refresh_prices.run(src)
        except Exception as e:
            _log(f"refresh {src} FAILED: {e}")
    _log("PRICE REFRESH done")


def discover_all() -> None:
    _log("CATALOG DISCOVERY starting")
    for src in SOURCES:
        try:
            run_discovery.run(src)
        except Exception as e:
            _log(f"discovery {src} FAILED: {e}")
    _log("CATALOG DISCOVERY done")


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone=settings.timezone)
    for hour in settings.refresh_hour_list:
        sched.add_job(refresh_all, CronTrigger(hour=hour, minute=0),
                      id=f"refresh_{hour}", name=f"price-refresh@{hour}:00")
    sched.add_job(discover_all, CronTrigger(hour=settings.discovery_hour, minute=0),
                  id="discovery", name=f"discovery@{settings.discovery_hour}:00")
    return sched


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", choices=["refresh", "discovery"],
                    help="run one cycle immediately and exit (no scheduling)")
    args = ap.parse_args()

    if args.now == "refresh":
        refresh_all()
        return
    if args.now == "discovery":
        discover_all()
        return

    sched = build_scheduler()
    _log(f"Scheduler up (tz={settings.timezone}). "
         f"Refresh at {settings.refresh_hour_list}, discovery at {settings.discovery_hour}:00.")
    for job in sched.get_jobs():
        _log(f"  scheduled: {job.name}  [{job.trigger}]")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        _log("Scheduler stopped.")


if __name__ == "__main__":
    main()
