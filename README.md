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
| NetSuite check (set by `load_netsuite_results.py`, never touched by import) | `netsuite_status` (unknown, confirmed, likely, ruled_out), `netsuite_strength` (strong, medium, weak), `netsuite_evidence` (quotes + URLs, or the DNS record), `netsuite_checked_at` (date of the result file), `netsuite_note` (caveats, or why it was ruled out) |
| Lead tags (never touched by import) | `lead_tags[]`: our own labels, e.g. `hiring-signal`. YC's `tags[]` can't be used for this because the import overwrites them. |
| Hiring signal (set by `load_hiring_signal.py`, never touched by import) | `hiring_signal_fit` (strong, partial, weak), `hiring_signal_fit_reason`, `hiring_signal_role`, `hiring_signal_posting_url`, `hiring_signal_posted_at`, `hiring_signal_evidence` (exact quote), `hiring_signal_headcount` (range, e.g. 51-200), `hiring_signal_owner` (likely owner, unverified), `hiring_signal_source`, `hiring_signal_checked_at`, `hiring_signal_note` |
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
  `next_follow_up`, `notes`) and the **NetSuite fields** (`netsuite_*`) are never sent by the import, so they are
  never overwritten. The script asserts this before it uploads anything.
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

## NetSuite check results

The NetSuite campaign repo (`treg-export`, `tools/lead_pipeline/out/yc_netsuite_free_<date>.json`) produces free
NetSuite checks of the YC pool. Load one or more result files with:

```bash
SUPABASE_ACCESS_TOKEN=... python3 scripts/load_netsuite_results.py [--dry-run] path/to/yc_netsuite_free_*.json
# on the entechbot machine:
geckit secrets run --env SUPABASE_ACCESS_TOKEN=secret:supabase-token -- python3 scripts/load_netsuite_results.py FILE...
```

- **Mapping:** `confirmed[]` → `confirmed`, with the file's strength, its evidence quotes/URLs and caveats as the note.
  `dropped_borderline[]` with a strong/medium signal (dropped for size/ICP, not for the evidence) → `likely`.
  Those with a weak or vendor signal → `ruled_out`, and the reason goes in the note. Wrong-company matches
  (signal `n/a`) say nothing about the YC company, so they are skipped.
- **Matching:** `slug` if the record has one, else `domain` against the host of `website` (`www.` ignored). Unmatched
  and ambiguous records are listed and skipped.
- **Order:** files are applied by the date in the file name (else `created`), so later files win per company.
  Companies that a file does not mention keep their values. Only the `netsuite_*` columns are written.
- Re-running the same file is harmless. `--dry-run` shows the matches without writing.

## Hiring-signal leads (non-YC companies too)

Companies hiring GTM / automation / forward deployed engineers, from the NetSuite campaign repo
(`treg-export/outputs/hiring-signal-leads-<date>.csv`). Load a file with:

```bash
geckit secrets run --env SUPABASE_ACCESS_TOKEN=secret:supabase-token -- python3 scripts/load_hiring_signal.py [--dry-run] [--tags hiring-signal,niraj-1-campaign] [--source-label '...'] FILE.csv
```

- Every company in the file gets the tags from `--tags` (default **`hiring-signal`**) in `lead_tags`. Niraj's campaign uses
  `--tags hiring-signal,niraj-1-campaign`; list it with `select * from public.companies where 'niraj-1-campaign' = any(lead_tags);`.
  The Mon/Wed/Fri run that produces these files is `treg-export/tools/hiring_signal/RUNBOOK.md`.
- **Matching** is by the optional CSV column `db id` (the companies `id`), else by domain against the host of `website` (`www.` ignored). A company already in the DB (e.g. from YC) keeps
  its `source` and data, gets the tag added, and its `hiring_signal_*` columns are filled only where empty. A differing
  value never overwrites: it is appended to `notes` as `[hiring signal <date>] <field>: <value>`.
- **New companies** are inserted with `source = 'hiring-signal'` and an id from the manual sequence (the import treats them
  like manual rows: never overwritten, renamed only on a slug clash).
- Re-running a file is harmless (it skips what's already there). Nothing is deleted.
- Only tagged rows: `select * from companies where 'hiring-signal' = any(lead_tags);` In the UI: the *Hiring signal* filter.

## UI (`web/`)

It's plain HTML/JS with [supabase-js](https://supabase.com/docs/reference/javascript) from a CDN. There's no build step.

- Search by name, one-liner, website or description. Filter by batch, status, industry, region, tag, contact status,
  owner, hiring, NetSuite status (*confirmed or likely* = NetSuite users), NetSuite strength and hiring-signal leads (by fit). Sort and page through results, and export the current filter to CSV.
- Click a row to see the full company, including the NetSuite evidence (read-only), and edit its outreach fields. Company fields are read-only for imported rows
  (the next import would overwrite them) and editable for manual rows. You can also add and delete companies.

Run locally: `python3 -m http.server -d web 8000` and open http://localhost:8000.

Deploy: pushing to `main` (changes under `web/`) runs `.github/workflows/pages.yml`, which publishes `web/` to GitHub Pages.

### Managing users

Sign-ups are disabled. To add a teammate, open Supabase dashboard → Authentication → Users → *Add user* →
*Create new user* (tick *Auto confirm*). Alternatively, briefly enable sign-ups (Authentication → Sign In / Providers →
*Allow new users to sign up*, with *Confirm email* off), have them use https://entechbot.github.io/yc-orgs-db/#signup,
then turn sign-ups off again.
