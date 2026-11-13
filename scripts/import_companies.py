"""Import / refresh all YC companies from yc-oss/api into Supabase.

Idempotent upsert keyed on the YC company id (Supabase REST API):
- YC columns are overwritten; outreach columns (contact_status, owner, notes, ...) are never sent, so never touched.
- Companies no longer in the source are NOT deleted: they get `removed_from_source_at` set
  (cleared again if they reappear). Rows and their outreach data stay.
- A manual row whose slug collides with a new YC company is renamed to `<slug>-manual-<id>` (with a warning).
- Aborts before changing anything if the source looks truncated (< 80% of the companies currently in the DB).

Env:
  SUPABASE_URL         https://<project-ref>.supabase.co (defaults to the YC-Leads project)
  SUPABASE_SECRET_KEY  project secret API key (sb_secret_...), bypasses RLS

  python3 scripts/import_companies.py [--file all.json] [--batch-size 500]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone

SOURCE_URL = "https://yc-oss.github.io/api/companies/all.json"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://swgepccnutjowghlgtnc.supabase.co")
BATCH_SIZE = 500
MIN_SOURCE_RATIO = 0.8


def load(path):
    if path:
        with open(path) as f:
            return json.load(f)
    out = subprocess.run(["curl", "-sSfL", "--retry", "3", "--max-time", "300", SOURCE_URL], capture_output=True, check=True)
    return json.loads(out.stdout)


def rest(method, path, body=None, prefer="return=minimal", retries=3):
    """Call Supabase REST (PostgREST). Returns (json_body, content_range)."""
    key = os.environ.get("SUPABASE_SECRET_KEY") or sys.exit("SUPABASE_SECRET_KEY is not set")
    # Key goes in via a curl config on stdin so it never shows up in the process list.
    config = f'header = "apikey: {key}"\nheader = "Authorization: Bearer {key}"\n'
    args = ["curl", "-sS", "--max-time", "180", "-X", method, "-K", "-", "-D", "-",
            "-H", "Content-Type: application/json", "-H", f"Prefer: {prefer}", SUPABASE_URL + "/rest/v1/" + path]
    if body is not None:
        args += ["--data-binary", "@" + _tmp_json(body)]
    for attempt in range(retries):
        out = subprocess.run(args, input=config.encode(), capture_output=True)
        head, _, raw = out.stdout.decode(errors="replace").partition("\r\n\r\n")
        while head.startswith("HTTP/") and " 100" in head.split("\r\n")[0]:  # skip "100 Continue"
            head, _, raw = raw.partition("\r\n\r\n")
        status = head.split("\r\n")[0].split(" ")[1] if head.startswith("HTTP/") else "?"
        if out.returncode == 0 and status.startswith("2"):
            crange = next((l.split(":", 1)[1].strip() for l in head.split("\r\n") if l.lower().startswith("content-range:")), None)
            return (json.loads(raw) if raw.strip() else None), crange
        if attempt < retries - 1 and (out.returncode != 0 or status in ("429", "500", "502", "503", "504")):
            time.sleep(3 * (attempt + 1))
            continue
        raise RuntimeError(f"{method} {path[:80]} -> HTTP {status}: {(raw or out.stderr.decode())[:500]}")


_tmp_path = None


def _tmp_json(body):
    # Request bodies go through a temp file: a 500-row batch is too big for argv.
    global _tmp_path
    if _tmp_path is None:
        fd, _tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
    with open(_tmp_path, "w") as f:
        json.dump(body, f)
    return _tmp_path


def count(filters):
    _, crange = rest("GET", f"companies?select=id&limit=1&{filters}", prefer="count=exact")
    return int(crange.split("/")[1])


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


def rename_colliding_manual_rows(rows):
    manual, _ = rest("GET", "companies?select=id,slug&source=neq.yc-oss", prefer="return=representation")
    incoming = {r["slug"]: r["id"] for r in rows}
    for m in manual or []:
        if m["slug"] in incoming and incoming[m["slug"]] != m["id"]:
            new_slug = f"{m['slug']}-manual-{m['id']}"
            print(f"WARNING: manual company {m['id']} uses slug '{m['slug']}' now taken by YC company "
                  f"{incoming[m['slug']]}; renamed to '{new_slug}' (merge them by hand if they are the same)")
            rest("PATCH", f"companies?id=eq.{m['id']}", {"slug": new_slug})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="local copy of all.json instead of downloading")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = ap.parse_args()

    rows = [to_row(c) for c in load(args.file)]
    run_ts = datetime.now(timezone.utc).isoformat()
    current = count("source=eq.yc-oss&removed_from_source_at=is.null")
    print(f"source: {len(rows)} companies; db currently has {current} active yc-oss rows")
    if len(rows) < MIN_SOURCE_RATIO * current:
        sys.exit(f"ABORT: source has only {len(rows)} companies vs {current} in DB - looks truncated, nothing changed")

    rename_colliding_manual_rows(rows)
    for r in rows:
        r.update(source="yc-oss", synced_at=run_ts, removed_from_source_at=None)
    for i in range(0, len(rows), args.batch_size):
        rest("POST", "companies?on_conflict=id", rows[i:i + args.batch_size],
             prefer="resolution=merge-duplicates,return=minimal")
        print(f"  upserted {min(i + args.batch_size, len(rows))}/{len(rows)}")

    ts = urllib.parse.quote(run_ts)
    removed, _ = rest("PATCH", f"companies?source=eq.yc-oss&synced_at=lt.{ts}&removed_from_source_at=is.null&select=id,name",
                      {"removed_from_source_at": run_ts}, prefer="return=representation")
    for r in removed or []:
        print(f"  no longer in source (kept, marked removed): {r['id']} {r['name']}")

    print(f"db: total={count('id=not.is.null')} yc-oss={count('source=eq.yc-oss')} "
          f"in source={count('source=eq.yc-oss&removed_from_source_at=is.null')} "
          f"removed from source={count('removed_from_source_at=not.is.null')} manual={count('source=neq.yc-oss')}")
    if _tmp_path:
        os.remove(_tmp_path)


if __name__ == "__main__":
    main()
