-- Migration v3: Connection label positions
-- Run once in the Supabase SQL editor.

ALTER TABLE public.connections
  ADD COLUMN IF NOT EXISTS label_dx DOUBLE PRECISION NOT NULL DEFAULT 0;

ALTER TABLE public.connections
  ADD COLUMN IF NOT EXISTS label_dy DOUBLE PRECISION NOT NULL DEFAULT 0;
