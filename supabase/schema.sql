-- YC companies marketing database (Supabase / Postgres).
-- Idempotent: safe to re-apply with `python3 scripts/apply_schema.py`.

create extension if not exists pg_trgm with schema extensions;

-- Manually added companies get ids far above YC's ids so they never collide.
create sequence if not exists public.companies_manual_id_seq start with 100000000;

create table if not exists public.companies (
  -- Source data from yc-oss/api (overwritten on every import)
  id                bigint primary key default nextval('public.companies_manual_id_seq'),
  slug              text not null unique,
  name              text not null,
  former_names      text[] not null default '{}',
  website           text,
  one_liner         text,
  long_description  text,
  batch             text,
  status            text,          -- Active | Inactive | Acquired | Public
  stage             text,          -- Early | Growth
  industry          text,
  subindustry       text,
  industries        text[] not null default '{}',
  tags              text[] not null default '{}',
  regions           text[] not null default '{}',
  all_locations     text,
  team_size         integer,
  launched_at       timestamptz,
  is_hiring         boolean,
  nonprofit         boolean,
  top_company       boolean,
  logo_url          text,
  yc_url            text,
  source            text not null default 'manual',   -- 'yc-oss' for imported rows
  synced_at         timestamptz,                      -- last import that saw this company

  -- Marketing / outreach tracking (never touched by the import)
  contact_status    text not null default 'not_contacted',
  owner             text,
  contact_name      text,
  contact_email     text,
  last_contacted_at date,
  next_follow_up    date,
  notes             text,

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  -- Sortable batch key, e.g. 'Summer 2024' -> 20243 (Winter=1, Spring=2, Summer=3, Fall=4)
  batch_sort integer generated always as (
    case when batch ~ '^(Winter|Spring|Summer|Fall) [0-9]{4}$' then
      split_part(batch, ' ', 2)::int * 10 +
      case split_part(batch, ' ', 1) when 'Winter' then 1 when 'Spring' then 2 when 'Summer' then 3 else 4 end
    end
  ) stored
);

alter sequence public.companies_manual_id_seq owned by public.companies.id;

do $$ begin
  alter table public.companies add constraint companies_contact_status_check check (contact_status in
    ('not_contacted', 'queued', 'contacted', 'replied', 'interested', 'not_interested', 'customer', 'do_not_contact'));
exception when duplicate_object then null; end $$;

create index if not exists companies_batch_sort_idx on public.companies (batch_sort);
create index if not exists companies_status_idx on public.companies (status);
create index if not exists companies_industry_idx on public.companies (industry);
create index if not exists companies_contact_status_idx on public.companies (contact_status);
create index if not exists companies_tags_idx on public.companies using gin (tags);
create index if not exists companies_industries_idx on public.companies using gin (industries);
create index if not exists companies_regions_idx on public.companies using gin (regions);
create index if not exists companies_name_trgm_idx on public.companies using gin (name extensions.gin_trgm_ops);

create or replace function public.set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin new.updated_at = now(); return new; end $$;

drop trigger if exists companies_set_updated_at on public.companies;
create trigger companies_set_updated_at before update on public.companies
  for each row execute function public.set_updated_at();

-- Access: only signed-in users can read or write; anonymous visitors get nothing.
alter table public.companies enable row level security;
revoke all on public.companies from anon;
grant select, insert, update, delete on public.companies to authenticated;
grant usage on sequence public.companies_manual_id_seq to authenticated;

drop policy if exists "authenticated full access" on public.companies;
create policy "authenticated full access" on public.companies
  for all to authenticated using (true) with check (true);

-- Filter options for the UI (respects RLS of the caller).
create or replace view public.company_facets with (security_invoker = true) as
  select 'batch' as facet, batch as value, max(batch_sort) as sort, count(*) as n
    from public.companies where batch is not null group by batch
  union all
  select 'status', status, null, count(*) from public.companies where status is not null group by status
  union all
  select 'industry', industry, null, count(*) from public.companies where industry is not null group by industry
  union all
  select 'region', r, null, count(*) from public.companies, unnest(regions) r group by r
  union all
  select 'tag', t, null, count(*) from public.companies, unnest(tags) t group by t;

revoke all on public.company_facets from anon;
grant select on public.company_facets to authenticated;
