import csv
import os
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
PERSONS_CSV = BASE_DIR / "persons.csv"
CONNECTIONS_CSV = BASE_DIR / "connections.csv"
PORTRAITS_DIR = BASE_DIR / "webapp" / "portraits"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "portraits").strip()

if not SUPABASE_URL or not SERVICE_KEY:
    raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")


def headers(content_type=None):
    base = {
        "Authorization": f"Bearer {SERVICE_KEY}",
        "apikey": SERVICE_KEY,
    }
    if content_type:
        base["Content-Type"] = content_type
    return base


def rest_url(table, query=""):
    suffix = f"?{query}" if query else ""
    return f"{SUPABASE_URL}/rest/v1/{table}{suffix}"


def check_response(resp, fallback):
    if resp.ok:
        return
    try:
        payload = resp.json()
        detail = payload.get("message") or payload.get("error") or fallback
    except Exception:
        detail = fallback
    raise RuntimeError(f"{detail} (HTTP {resp.status_code})")


def read_persons():
    persons = []
    with PERSONS_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pid = row.get("person_id", "").strip()
            name = row.get("display_name", "").strip()
            if not pid or not name:
                continue
            x = row.get("x", "").strip()
            y = row.get("y", "").strip()
            persons.append(
                {
                    "person_id": pid,
                    "display_name": name,
                    "x": float(x) if x else None,
                    "y": float(y) if y else None,
                }
            )
    return persons


def read_connections():
    connections = []
    with CONNECTIONS_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rid = row.get("relation_id", "").strip()
            from_id = row.get("from_id", "").strip()
            to_id = row.get("to_id", "").strip()
            color = row.get("linienfarbe", row.get("color", "")).strip().lower()
            label = row.get("label", "").strip()
            if not rid or not from_id or not to_id:
                continue
            connections.append(
                {
                    "relation_id": rid,
                    "from_id": from_id,
                    "to_id": to_id,
                    "color": color,
                    "label": label,
                }
            )
    return connections


def migrate_data(persons, connections):
    resp = requests.delete(
        rest_url("connections", "relation_id=not.is.null"),
        headers={**headers(), "Prefer": "return=minimal"},
        timeout=20,
    )
    check_response(resp, "Failed to clear connections")

    resp = requests.delete(
        rest_url("persons", "person_id=not.is.null"),
        headers={**headers(), "Prefer": "return=minimal"},
        timeout=20,
    )
    check_response(resp, "Failed to clear persons")

    if persons:
        resp = requests.post(
            rest_url("persons"),
            headers={**headers("application/json"), "Prefer": "return=minimal"},
            json=persons,
            timeout=20,
        )
        check_response(resp, "Failed to insert persons")

    if connections:
        resp = requests.post(
            rest_url("connections"),
            headers={**headers("application/json"), "Prefer": "return=minimal"},
            json=connections,
            timeout=20,
        )
        check_response(resp, "Failed to insert connections")


def upload_portraits(person_ids):
    for pid in person_ids:
        found = False
        for ext in ("jpg", "jpeg", "png"):
            local = PORTRAITS_DIR / f"{pid}.{ext}"
            if not local.exists():
                continue
            found = True
            url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{pid}.{ext}"
            with local.open("rb") as fh:
                resp = requests.post(
                    url,
                    headers={
                        **headers("image/jpeg" if ext in ("jpg", "jpeg") else "image/png"),
                        "x-upsert": "true",
                    },
                    data=fh.read(),
                    timeout=20,
                )
                check_response(resp, f"Failed to upload {local.name}")
            print(f"Uploaded {local.name}")
        if not found:
            print(f"No local portrait for {pid}")


def main():
    persons = read_persons()
    connections = read_connections()
    migrate_data(persons, connections)
    upload_portraits([p["person_id"] for p in persons])
    print(f"Migrated {len(persons)} persons and {len(connections)} connections")


if __name__ == "__main__":
    main()
