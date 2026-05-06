-- ─────────────────────────────────────────────────────────────
-- Migration v2: Multi-Mindmap-Support
-- Führe dieses Script einmalig im Supabase SQL-Editor aus.
-- ─────────────────────────────────────────────────────────────

-- 1. Mindmaps-Tabelle anlegen
CREATE TABLE mindmaps (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL DEFAULT '',   -- Leerstring = öffentlich (kein Passwort)
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Standard-Mindmap für bestehende Daten eintragen
--    password_hash = '' → öffentlich zugänglich, kein Passwort nötig
INSERT INTO mindmaps (id, name, password_hash)
VALUES ('default', 'Standard Mindmap', '');

-- ── persons ──────────────────────────────────────────────────

-- 3. mindmap_id-Spalte hinzufügen (zuerst nullable)
ALTER TABLE persons ADD COLUMN mindmap_id TEXT;

-- 4. Alle bestehenden Personen der Standard-Mindmap zuweisen
UPDATE persons SET mindmap_id = 'default';

-- 5. Spalte auf NOT NULL setzen
ALTER TABLE persons ALTER COLUMN mindmap_id SET NOT NULL;
ALTER TABLE persons ALTER COLUMN mindmap_id SET DEFAULT 'default';

-- 6. Bestehende FK-Constraints von connections auf persons entfernen
--    (damit wir den PK ändern können)
ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_from_id_fkey;
ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_to_id_fkey;

-- 7. Alten PK auf persons entfernen und durch zusammengesetzten ersetzen
ALTER TABLE persons DROP CONSTRAINT persons_pkey;
ALTER TABLE persons ADD PRIMARY KEY (mindmap_id, person_id);

-- 8. FK: persons.mindmap_id → mindmaps.id
ALTER TABLE persons
  ADD CONSTRAINT persons_mindmap_id_fkey
  FOREIGN KEY (mindmap_id) REFERENCES mindmaps(id);

-- ── connections ──────────────────────────────────────────────

-- 9. mindmap_id-Spalte hinzufügen
ALTER TABLE connections ADD COLUMN mindmap_id TEXT;

-- 10. Alle bestehenden Verbindungen der Standard-Mindmap zuweisen
UPDATE connections SET mindmap_id = 'default';

-- 11. Spalte auf NOT NULL setzen
ALTER TABLE connections ALTER COLUMN mindmap_id SET NOT NULL;
ALTER TABLE connections ALTER COLUMN mindmap_id SET DEFAULT 'default';

-- 12. Alten PK auf connections entfernen und durch zusammengesetzten ersetzen
ALTER TABLE connections DROP CONSTRAINT connections_pkey;
ALTER TABLE connections ADD PRIMARY KEY (mindmap_id, relation_id);

-- 13. Zusammengesetzte FKs: connections → persons
ALTER TABLE connections
  ADD CONSTRAINT connections_from_person_fkey
  FOREIGN KEY (mindmap_id, from_id) REFERENCES persons(mindmap_id, person_id);

ALTER TABLE connections
  ADD CONSTRAINT connections_to_person_fkey
  FOREIGN KEY (mindmap_id, to_id) REFERENCES persons(mindmap_id, person_id);

-- 14. FK: connections.mindmap_id → mindmaps.id
ALTER TABLE connections
  ADD CONSTRAINT connections_mindmap_id_fkey
  FOREIGN KEY (mindmap_id) REFERENCES mindmaps(id);

-- ─────────────────────────────────────────────────────────────
-- Fertig! Die bestehenden Daten sind jetzt unter 'default' erreichbar.
-- Die default-Mindmap ist öffentlich (kein Passwort).
-- ─────────────────────────────────────────────────────────────
