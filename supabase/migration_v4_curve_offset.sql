-- Migration v4: persist curve_offset per connection
-- curve_offset is NULL for existing rows → frontend falls back to computed value on first load,
-- then saves the value so it never changes again.
alter table public.connections
  add column if not exists curve_offset double precision null default null;
