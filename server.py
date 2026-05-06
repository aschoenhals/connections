import csv
import os
import re
from pathlib import Path

import requests
from flask import Flask, jsonify, redirect, request, send_from_directory
from flask_cors import CORS

BASE_DIR = Path(__file__).parent
PERSONS_PATH = BASE_DIR / "persons.csv"
CONNECTIONS_PATH = BASE_DIR / "connections.csv"
PORTRAITS_DIR = BASE_DIR / "webapp" / "portraits"
WEBAPP_DIR = BASE_DIR / "webapp"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "portraits").strip()

USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
USE_SUPABASE_STORAGE = USE_SUPABASE

app = Flask(__name__, static_folder=str(WEBAPP_DIR))
CORS(app)

VALID_COLORS = {"rot", "blau", "orange"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}


def _parse_float(value):
    try:
        if value is None:
            return None
        text = str(value).strip().replace(",", ".")
        if text == "":
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _is_valid_person_id(pid: str) -> bool:
    return bool(re.fullmatch(r"p_\d+", pid))


def _supabase_headers(content_type: str | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _supabase_object_public_url(filename: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{filename}"


def _supabase_object_manage_url(filename: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{filename}"


def _supabase_rest_url(table: str, query: str = "") -> str:
    suffix = f"?{query}" if query else ""
    return f"{SUPABASE_URL}/rest/v1/{table}{suffix}"


def _raise_for_supabase_error(resp: requests.Response, fallback: str):
    if resp.ok:
        return
    try:
        payload = resp.json()
        message = payload.get("message") or payload.get("error") or fallback
    except Exception:
        message = fallback
    raise RuntimeError(f"{message} (HTTP {resp.status_code})")


def _read_persons_csv() -> dict:
    persons: dict = {}
    if not PERSONS_PATH.exists():
        return persons
    with PERSONS_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("person_id", "").strip()
            if not pid:
                continue
            persons[pid] = {
                "person_id": pid,
                "display_name": row.get("display_name", "").strip(),
                "x": _parse_float(row.get("x")),
                "y": _parse_float(row.get("y")),
            }
    return persons


def _write_persons_csv(persons: dict):
    with PERSONS_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["person_id", "display_name", "x", "y"])
        for p in persons.values():
            writer.writerow([
                p["person_id"],
                p["display_name"],
                p["x"] if p.get("x") is not None else "",
                p["y"] if p.get("y") is not None else "",
            ])


def _read_connections_csv() -> list:
    connections: list = []
    if not CONNECTIONS_PATH.exists():
        return connections
    with CONNECTIONS_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid = row.get("relation_id", "").strip()
            from_id = row.get("from_id", "").strip()
            to_id = row.get("to_id", "").strip()
            color = row.get("linienfarbe", row.get("color", "")).strip().lower()
            label = row.get("label", "").strip()
            if not rid or not from_id or not to_id or color not in VALID_COLORS:
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


def _write_connections_csv(connections: list):
    with CONNECTIONS_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["relation_id", "from_id", "to_id", "linienfarbe", "label"])
        for c in connections:
            writer.writerow([
                c["relation_id"],
                c["from_id"],
                c["to_id"],
                c["color"],
                c.get("label", ""),
            ])


def _read_persons_supabase() -> dict:
    persons: dict = {}
    resp = requests.get(
        _supabase_rest_url("persons", "select=person_id,display_name,x,y"),
        headers=_supabase_headers(),
        timeout=10,
    )
    _raise_for_supabase_error(resp, "Failed to load persons")
    for row in resp.json():
        pid = str(row.get("person_id", "")).strip()
        if not pid:
            continue
        persons[pid] = {
            "person_id": pid,
            "display_name": str(row.get("display_name", "")).strip(),
            "x": _parse_float(row.get("x")),
            "y": _parse_float(row.get("y")),
        }
    return persons


def _read_connections_supabase() -> list:
    connections = []
    resp = requests.get(
        _supabase_rest_url("connections", "select=relation_id,from_id,to_id,color,label"),
        headers=_supabase_headers(),
        timeout=10,
    )
    _raise_for_supabase_error(resp, "Failed to load connections")
    for row in resp.json():
        color = str(row.get("color", "")).strip().lower()
        if color not in VALID_COLORS:
            continue
        connections.append(
            {
                "relation_id": str(row.get("relation_id", "")).strip(),
                "from_id": str(row.get("from_id", "")).strip(),
                "to_id": str(row.get("to_id", "")).strip(),
                "color": color,
                "label": str(row.get("label", "") or "").strip(),
            }
        )
    return connections


def _write_all_supabase(persons: dict, connections: list):
    resp = requests.delete(
        _supabase_rest_url("connections", "relation_id=not.is.null"),
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        timeout=15,
    )
    _raise_for_supabase_error(resp, "Failed to clear connections")

    resp = requests.delete(
        _supabase_rest_url("persons", "person_id=not.is.null"),
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        timeout=15,
    )
    _raise_for_supabase_error(resp, "Failed to clear persons")

    if persons:
        resp = requests.post(
            _supabase_rest_url("persons"),
            headers={**_supabase_headers("application/json"), "Prefer": "return=minimal"},
            json=list(persons.values()),
            timeout=15,
        )
        _raise_for_supabase_error(resp, "Failed to write persons")

    if connections:
        resp = requests.post(
            _supabase_rest_url("connections"),
            headers={**_supabase_headers("application/json"), "Prefer": "return=minimal"},
            json=connections,
            timeout=15,
        )
        _raise_for_supabase_error(resp, "Failed to write connections")


def read_persons() -> dict:
    return _read_persons_supabase() if USE_SUPABASE else _read_persons_csv()


def read_connections() -> list:
    return _read_connections_supabase() if USE_SUPABASE else _read_connections_csv()


def write_all(persons: dict, connections: list):
    if USE_SUPABASE:
        _write_all_supabase(persons, connections)
        return
    _write_persons_csv(persons)
    _write_connections_csv(connections)


def delete_all_portraits_for_person(person_id: str):
    if USE_SUPABASE_STORAGE:
        for ext in ALLOWED_EXTENSIONS:
            requests.delete(
                _supabase_object_manage_url(f"{person_id}.{ext}"),
                headers=_supabase_headers(),
                timeout=10,
            )
        return

    PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ALLOWED_EXTENSIONS:
        p = PORTRAITS_DIR / f"{person_id}.{ext}"
        if p.exists():
            p.unlink(missing_ok=True)


def upload_portrait_binary(person_id: str, ext: str, data: bytes, content_type: str):
    if USE_SUPABASE_STORAGE:
        resp = requests.post(
            _supabase_object_manage_url(f"{person_id}.{ext}"),
            headers={
                **_supabase_headers(content_type),
                "x-upsert": "true",
            },
            data=data,
            timeout=15,
        )
        resp.raise_for_status()
        return

    PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)
    (PORTRAITS_DIR / f"{person_id}.{ext}").write_bytes(data)


