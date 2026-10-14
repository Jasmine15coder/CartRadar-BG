"""Load the Bangalore dark-store list into the local SQLite stores table."""

import csv
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STORES_FILE = ROOT / "bangalore_stores.txt"
DATABASE_FILE = ROOT / "backend" / "data" / "mega.db"
REQUIRED_COLUMNS = {"id", "name", "lat", "lng", "city"}


def read_stores(path: Path = STORES_FILE) -> list[dict[str, str | float]]:
    with path.open(encoding="utf-8", newline="") as store_file:
        reader = csv.DictReader(store_file, delimiter="\t")
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError(
                f"{path} must have tab-separated columns: "
                f"{', '.join(sorted(REQUIRED_COLUMNS))}"
            )

        stores: list[dict[str, str | float]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(row.get(column) is None for column in REQUIRED_COLUMNS):
                raise ValueError(f"Malformed store record on line {line_number}")

            store_id = row["id"].strip()
            name = row["name"].strip()
            city = row["city"].strip()
            if not store_id or not name or not city:
                raise ValueError(f"Missing id, name, or city on line {line_number}")

            try:
                lat = float(row["lat"])
                lng = float(row["lng"])
            except ValueError as error:
                raise ValueError(f"Invalid coordinates on line {line_number}") from error
            if not (math.isfinite(lat) and -90 <= lat <= 90):
                raise ValueError(f"Invalid latitude on line {line_number}")
            if not (math.isfinite(lng) and -180 <= lng <= 180):
                raise ValueError(f"Invalid longitude on line {line_number}")

            stores.append(
                {"id": store_id, "name": name, "lat": lat, "lng": lng, "city": city}
            )

    if not stores:
        raise ValueError(f"No store records found in {path}")
    return stores


def update_database() -> int:
    if not DATABASE_FILE.is_file():
        raise FileNotFoundError(f"SQLite database not found: {DATABASE_FILE}")

    stores = read_stores()
    timestamp = datetime.now(timezone.utc).isoformat()
    connection = sqlite3.connect(DATABASE_FILE)
    try:
        with connection:
            connection.executemany(
                """INSERT INTO stores
                   (id, platform, name, city, lat, lng, probe_count,
                    discovered_at, last_seen_at)
                   VALUES (?, 'zepto', ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(id, platform) DO UPDATE SET
                       name = excluded.name,
                       city = excluded.city,
                       lat = excluded.lat,
                       lng = excluded.lng,
                       last_seen_at = excluded.last_seen_at""",
                [
                    (
                        store["id"],
                        store["name"],
                        store["city"],
                        store["lat"],
                        store["lng"],
                        timestamp,
                        timestamp,
                    )
                    for store in stores
                ],
            )
    except sqlite3.Error as error:
        raise RuntimeError(f"Failed to update {DATABASE_FILE}: {error}") from error
    finally:
        connection.close()

    return len(stores)


if __name__ == "__main__":
    print(f"Imported or updated {update_database()} Bangalore stores.")
