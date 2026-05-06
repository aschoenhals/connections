# Interaktive Beziehungs-Mindmap

Eine Web-App zur visuellen Darstellung von Personen und ihren Beziehungen als interaktive Mindmap.

---

## Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python · Flask · Gunicorn |
| Datenbank | Supabase (PostgREST API) |
| Bild-Storage | Supabase Storage |
| Frontend | Vanilla JS · HTML5 Canvas |
| Hosting | Render (via `render.yaml`) |

---

## Lokale Entwicklung

**Voraussetzungen:** Python 3.11+, ein Supabase-Projekt (optional, Fallback auf CSV)

```bash
# Abhängigkeiten installieren
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Server starten (CSV-Modus, kein Supabase nötig)
python server.py
# → http://localhost:3000
```

### Mit Supabase

```bash
export SUPABASE_URL="https://<project>.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="<service_role_key>"
export SUPABASE_STORAGE_BUCKET="portraits"
python server.py
```

Health-Check: `GET /api/health` gibt `"mode":"supabase"` zurück wenn alles verbunden ist.

---

## Deployment auf Render

1. Repo auf GitHub pushen
2. Render → **New → Blueprint** → Repo auswählen
3. Umgebungsvariablen setzen:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_STORAGE_BUCKET` (Standard: `portraits`)
4. Deploy starten → `render.yaml` wird automatisch erkannt

---

## Datenbank-Schema

Schema muss einmalig im Supabase SQL Editor ausgeführt werden (`supabase/schema.sql`):

```sql
-- Personen
CREATE TABLE persons (
  person_id   TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  x           FLOAT,
  y           FLOAT
);

-- Beziehungen
CREATE TABLE connections (
  relation_id TEXT PRIMARY KEY,
  from_id     TEXT REFERENCES persons(person_id),
  to_id       TEXT REFERENCES persons(person_id),
  color       TEXT CHECK (color IN ('rot', 'blau', 'orange')),
  label       TEXT DEFAULT ''
);
```

Der Storage-Bucket `portraits` muss auf **Public** gestellt sein (Supabase → Storage → Bucket settings).

---

## API-Routen

| Methode | Route | Beschreibung |
|---------|-------|--------------|
| `GET` | `/api/data` | Alle Personen und Beziehungen laden |
| `POST` | `/api/data` | Gesamten State speichern (`{ persons, connections }`) |
| `GET` | `/api/health` | Status-Check (Modus, DB, Storage) |
| `POST` | `/api/portrait/<id>` | Portrait-Bild hochladen (multipart/form-data) |
| `DELETE` | `/api/portrait/<id>` | Portrait-Bild löschen |
| `GET` | `/portraits/<filename>` | Portrait-Bild ausliefern (Redirect auf Supabase-URL im Supabase-Modus) |

---

## Bedienung

| Aktion | Beschreibung |
|--------|--------------|
| **Drag** | Person verschieben |
| **Shift + Klick** | Mehrere Personen auswählen (blauer Ring) |
| **Shift + Drag** | Ausgewählte Personen gemeinsam verschieben |
| **Rechtsklick** auf Person | Kontextmenü: Person bearbeiten / löschen, Beziehungen anzeigen |
| **Doppelklick** auf Canvas | Hereinzoomen |
| **Scrollrad** | Zoomen |
| **Mittlere Maustaste / Drag auf leerer Fläche** | Panning |
| **+ Person** | Neue Person anlegen |
| **+ Beziehung hinzufügen** | Neue Beziehung zwischen zwei Personen erstellen |
| **Suche** | Person nach Name filtern und hervorheben |
| **⦿** | Mindmap zentrieren und Zoom anpassen |
| **+  /  −** | Zoom |

### Portraits
- Im Rechtsklick-Menü → **Person bearbeiten** → Foto hochladen (JPG/PNG)
- Foto löschen über den Button im selben Modal
- Fallback: farbiger Kreis mit Initialen

### Beziehungsfarben
| Farbe | Bedeutung |
|-------|-----------|
| 🔴 rot | verliebt |
| 🟠 orange | verwandt |
| 🔵 blau | befreundet |

---

## Projektstruktur

```
├── server.py                  # Flask-Backend
├── requirements.txt
├── render.yaml                # Render-Deploy-Konfiguration
├── migrate_csv_to_supabase.py # Einmalige Migration CSV → Supabase
├── supabase/
│   └── schema.sql             # DB-Schema
├── persons.csv                # Lokaler Fallback
├── connections.csv            # Lokaler Fallback
└── webapp/
    ├── index.html
    ├── app.js                 # Gesamte Frontend-Logik
    ├── styles.css
    └── portraits/
        └── placeholder.svg
```