@app.route("/")
def index():
    return send_from_directory(WEBAPP_DIR, "index.html")


@app.get("/portraits/<path:filename>")
def get_portrait(filename: str):
    if filename == "placeholder.svg":
        return send_from_directory(PORTRAITS_DIR, filename)
    if USE_SUPABASE_STORAGE:
        return redirect(_supabase_object_public_url(filename), code=302)
    return send_from_directory(PORTRAITS_DIR, filename)


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(WEBAPP_DIR, path)


@app.get("/api/data")
def get_data():
    persons = read_persons()
    connections = read_connections()
    return jsonify({"persons": list(persons.values()), "connections": connections})


@app.post("/api/data")
def save_data():
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object"}), 400

    persons: dict = {}
    for p in data.get("persons", []):
        pid = str(p.get("person_id", "")).strip()
        display_name = str(p.get("display_name", "")).strip()
        if not pid or not display_name:
            continue
        persons[pid] = {
            "person_id": pid,
            "display_name": display_name,
            "x": _parse_float(p.get("x")),
            "y": _parse_float(p.get("y")),
        }

    valid_ids = set(persons.keys())
    connections = []
    for c in data.get("connections", []):
        rid = str(c.get("relation_id", "")).strip()
        from_id = str(c.get("from_id", "")).strip()
        to_id = str(c.get("to_id", "")).strip()
        color = str(c.get("color", "")).strip().lower()
        label = str(c.get("label", "")).strip()
        if not rid or not from_id or not to_id or color not in VALID_COLORS:
            continue
        if from_id not in valid_ids or to_id not in valid_ids:
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

    write_all(persons, connections)
    return jsonify({"saved_persons": len(persons), "saved_connections": len(connections)})


