import csv
import hashlib
import hmac
import os
import re
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, redirect, request, send_from_directory
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

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

# ── Auth ─────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY") or hashlib.sha256(os.urandom(32)).hexdigest()
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 Tage
MINDMAP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


def _is_valid_mindmap_id(mid: str) -> bool:
    return bool(MINDMAP_ID_RE.fullmatch(mid))


def _make_token(mindmap_id: str) -> str:
    payload = f"{mindmap_id}:{int(time.time()) + TOKEN_TTL_SECONDS}"
    payload_hex = payload.encode().hex()
    sig = hmac.new(SECRET_KEY.encode(), payload_hex.encode(), hashlib.sha256).hexdigest()
    return f"{payload_hex}.{sig}"


def _verify_token(token: str) -> str | None:
    try:
        payload_hex, sig = token.rsplit(".", 1)
        expected = hmac.new(SECRET_KEY.encode(), payload_hex.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = bytes.fromhex(payload_hex).decode()
        mid, exp_str = payload.rsplit(":", 1)
        if int(exp_str) < int(time.time()):
            return None
        if not _is_valid_mindmap_id(mid):
            return None
        return mid
    except Exception:
        return None


def _require_auth():
    """Returns (mindmap_id, None) on success, (None, error_response) on failure."""
    if not USE_SUPABASE:
        return "default", None  # CSV-Modus: keine Auth nötig
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, (jsonify({"error": "Nicht autorisiert"}), 401)
    mid = _verify_token(auth_header[7:])
    if not mid:
        return None, (jsonify({"error": "Token ungültig oder abgelaufen"}), 401)
    return mid, None


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


def _read_persons_supabase(mindmap_id: str) -> dict:
    persons: dict = {}
    resp = requests.get(
        _supabase_rest_url("persons", f"select=person_id,display_name,x,y&mindmap_id=eq.{mindmap_id}"),
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


def _read_connections_supabase(mindmap_id: str) -> list:
    connections = []
    resp = requests.get(
        _supabase_rest_url("connections", f"select=relation_id,from_id,to_id,color,label&mindmap_id=eq.{mindmap_id}"),
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


def _write_all_supabase(persons: dict, connections: list, mindmap_id: str):
    resp = requests.delete(
        _supabase_rest_url("connections", f"mindmap_id=eq.{mindmap_id}"),
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        timeout=15,
    )
    _raise_for_supabase_error(resp, "Failed to clear connections")

    resp = requests.delete(
        _supabase_rest_url("persons", f"mindmap_id=eq.{mindmap_id}"),
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        timeout=15,
    )
    _raise_for_supabase_error(resp, "Failed to clear persons")

    if persons:
        persons_with_mid = [{**p, "mindmap_id": mindmap_id} for p in persons.values()]
        resp = requests.post(
            _supabase_rest_url("persons"),
            headers={**_supabase_headers("application/json"), "Prefer": "return=minimal"},
            json=persons_with_mid,
            timeout=15,
        )
        _raise_for_supabase_error(resp, "Failed to write persons")

    if connections:
        connections_with_mid = [{**c, "mindmap_id": mindmap_id} for c in connections]
        resp = requests.post(
            _supabase_rest_url("connections"),
            headers={**_supabase_headers("application/json"), "Prefer": "return=minimal"},
            json=connections_with_mid,
            timeout=15,
        )
        _raise_for_supabase_error(resp, "Failed to write connections")


def _get_mindmap_supabase(mindmap_id: str) -> dict | None:
    resp = requests.get(
        _supabase_rest_url("mindmaps", f"select=id,name,password_hash&id=eq.{mindmap_id}"),
        headers=_supabase_headers(),
        timeout=10,
    )
    _raise_for_supabase_error(resp, "Failed to query mindmap")
    rows = resp.json()
    return rows[0] if rows else None


def _create_mindmap_supabase(mindmap_id: str, name: str, password_hash: str):
    resp = requests.post(
        _supabase_rest_url("mindmaps"),
        headers={**_supabase_headers("application/json"), "Prefer": "return=minimal"},
        json={"id": mindmap_id, "name": name, "password_hash": password_hash},
        timeout=10,
    )
    _raise_for_supabase_error(resp, "Failed to create mindmap")


def read_persons(mindmap_id: str = "default") -> dict:
    return _read_persons_supabase(mindmap_id) if USE_SUPABASE else _read_persons_csv()


def read_connections(mindmap_id: str = "default") -> list:
    return _read_connections_supabase(mindmap_id) if USE_SUPABASE else _read_connections_csv()


def write_all(persons: dict, connections: list, mindmap_id: str = "default"):
    if USE_SUPABASE:
        _write_all_supabase(persons, connections, mindmap_id)
        return
    _write_persons_csv(persons)
    _write_connections_csv(connections)


def delete_all_portraits_for_person(person_id: str, mindmap_id: str = "default"):
    if USE_SUPABASE_STORAGE:
        for ext in ALLOWED_EXTENSIONS:
            requests.delete(
                _supabase_object_manage_url(f"{mindmap_id}/{person_id}.{ext}"),
                headers=_supabase_headers(),
                timeout=10,
            )
        return

    PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ALLOWED_EXTENSIONS:
        p = PORTRAITS_DIR / mindmap_id / f"{person_id}.{ext}"
        if p.exists():
            p.unlink(missing_ok=True)


def upload_portrait_binary(person_id: str, ext: str, data: bytes, content_type: str, mindmap_id: str = "default"):
    if USE_SUPABASE_STORAGE:
        resp = requests.post(
            _supabase_object_manage_url(f"{mindmap_id}/{person_id}.{ext}"),
            headers={
                **_supabase_headers(content_type),
                "x-upsert": "true",
            },
            data=data,
            timeout=15,
        )
        resp.raise_for_status()
        return

    local_dir = PORTRAITS_DIR / mindmap_id
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / f"{person_id}.{ext}").write_bytes(data)


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
    mindmap_id, err = _require_auth()
    if err:
        return err
    persons = read_persons(mindmap_id)
    connections = read_connections(mindmap_id)
    return jsonify({"persons": list(persons.values()), "connections": connections})


@app.post("/api/data")
def save_data():
    mindmap_id, err = _require_auth()
    if err:
        return err

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

    write_all(persons, connections, mindmap_id)
    return jsonify({"saved_persons": len(persons), "saved_connections": len(connections)})


@app.post("/api/portrait/<person_id>")
def upload_portrait(person_id: str):
    if not _is_valid_person_id(person_id):
        return jsonify({"error": "Invalid person_id"}), 400

    mindmap_id, err = _require_auth()
    if err:
        return err

    file = request.files.get("portrait")
    if not file or file.filename == "":
        return jsonify({"error": "No file provided"}), 400

    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "Only jpg, jpeg, png allowed"}), 400

    try:
        delete_all_portraits_for_person(person_id, mindmap_id)
        upload_portrait_binary(
            person_id=person_id,
            ext=ext,
            data=file.read(),
            content_type=file.mimetype or "application/octet-stream",
            mindmap_id=mindmap_id,
        )
    except requests.HTTPError as err:
        return jsonify({"error": f"Storage upload failed: {err.response.status_code}"}), 502
    except Exception as err:
        return jsonify({"error": f"Upload failed: {err}"}), 500

    return jsonify({"saved": f"{mindmap_id}/{person_id}.{ext}"})


