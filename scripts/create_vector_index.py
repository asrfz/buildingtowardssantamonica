"""
Create the MongoDB Atlas vector search index for sensor_readings.

Run once after setting up your Atlas cluster (before starting agents):
    python scripts/create_vector_index.py

Requires MongoDB Atlas (not local MongoDB) with Atlas Search enabled.
Local instances (localhost / 127.0.0.1) will be rejected with a clear message.

Index spec:
  name: sensor_vector_index, type: vectorSearch
  embedding: vector, dims=7, similarity=cosine
  user_id, is_anomaly: filter fields (required for pre-filtered $vectorSearch)
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel
from app.config import settings

INDEX_NAME = "sensor_vector_index"
COLLECTION = "sensor_readings"


def main() -> None:
    uri = settings.MONGODB_URI
    if "localhost" in uri or "127.0.0.1" in uri:
        print("ERROR: $vectorSearch requires MongoDB Atlas, not a local instance.")
        print("       Update MONGODB_URI in .env to your Atlas connection string.")
        print("       Free tier (M0) is sufficient for the demo.")
        sys.exit(1)

    client = MongoClient(uri)
    db = client[settings.MONGODB_DB_NAME]
    collection = db[COLLECTION]

    existing = list(collection.list_search_indexes())
    if any(idx.get("name") == INDEX_NAME for idx in existing):
        print(f"[OK] Index '{INDEX_NAME}' already exists — nothing to do.")
        client.close()
        return

    index_model = SearchIndexModel(
        definition={
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": 7,
                    "similarity": "cosine",
                },
                {
                    "type": "filter",
                    "path": "user_id",
                },
                {
                    "type": "filter",
                    "path": "is_anomaly",
                },
            ]
        },
        name=INDEX_NAME,
        type="vectorSearch",
    )

    collection.create_search_index(model=index_model)
    print(f"[OK] Index '{INDEX_NAME}' creation submitted to Atlas.")
    print("     Polling for READY status (can take 30-90s)...")

    for attempt in range(36):
        time.sleep(5)
        indexes = list(collection.list_search_indexes(INDEX_NAME))
        if not indexes:
            print(".", end="", flush=True)
            continue
        status = indexes[0].get("status", "UNKNOWN")
        if status == "READY":
            print(f"\n[OK] Index is READY after ~{(attempt + 1) * 5}s.")
            break
        print(f"  [{status}]", end="", flush=True)
    else:
        print("\n[WARN] Index still building — it will be ready shortly.")
        print("       Run anomaly detection only after the index shows READY in Atlas UI.")

    client.close()


if __name__ == "__main__":
    main()