@app.post("/api/portrait/<person_id>")
def upload_portrait(person_id: str):
    if not _is_valid_person_id(person_id):
        return jsonify({"error": "Invalid person_id"}), 400

    file = request.files.get("portrait")
    if not file or file.filename == "":
        return jsonify({"error": "No file provided"}), 400

    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "Only jpg, jpeg, png allowed"}), 400

    try:
        delete_all_portraits_for_person(person_id)
        upload_portrait_binary(
            person_id=person_id,
            ext=ext,
            data=file.read(),
            content_type=file.mimetype or "application/octet-stream",
        )
    except requests.HTTPError as err:
        return jsonify({"error": f"Storage upload failed: {err.response.status_code}"}), 502
    except Exception as err:
        return jsonify({"error": f"Upload failed: {err}"}), 500

    return jsonify({"saved": f"{person_id}.{ext}"})


@app.delete("/api/portrait/<person_id>")
def delete_portrait(person_id: str):
    if not _is_valid_person_id(person_id):
        return jsonify({"error": "Invalid person_id"}), 400

    try:
        delete_all_portraits_for_person(person_id)
    except requests.HTTPError as err:
        return jsonify({"error": f"Storage delete failed: {err.response.status_code}"}), 502
    except Exception as err:
        return jsonify({"error": f"Delete failed: {err}"}), 500

    return jsonify({"deleted": True})


@app.get("/api/health")
def health():
    db_ok = None
    storage_ok = None
    errors: list[str] = []

    if USE_SUPABASE:
        try:
            resp = requests.get(
                _supabase_rest_url("persons", "select=person_id&limit=1"),
                headers=_supabase_headers(),
                timeout=8,
            )
            _raise_for_supabase_error(resp, "REST data check failed")
            db_ok = True
        except Exception as err:
            db_ok = False
            errors.append(f"db: {err}")

    if USE_SUPABASE_STORAGE:
        try:
            url = f"{SUPABASE_URL}/storage/v1/bucket/{SUPABASE_STORAGE_BUCKET}"
            resp = requests.get(url, headers=_supabase_headers(), timeout=8)
            storage_ok = resp.ok
            if not resp.ok:
                errors.append(f"storage: http {resp.status_code}")
        except Exception as err:
            storage_ok = False
            errors.append(f"storage: {err}")

    status = 200
    if db_ok is False or storage_ok is False:
        status = 503

    return (
        jsonify(
            {
                "mode": "supabase" if USE_SUPABASE else "csv",
                "supabase_db_enabled": USE_SUPABASE,
                "supabase_storage_enabled": USE_SUPABASE_STORAGE,
                "db_ok": db_ok,
                "storage_ok": storage_ok,
                "errors": errors,
            }
        ),
        status,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 3000))
    mode = "Supabase" if USE_SUPABASE else "CSV"
    print(f"Server läuft auf http://127.0.0.1:{port} ({mode}-Modus)")
    app.run(host="0.0.0.0", port=port, debug=False)