@app.delete("/api/portrait/<person_id>")
def delete_portrait(person_id: str):
    if not _is_valid_person_id(person_id):
        return jsonify({"error": "Invalid person_id"}), 400

    mindmap_id, err = _require_auth()
    if err:
        return err

    try:
        delete_all_portraits_for_person(person_id, mindmap_id)
    except requests.HTTPError as err:
        return jsonify({"error": f"Storage delete failed: {err.response.status_code}"}), 502
    except Exception as err:
        return jsonify({"error": f"Delete failed: {err}"}), 500

    return jsonify({"deleted": True})


@app.post("/api/mindmap")
def create_mindmap():
    if not USE_SUPABASE:
        return jsonify({"error": "Multi-Mindmap nur im Supabase-Modus verfügbar"}), 501

    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON-Objekt erwartet"}), 400

    mid = str(data.get("id", "")).strip().lower()
    name = str(data.get("name", "")).strip()
    password = str(data.get("password", "")).strip()

    if not _is_valid_mindmap_id(mid):
        return jsonify({"error": "ID ungültig. Erlaubt: Kleinbuchstaben, Ziffern, Bindestriche; mind. 3 Zeichen, max. 40"}), 400
    if not name:
        return jsonify({"error": "Name fehlt"}), 400
    if len(password) < 4:
        return jsonify({"error": "Passwort muss mindestens 4 Zeichen haben"}), 400

    try:
        existing = _get_mindmap_supabase(mid)
    except RuntimeError as err:
        return jsonify({"error": str(err)}), 500

    if existing is not None:
        return jsonify({"error": "Diese ID ist bereits vergeben"}), 409

    pw_hash = generate_password_hash(password)
    try:
        _create_mindmap_supabase(mid, name, pw_hash)
    except RuntimeError as err:
        return jsonify({"error": str(err)}), 500

    token = _make_token(mid)
    return jsonify({"token": token, "mindmap_id": mid, "name": name}), 201


@app.post("/api/mindmap/auth")
def auth_mindmap():
    if not USE_SUPABASE:
        # CSV-Modus: keine Mindmaps, direkt als "default" einloggen
        return jsonify({"token": _make_token("default"), "mindmap_id": "default", "name": "Lokal"})

    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON-Objekt erwartet"}), 400

    mid = str(data.get("id", "")).strip().lower()
    password = str(data.get("password", "")).strip()

    if not mid:
        return jsonify({"error": "ID fehlt"}), 400

    try:
        mindmap = _get_mindmap_supabase(mid)
    except RuntimeError as err:
        return jsonify({"error": str(err)}), 500

    if mindmap is None:
        return jsonify({"error": "Mindmap nicht gefunden"}), 404

    pw_hash = mindmap.get("password_hash", "")
    if pw_hash and not check_password_hash(pw_hash, password):
        return jsonify({"error": "Falsches Passwort"}), 403

    token = _make_token(mid)
    return jsonify({"token": token, "mindmap_id": mid, "name": mindmap.get("name", mid)})


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