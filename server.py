import csv
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

BASE_DIR         = Path(__file__).parent
PERSONS_PATH     = BASE_DIR / "persons.csv"
CONNECTIONS_PATH = BASE_DIR / "connections.csv"
PORTRAITS_DIR    = BASE_DIR / "webapp" / "portraits"
WEBAPP_DIR       = BASE_DIR / "webapp"

app = Flask(__name__, static_folder=str(WEBAPP_DIR))
CORS(app)

VALID_COLORS = {"rot", "blau", "orange"}


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


# ── persons.csv ───────────────────────────────────────────────

def read_persons() -> dict:
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
                "person_id":   pid,
                "display_name": row.get("display_name", "").strip(),
                "x": _parse_float(row.get("x")),
                "y": _parse_float(row.get("y")),
            }
    return persons


def write_persons(persons: dict):
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


# ── connections.csv ───────────────────────────────────────────

def read_connections() -> list:
    connections: list = []
    if not CONNECTIONS_PATH.exists():
        return connections
    with CONNECTIONS_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid     = row.get("relation_id", "").strip()
            from_id = row.get("from_id", "").strip()
            to_id   = row.get("to_id", "").strip()
            color   = row.get("linienfarbe", row.get("color", "")).strip().lower()
            label   = row.get("label", "").strip()
            if not rid or not from_id or not to_id or color not in VALID_COLORS:
                continue
            connections.append({
                "relation_id": rid,
                "from_id":     from_id,
                "to_id":       to_id,
                "color":       color,
                "label":       label,
            })
    return connections


def write_connections(connections: list):
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




# ── Static files ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(WEBAPP_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(WEBAPP_DIR, path)


# ── API ──────────────────────────────────────────────────────

@app.get("/api/data")
def get_data():
    persons     = read_persons()
    connections = read_connections()
    return jsonify({"persons": list(persons.values()), "connections": connections})


@app.post("/api/data")
def save_data():
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object"}), 400

    persons: dict = {}
    for p in data.get("persons", []):
        pid          = str(p.get("person_id", "")).strip()
        display_name = str(p.get("display_name", "")).strip()
        if not pid or not display_name:
            continue
        persons[pid] = {
            "person_id":    pid,
            "display_name": display_name,
            "x": _parse_float(p.get("x")),
            "y": _parse_float(p.get("y")),
        }

    valid_ids   = set(persons.keys())
    connections = []
    for c in data.get("connections", []):
        rid     = str(c.get("relation_id", "")).strip()
        from_id = str(c.get("from_id", "")).strip()
        to_id   = str(c.get("to_id", "")).strip()
        color   = str(c.get("color", "")).strip().lower()
        label   = str(c.get("label", "")).strip()
        if not rid or not from_id or not to_id or color not in VALID_COLORS:
            continue
        if from_id not in valid_ids or to_id not in valid_ids:
            continue
        connections.append({
            "relation_id": rid,
            "from_id":     from_id,
            "to_id":       to_id,
            "color":       color,
            "label":       label,
        })

    write_persons(persons)
    write_connections(connections)
    return jsonify({"saved_persons": len(persons), "saved_connections": len(connections)})


# ── Portrait upload / delete ─────────────────────────────────

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}


def _is_valid_person_id(pid: str) -> bool:
    """Allow only p_<digits> to prevent path traversal."""
    import re
    return bool(re.fullmatch(r'p_\d+', pid))


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

    PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)

    # Remove any existing portrait for this person (any extension)
    for old in PORTRAITS_DIR.glob(f"{person_id}.*"):
        if old.name != "placeholder.svg":
            old.unlink(missing_ok=True)

    dest = PORTRAITS_DIR / f"{person_id}.{ext}"
    file.save(dest)
    return jsonify({"saved": f"{person_id}.{ext}"})


@app.delete("/api/portrait/<person_id>")
def delete_portrait(person_id: str):
    if not _is_valid_person_id(person_id):
        return jsonify({"error": "Invalid person_id"}), 400

    deleted = []
    for f in PORTRAITS_DIR.glob(f"{person_id}.*"):
        if f.name != "placeholder.svg":
            f.unlink(missing_ok=True)
            deleted.append(f.name)
    return jsonify({"deleted": deleted})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 3000))
    print(f"Server läuft auf http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
