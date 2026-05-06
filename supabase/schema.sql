create table if not exists public.persons (
  person_id text primary key,
  display_name text not null,
  x double precision null,
  y double precision null,
  updated_at timestamptz not null default now()
);

create table if not exists public.connections (
  relation_id text primary key,
  from_id text not null references public.persons(person_id) on delete cascade,
  to_id text not null references public.persons(person_id) on delete cascade,
  color text not null check (color in ('rot', 'blau', 'orange')),
  label text not null default '',
  updated_at timestamptz not null default now()
);

create index if not exists idx_connections_from_id on public.connections(from_id);
create index if not exists idx_connections_to_id on public.connections(to_id);
