import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DATABASE_PATH = Path(__file__).parent / "backend" / "data" / "mega.db"


def load_stores(json_path: Path) -> list[dict]:
    with json_path.open(encoding="utf-8") as store_file:
        data = json.load(store_file)

    if isinstance(data, dict):
        data = data.get("stores")
    if not isinstance(data, list):
        raise ValueError("JSON must contain a list of stores or an object with a 'stores' list")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Import custom store locations into the Zepto cache.")
    parser.add_argument("json_file", type=Path, help="Path to the custom JSON store file")
    args = parser.parse_args()

    stores = load_stores(args.json_file)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS stores (
            id TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'zepto',
            name TEXT,
            city TEXT,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            probe_count INTEGER NOT NULL DEFAULT 1,
            discovered_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (id, platform)
        )"""
    )

    inserted = 0
    duplicates = 0
    try:
        for index, store in enumerate(stores, start=1):
            timestamp = datetime.now(timezone.utc).isoformat()
            try:
                connection.execute(
                    """INSERT INTO stores
                       (id, platform, name, lat, lng, discovered_at, last_seen_at)
                       VALUES (?, 'zepto', ?, ?, ?, ?, ?)""",
                    (
                        f"custom-{index:06d}",
                        store.get("display_name") or store.get("name"),
                        float(store["lat"]),
                        float(store["lon"]),
                        timestamp,
                        timestamp,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
        connection.commit()
    finally:
        connection.close()

    print(f"Inserted {inserted} stores; skipped {duplicates} duplicates.")


if __name__ == "__main__":
    main()