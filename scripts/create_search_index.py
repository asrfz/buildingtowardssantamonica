"""
Create Atlas Search (full-text) and Vector Search indexes for HomePulse.

Usage:
    python scripts/create_search_index.py
    python scripts/create_search_index.py --with-incident-vector
    python scripts/create_search_index.py --only events

MongoDB Atlas **M0 (free) clusters typically allow only 3 Search/Vector indexes total**
per project. This repo also uses `sensor_vector_index` on `sensor_readings`
(`scripts/create_vector_index.py`). A common M0 layout is:

  1. sensor_vector_index   (sensor_readings) — multivariate anomalies
  2. sensor_event_search    (events)          — GET /search/events
  3. incident_text_search   (incident_reports) — GET /search/incidents

There is usually **no room** for `incident_vector_index` until you upgrade Atlas
or remove an unused index in the Atlas UI. By default this script **does not**
request `incident_vector_index` (use `--with-incident-vector` on a larger tier).

If the path has a trailing backslash, Windows may error — use:
    python scripts/create_search_index.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel

from app.config import settings


def ensure_collection(db, name: str) -> None:
    if name not in db.list_collection_names():
        db.create_collection(name)
        print(f"  [OK] Created empty collection '{name}' (required before search indexes)\n")


def wait_for_ready(collection, index_name: str, timeout_s: int = 180) -> None:
    print(f"     Waiting for '{index_name}'...", end="", flush=True)
    for _ in range(timeout_s // 5):
        time.sleep(5)
        indexes = list(collection.list_search_indexes(index_name))
        if indexes and indexes[0].get("status") == "READY":
            print(" READY")
            return
        print(".", end="", flush=True)
    print(" (still building — check Atlas UI)")


def _index_name(model: SearchIndexModel) -> str:
    doc = getattr(model, "document", None) or {}
    return doc.get("name", "")


def try_create_index(
    collection,
    model: SearchIndexModel,
    label: str,
    *,
    quota_hit_ref: list[bool],
) -> bool:
    """
    Returns True if a new index was submitted (not already present).
    Sets quota_hit_ref[0] if Atlas refused due to index limits.
    """
    name = _index_name(model)
    existing = [i["name"] for i in collection.list_search_indexes()]
    if name in existing:
        print(f"  [OK] '{name}' already exists — skipping")
        return False
    try:
        collection.create_search_index(model=model)
        print(f"  [OK] '{label}' submitted (`{name}`)")
        return True
    except OperationFailure as e:
        msg = (e.details or {}).get("errmsg", str(e))
        code = getattr(e, "code", None)
        if code == 20 or "maximum number" in msg.lower() or "FTS" in msg:
            quota_hit_ref[0] = True
            print(f"  [WARN] Atlas refused new index `{name}` (quota / tier limit).")
            print(f"         Message: {msg}")
            print(
                "         Fix: Atlas UI → Search → delete an unused index, or upgrade tier.\n"
                "         On M0 with sensor_vector_index + 2 text indexes, omit\n"
                "         `--with-incident-vector` (default) or drop one text index.\n"
            )
            return False
        raise


def build_models() -> dict[str, SearchIndexModel]:
    event_text = SearchIndexModel(
        definition={
            "analyzer": "lucene.standard",
            "analyzers": [
                {
                    "name": "underscore_split",
                    "charFilters": [{"type": "mapping", "mappings": {"_": " "}}],
                    "tokenizer": {"type": "whitespace"},
                    "tokenFilters": [{"type": "lowercase"}],
                }
            ],
            "mappings": {
                "dynamic": False,
                "fields": {
                    "event_type": {"type": "string", "analyzer": "underscore_split"},
                    "event_label": {"type": "string", "analyzer": "lucene.standard"},
                    "recommended_action": {"type": "string", "analyzer": "lucene.standard"},
                    "triage_reason": {"type": "string", "analyzer": "lucene.standard"},
                    "monitor_reasoning": {"type": "string", "analyzer": "lucene.standard"},
                    "severity": {"type": "token"},
                    "status": {"type": "token"},
                    "user_id_str": {"type": "token"},
                    "detected_at": {"type": "date"},
                },
            },
        },
        name="sensor_event_search",
        type="search",
    )

    incident_text = SearchIndexModel(
        definition={
            "analyzer": "lucene.standard",
            "analyzers": [
                {
                    "name": "underscore_split",
                    "charFilters": [{"type": "mapping", "mappings": {"_": " "}}],
                    "tokenizer": {"type": "whitespace"},
                    "tokenFilters": [{"type": "lowercase"}],
                }
            ],
            "mappings": {
                "dynamic": False,
                "fields": {
                    "title": {"type": "string", "analyzer": "lucene.standard"},
                    "summary": {"type": "string", "analyzer": "lucene.standard"},
                    "event_label": {"type": "string", "analyzer": "lucene.standard"},
                    "recommended_action": {"type": "string", "analyzer": "lucene.standard"},
                    "event_type": {"type": "string", "analyzer": "underscore_split"},
                    "severity": {"type": "token"},
                    "user_id_str": {"type": "token"},
                },
            },
        },
        name="incident_text_search",
        type="search",
    )

    incident_vector = SearchIndexModel(
        definition={
            "fields": [
                {"type": "vector", "path": "embedding", "numDimensions": 7, "similarity": "cosine"},
                {"type": "filter", "path": "user_id"},
            ]
        },
        name="incident_vector_index",
        type="vectorSearch",
    )

    return {
        "events": event_text,
        "incidents-text": incident_text,
        "incidents-vector": incident_vector,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Atlas Search indexes for HomePulse.")
    parser.add_argument(
        "--only",
        choices=("events", "incidents-text", "incidents-vector", "all-text"),
        default=None,
        help="Create just one index (or all full-text: events + incidents-text).",
    )
    parser.add_argument(
        "--with-incident-vector",
        action="store_true",
        help="Also create incident_vector_index (usually fails on M0 if 3 indexes already exist).",
    )
    args = parser.parse_args()

    uri = settings.MONGODB_URI
    if "localhost" in uri or "127.0.0.1" in uri:
        print("ERROR: Atlas Search requires MongoDB Atlas, not localhost.")
        sys.exit(1)

    client = MongoClient(uri)
    db = client[settings.MONGODB_DB_NAME]
    models = build_models()

    print("\nCreating Atlas Search indexes...\n")
    print(
        "Note: M0 free tier allows ~3 Search/Vector indexes total (including "
        "sensor_vector_index on sensor_readings if you ran create_vector_index.py).\n"
    )

    ensure_collection(db, "events")
    ensure_collection(db, "incident_reports")

    events_coll = db["events"]
    incidents_coll = db["incident_reports"]

    quota_hit: list[bool] = [False]
    created: list[tuple[object, str]] = []

    def plan() -> list[tuple[str, object, SearchIndexModel]]:
        steps: list[tuple[str, object, SearchIndexModel]] = []
        if args.only == "events":
            steps.append(("events full-text", events_coll, models["events"]))
        elif args.only == "incidents-text":
            steps.append(("incidents full-text", incidents_coll, models["incidents-text"]))
        elif args.only == "incidents-vector":
            steps.append(("incidents vector", incidents_coll, models["incidents-vector"]))
        elif args.only == "all-text":
            steps.append(("events full-text", events_coll, models["events"]))
            steps.append(("incidents full-text", incidents_coll, models["incidents-text"]))
        else:
            steps.append(("events full-text", events_coll, models["events"]))
            steps.append(("incidents full-text", incidents_coll, models["incidents-text"]))
            if args.with_incident_vector:
                steps.append(("incidents vector", incidents_coll, models["incidents-vector"]))
        return steps

    for label, coll, model in plan():
        if quota_hit[0]:
            print(f"  [SKIP] '{label}' — earlier step hit Atlas index quota.")
            continue
        if try_create_index(coll, model, label, quota_hit_ref=quota_hit):
            created.append((coll, _index_name(model)))

    if created:
        print("\nPolling for index readiness (Atlas often needs 30–120s)...\n")
        for coll, iname in created:
            wait_for_ready(coll, iname)

    print("\n[Done] create_search_index finished.")
    if quota_hit[0]:
        print(
            "[INFO] Some indexes were skipped due to tier limits. "
            "GET /search/* still falls back to regex when $search is unavailable.\n"
            "Similar incidents via $vectorSearch need incident_vector_index on a tier with room.\n"
        )
    else:
        print("Test: GET /search/events?q=stove+left+on\n")

    client.close()


if __name__ == "__main__":
    main()
