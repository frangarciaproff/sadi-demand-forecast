"""AWS Lambda entry point for the CAMMESA collector.

Events:
    {"mode": "snapshot" | "day" | "regions", "regions": [...]}
    {"mode": "docs", "days": 8}
"""

from __future__ import annotations

import logging
import os

import collect_cammesa as cc

logging.getLogger().setLevel(logging.INFO)


def handler(event: dict, context: object) -> dict:
    mode = event.get("mode", "snapshot")
    cc.FAILURES.clear()  # warm Lambda containers keep module state between invocations
    sink = cc.S3Sink(os.environ["RAW_BUCKET"])
    if mode == "docs":
        days = int(event.get("days", 8))
        ok = cc.run_docs_recent(sink, days)
        detail: dict[str, object] = {"days": days}
    else:
        regions = [int(r) for r in event.get("regions", cc.DEFAULT_REGIONS)]
        ok = cc.run_mode(sink, mode, regions)
        detail = {"regions": regions}
    if not ok:
        n_failures = cc.report_failures()
        # Raising surfaces the run as a Lambda Errors metric (email alarm)
        raise RuntimeError(
            f"collector run failed: mode={mode} {detail}; {n_failures} failure(s)"
        )
    return {"ok": True, "mode": mode, **detail}
