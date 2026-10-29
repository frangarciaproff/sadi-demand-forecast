"""AWS Lambda entry point for the forecaster (SPEC 7). Container image: Dockerfile.

Events:
    {"mode": "daily"}    state update, live weather, forecast of tomorrow, scores
    {"mode": "monthly"}  Síntesis, supply and feature tables, retrain, champion
    {"mode": "score"}    scores only
    {"mode": "evening"}  documents published today (operator programme), page data
    {"mode": "site"}     public page data only (site bucket)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from sadi_forecast import service
from sadi_forecast.store import S3Store

logging.getLogger().setLevel(logging.INFO)


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    store = S3Store(os.environ["BUCKET"])
    site_bucket = os.environ.get("SITE_BUCKET")
    site = S3Store(site_bucket) if site_bucket else None
    mode = event.get("mode", "daily")
    at = service.now_art()
    if mode == "daily":
        out = service.daily(store, at, site=site)
    elif mode == "evening":
        out = service.evening(store, site, at)
    elif mode == "site" and site is not None:
        out = {"site_days": service.publish_site(store, site, at)}
    elif mode == "monthly":
        out = service.monthly(store, at)
    elif mode == "score":
        out = {"scores_written": service.score(store)}
    else:
        raise ValueError(f"unsupported mode: {mode}")
    result: dict[str, Any] = json.loads(json.dumps({"mode": mode, **out}, default=str))
    logging.info("result: %s", json.dumps(result))
    return result
