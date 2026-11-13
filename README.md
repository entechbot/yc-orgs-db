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
| YC data (refreshed by import) | `id` (YC id, PK), `slug` (unique), `name`, `former_names[]`, `website`, `one_liner`, `long_description`, `batch`, `batch_sort` (generated, e.g. Summer 2024 → 20243), `status`, `stage`, `industry`, `subindustry`, `industries[]`, `tags[]`, `regions[]`, `all_locations`, `team_size`, `launched_at`, `is_hiring`, `nonprofit`, `top_company`, `logo_url`, `yc_url`, `source` (`yc-oss`/`manual`), `synced_at`, `removed_from_source_at` |
| Outreach (never touched by import) | `contact_status` (not_contacted, queued, contacted, replied, interested, not_interested, customer, do_not_contact), `owner`, `contact_name`, `contact_email`, `last_contacted_at`, `next_follow_up`, `notes` |
| Bookkeeping | `created_at`, `updated_at` (trigger) |

Companies added by hand get ids from 100000000 upward, so they never clash with YC ids.
View `public.company_facets` feeds the UI filter dropdowns.
RLS policy: the `authenticated` role has full access, and `anon` has none.

## Credentials (none are stored in this repo)

| What | Used by | Where it lives |
|---|---|---|
| Supabase **secret API key** (`sb_secret_…`, project-scoped, bypasses RLS) | import script / daily sync | GitHub Actions secret `SUPABASE_SECRET_KEY` in `entechbot/yc-orgs-db` (Settings → Secrets and variables → Actions). Get it in Supabase dashboard → Project Settings → API Keys. |
| Supabase **personal access token** (account-wide, keep it off CI) | `apply_schema.py`, ad-hoc SQL | env var `SUPABASE_ACCESS_TOKEN`. On the entechbot machine it is the GeckIt secret `supabase-token`. |
| UI login | people | Supabase Auth users, e.g. `admin@entechsolutions.com` (Authentication → Users). |
| `web/config.js` | UI | Project URL + **publishable** key. These are public by design; RLS protects the data. |

To rotate the sync key, create a new secret key in the Supabase dashboard and run
`gh secret set SUPABASE_SECRET_KEY -R entechbot/yc-orgs-db` (it reads the value from stdin). Then delete the old key.

## Keeping the data current (daily sync)

`.github/workflows/sync.yml` runs `scripts/import_companies.py` **every day at 04:17 UTC** on GitHub Actions.

- **Run it manually:** GitHub → Actions → *Sync YC companies* → *Run workflow*, or
  `gh workflow run sync.yml -R entechbot/yc-orgs-db`. Logs are under the Actions tab.
- **Outreach fields** (`contact_status`, `owner`, `contact_name`, `contact_email`, `last_contacted_at`,
  `next_follow_up`, `notes`) are never sent by the import, so they are never overwritten.
- **Companies that disappear from yc-oss are never deleted.** The import sets `removed_from_source_at` and
  keeps the row and its outreach data. If the company reappears, the timestamp is cleared. In the UI, tick
  *No longer in YC data* to list them. The company view also shows the date.
- **Safety:** if the downloaded dataset has fewer than 80% of the companies currently in the DB, the run aborts
  before changing anything, and the job fails, so GitHub emails the repo owner.
- **Slug clash:** if a manually added company has the same slug as a new YC company, the manual row is renamed
  to `<slug>-manual-<id>` and a warning is logged. Merge the two by hand.
- GitHub disables scheduled workflows in a repo after 60 days without commits. If that happens, re-enable it on
  the Actions tab. The daily API traffic should also keep the free Supabase project from pausing for inactivity.

## Running the import by hand

```bash
export SUPABASE_SECRET_KEY=...            # project secret key, see Credentials
python3 scripts/import_companies.py       # downloads all.json and upserts it
# or from a local copy:  python3 scripts/import_companies.py --file data/all.json
```

Schema changes: edit `supabase/schema.sql`, then run `SUPABASE_ACCESS_TOKEN=... python3 scripts/apply_schema.py`.
It is idempotent and uses the Management API SQL endpoint, so no database password is needed.

Requirements: Python 3.9+ and `curl`. No pip packages are needed.

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
