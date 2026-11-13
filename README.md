# YC companies outreach database

All Y Combinator companies from [yc-oss/api](https://github.com/yc-oss/api), stored in a free Supabase
Postgres database. A small web UI lets you search, filter and track marketing outreach.

- **UI:** https://entechbot.github.io/yc-orgs-db/ (GitHub Pages, sign-in required)
- **Database:** Supabase project `YC-Leads` (ref `swgepccnutjowghlgtnc`, region eu-west-1, Free plan)

## Why Supabase

- Its free tier gives 500 MB of Postgres. ~6.4k companies take well under 50 MB.
- Email/password auth and a REST API (PostgREST) are built in, so the UI is a static page with no backend.
- Row-level security: anonymous visitors can't read or write anything. Only signed-in users can.
- One caveat: free projects **pause after ~7 days without activity**. Resume them with one click in the
  Supabase dashboard (no data is lost).

## Schema (`supabase/schema.sql`)

Table `public.companies`, with one row per company:

| Group | Columns |
|---|---|
| YC data (refreshed by import) | `id` (YC id, PK), `slug` (unique), `name`, `former_names[]`, `website`, `one_liner`, `long_description`, `batch`, `batch_sort` (generated, e.g. Summer 2024 → 20243), `status`, `stage`, `industry`, `subindustry`, `industries[]`, `tags[]`, `regions[]`, `all_locations`, `team_size`, `launched_at`, `is_hiring`, `nonprofit`, `top_company`, `logo_url`, `yc_url`, `source` (`yc-oss`/`manual`), `synced_at` |
| Outreach (never touched by import) | `contact_status` (not_contacted, queued, contacted, replied, interested, not_interested, customer, do_not_contact), `owner`, `contact_name`, `contact_email`, `last_contacted_at`, `next_follow_up`, `notes` |
| Bookkeeping | `created_at`, `updated_at` (trigger) |

Companies added by hand get ids from 100000000 upward, so they never clash with YC ids.
View `public.company_facets` feeds the UI filter dropdowns.
RLS policy: the `authenticated` role has full access, and `anon` has none.

## Credentials (none are stored in this repo)

| What | Where |
|---|---|
| Supabase personal access token (schema + import) | env var `SUPABASE_ACCESS_TOKEN`. On the entechbot machine it is the GeckIt secret `supabase-token`. Create one at https://supabase.com/dashboard/account/tokens |
| UI login | Supabase Auth user `admin@entechsolutions.com`. On the entechbot machine its password is the GeckIt secret `yc-orgs-ui-login`. |
| `web/config.js` | Project URL + **publishable** key. These are public by design; RLS protects the data. |

## Re-running the import

The import is idempotent. It upserts on `id`, overwrites only the YC columns and keeps all outreach data.
Companies that disappear from the source are not deleted. They keep an older `synced_at`.

```bash
export SUPABASE_ACCESS_TOKEN=...          # personal access token
python3 scripts/apply_schema.py           # only needed when schema.sql changes (safe to re-run)
python3 scripts/import_companies.py       # downloads all.json and upserts it
# or from a local copy:  python3 scripts/import_companies.py --file data/all.json
```

On the entechbot GeckIt machine, the broker proxy can't download from github.io. Download the file first,
then run the import with the secret:

```bash
mkdir -p data && curl -sSfL -o data/all.json https://yc-oss.github.io/api/companies/all.json
geckit secrets run --env SUPABASE_ACCESS_TOKEN=secret:supabase-token -- python3 scripts/import_companies.py --file data/all.json
```

Requirements: Python 3.9+ and `curl`. No pip packages are needed. The scripts call the Supabase Management API
SQL endpoint, so no database password is needed.

## UI (`web/`)

It's plain HTML/JS with [supabase-js](https://supabase.com/docs/reference/javascript) from a CDN. There's no build step.

- Search by name, one-liner, website or description. Filter by batch, status, industry, region, tag, contact status,
  owner and hiring. Sort and page through results, and export the current filter to CSV.
- Click a row to see the full company and edit its outreach fields. Company fields are read-only for imported rows
  (the next import would overwrite them) and editable for manual rows. You can also add and delete companies.

Run locally: `python3 -m http.server -d web 8000` and open http://localhost:8000.

Deploy: pushing to `main` (changes under `web/`) runs `.github/workflows/pages.yml`, which publishes `web/` to GitHub Pages.

### Managing users

Sign-ups are disabled. To add a teammate, open Supabase dashboard → Authentication → Users → *Add user* →
*Create new user* (tick *Auto confirm*). Alternatively, briefly enable sign-ups (Authentication → Sign In / Providers →
*Allow new users to sign up*, with *Confirm email* off), have them use https://entechbot.github.io/yc-orgs-db/#signup,
then turn sign-ups off again.
