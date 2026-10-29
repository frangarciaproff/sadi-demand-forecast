"""AWS Lambda entry point for the forecaster (SPEC 7). Container image: Dockerfile.

Events:
    {"mode": "daily"}    state update, live weather, forecast of tomorrow, scores
    {"mode": "monthly"}  Síntesis, supply and feature tables, retrain, champion
    {"mode": "score"}    scores only
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
    mode = event.get("mode", "daily")
    at = service.now_art()
    if mode == "daily":
        out = service.daily(store, at)
    elif mode == "monthly":
        out = service.monthly(store, at)
    elif mode == "score":
        out = {"scores_written": service.score(store)}
    else:
        raise ValueError(f"unsupported mode: {mode}")
    result: dict[str, Any] = json.loads(json.dumps({"mode": mode, **out}, default=str))
    logging.info("result: %s", json.dumps(result))
    return result
