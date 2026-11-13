"""Import / refresh all YC companies from yc-oss/api into Supabase.

Idempotent upsert keyed on the YC company id: source columns are overwritten,
marketing columns (contact_status, owner, notes, ...) are never touched.

  python3 scripts/import_companies.py [--file all.json] [--batch-size 500]
"""
import argparse
import json
import secrets
import subprocess
from datetime import datetime, timezone

import supa

SOURCE_URL = "https://yc-oss.github.io/api/companies/all.json"
BATCH_SIZE = 500


def load(path):
    if path:
        with open(path) as f:
            return json.load(f)
    out = subprocess.run(["curl", "-sSfL", "--max-time", "300", SOURCE_URL], capture_output=True, check=True)
    return json.loads(out.stdout)


def to_row(c):
    launched = c.get("launched_at")
    return {
        "id": c["id"],
        "slug": c["slug"],
        "name": c.get("name") or c["slug"],
        "former_names": c.get("former_names") or [],
        "website": c.get("website") or None,
        "one_liner": c.get("one_liner") or None,
        "long_description": c.get("long_description") or None,
        "batch": c.get("batch") or None,
        "status": c.get("status") or None,
        "stage": c.get("stage") or None,
        "industry": c.get("industry") or None,
        "subindustry": c.get("subindustry") or None,
        "industries": c.get("industries") or [],
        "tags": c.get("tags") or [],
        "regions": c.get("regions") or [],
        "all_locations": c.get("all_locations") or None,
        "team_size": c.get("team_size"),
        "launched_at": datetime.fromtimestamp(launched, timezone.utc).isoformat() if launched else None,
        "is_hiring": c.get("isHiring"),
        "nonprofit": c.get("nonprofit"),
        "top_company": c.get("top_company"),
        "logo_url": c.get("small_logo_thumb_url") or None,
        "yc_url": c.get("url") or None,
    }


SOURCE_COLS = list(to_row({"id": 0, "slug": ""}).keys())
UPDATE_COLS = [c for c in SOURCE_COLS if c != "id"]

# jsonb_to_recordset column definitions
COL_TYPES = {
    "id": "bigint", "team_size": "integer", "launched_at": "timestamptz",
    "is_hiring": "boolean", "nonprofit": "boolean", "top_company": "boolean",
    "former_names": "text[]", "industries": "text[]", "tags": "text[]", "regions": "text[]",
}


def upsert_sql(rows, run_ts):
    payload = json.dumps(rows)
    tag = "yc" + secrets.token_hex(6)
    assert f"${tag}$" not in payload
    # Arrays arrive as JSON arrays; convert them to text[] explicitly.
    defs = ", ".join(f"{c} {'jsonb' if COL_TYPES.get(c) == 'text[]' else COL_TYPES.get(c, 'text')}" for c in SOURCE_COLS)
    select = ", ".join(
        f"coalesce(array(select jsonb_array_elements_text(r.{c})), '{{}}')" if COL_TYPES.get(c) == "text[]" else f"r.{c}"
        for c in SOURCE_COLS
    )
    sets = ", ".join(f"{c} = excluded.{c}" for c in UPDATE_COLS)
    return f"""
insert into public.companies ({", ".join(SOURCE_COLS)}, source, synced_at)
select {select}, 'yc-oss', '{run_ts}'::timestamptz
from jsonb_to_recordset(${tag}${payload}${tag}$::jsonb) as r({defs})
on conflict (id) do update set {sets}, source = 'yc-oss', synced_at = excluded.synced_at;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="local copy of all.json instead of downloading")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = ap.parse_args()

    companies = load(args.file)
    rows = [to_row(c) for c in companies]
    run_ts = datetime.now(timezone.utc).isoformat()
    print(f"source: {len(rows)} companies")

    for i in range(0, len(rows), args.batch_size):
        supa.query(upsert_sql(rows[i:i + args.batch_size], run_ts))
        print(f"  upserted {min(i + args.batch_size, len(rows))}/{len(rows)}")

    stats = supa.query(f"""
select count(*) as total,
       count(*) filter (where source = 'yc-oss') as from_yc,
       count(*) filter (where source = 'yc-oss' and synced_at < '{run_ts}'::timestamptz) as missing_from_source
from public.companies""")[0]
    print(f"db: total={stats['total']} yc-oss={stats['from_yc']} "
          f"no longer in source={stats['missing_from_source']}")


if __name__ == "__main__":
    main()
