"""Load a hiring-signal lead list (treg-export outputs/hiring-signal-leads-<date>.csv) into the DB.

Every company in the file gets the tags from --tags (default 'hiring-signal') in `lead_tags` (never touched by the import,
unlike the YC `tags`); tags are only ever added, never removed.
- Matched by the optional CSV column `db id` (the companies.id, e.g. for YC companies found by slug), else by domain against the host of `website` (www. ignored), so a company already in the DB (YC or earlier load) is
  enriched, never duplicated: it keeps its `source`, gets the tag added, and its `hiring_signal_*` columns are filled only
  where they are empty. If one already holds a different value, the new value is appended to `notes` instead
  ("[hiring signal <date>] <field>: <value>"). Nothing is ever deleted or overwritten.
- Companies not in the DB are inserted as non-YC rows: source = 'hiring-signal', id from the manual sequence,
  name / slug / website from the file (slug made unique; the import renames it if YC later takes it).
Re-running the same file is harmless (nothing left to fill). `--dry-run` shows the plan without writing.

Env: SUPABASE_ACCESS_TOKEN (see scripts/supa.py)

  python3 scripts/load_hiring_signal.py [--dry-run] [--source-label 'treg hiring signal 2026-11-19']
      [--tags hiring-signal,niraj-1-campaign] hiring-signal-leads-2026-11-19.csv
"""
import argparse
import csv
import json
import pathlib
import re
import secrets
import sys
import urllib.parse

import supa

DEFAULT_TAGS = "hiring-signal"
SOURCE = "hiring-signal"
FIELDS = ["hiring_signal_fit", "hiring_signal_fit_reason", "hiring_signal_role", "hiring_signal_posting_url",
          "hiring_signal_posted_at", "hiring_signal_evidence", "hiring_signal_headcount", "hiring_signal_owner",
          "hiring_signal_source", "hiring_signal_checked_at", "hiring_signal_note"]
TYPES = {"hiring_signal_posted_at": "date", "hiring_signal_checked_at": "date"}


def host(url):
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    h = (urllib.parse.urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h or None


def slugify(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-") or "company"


def to_row(r, label, checked):
    note = "; ".join(f"{k}: {v}" for k, v in (
        ("Role family", r.get("role family")), ("Posting location", r.get("posting location")),
        ("Tools/systems named", r.get("tools/systems named")),
        ("Suggested contact (campaign rules)", r.get("suggested contact (campaign rules: no finance/sales/marketing)")),
        ("Verified email", r.get("verified email")), ("Notes", r.get("notes"))) if v)
    return {"hiring_signal_fit": r["fit"] or None, "hiring_signal_fit_reason": r["fit reason"] or None,
            "hiring_signal_role": r["role title"] or None, "hiring_signal_posting_url": r["posting URL"] or None,
            "hiring_signal_posted_at": r["posted date"] or None, "hiring_signal_evidence": r["exact quote (job post)"] or None,
            "hiring_signal_headcount": r["headcount (Crustdata range)"] or None,
            "hiring_signal_owner": r["likely role owner (Apollo, unverified, last name masked)"] or None,
            "hiring_signal_source": label, "hiring_signal_checked_at": checked, "hiring_signal_note": note or None}


def dq(payload):
    tag = "j" + secrets.token_hex(8)  # dollar-quote tag that cannot occur in the payload
    while f"${tag}$" in payload:
        tag = "j" + secrets.token_hex(8)
    return f"${tag}${payload}${tag}$::jsonb"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=pathlib.Path)
    ap.add_argument("--source-label", help="value for hiring_signal_source (default: 'treg hiring signal <date in file name>')")
    ap.add_argument("--tags", default=DEFAULT_TAGS, help="comma list of lead_tags to add (default: hiring-signal)")
    ap.add_argument("--dry-run", action="store_true", help="match and report, write nothing")
    args = ap.parse_args()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    if not tags or any(not re.fullmatch(r"[a-z0-9][a-z0-9-]*", t) for t in tags):
        sys.exit("--tags: lower-case letters, digits and dashes only")

    checked = re.search(r"(\d{4}-\d{2}-\d{2})", args.file.name).group(1)
    label = args.source_label or f"treg hiring signal {checked}"
    recs = list(csv.DictReader(args.file.open(newline="")))

    cols = ", ".join(["id", "slug", "name", "website", "source", "notes", "lead_tags", *FIELDS])
    companies = supa.query(f"select {cols} from public.companies")
    slugs = {c["slug"] for c in companies}
    by_id = {str(c["id"]): c for c in companies}
    by_host = {}
    for c in companies:
        if host(c["website"]):
            by_host.setdefault(host(c["website"]), []).append(c)

    inserts, updates, skipped, ambiguous = [], [], [], []
    for r in recs:
        row = to_row(r, label, checked)
        d = host(r["website"])
        hits = [by_id[r["db id"].strip()]] if (r.get("db id") or "").strip() in by_id else by_host.get(d, [])
        if len(hits) > 1:
            ambiguous.append(f"{r['company']} ({d}) -> " + ", ".join(f"{h['id']} {h['name']}" for h in hits))
            continue
        if not hits:
            slug = slugify(r["company"])
            if slug in slugs:
                slug = f"{slug}-{slugify(d)}"
            slugs.add(slug)
            inserts.append(dict(row, slug=slug, name=r["company"], website="https://" + d))
            continue
        c = hits[0]
        fill, conflicts = {}, []
        for f in FIELDS:
            old, new = c.get(f), row[f]
            if new is None or str(old or "") == str(new):
                continue
            if old in (None, ""):
                fill[f] = new
            elif f not in ("hiring_signal_checked_at", "hiring_signal_source"):
                conflicts.append(f"[hiring signal {checked}] {f}: {new}")
        add_tags = [t for t in tags if t not in (c.get("lead_tags") or [])]
        if not fill and not conflicts and not add_tags:
            skipped.append(f"{c['name']} ({d}): already loaded, nothing to add")
            continue
        updates.append({"id": c["id"], "_name": c["name"], "_source": c["source"], "fill": fill,
                        "notes_append": "\n".join(conflicts) or None, "add_tags": ",".join(add_tags) or None})

    for i in inserts:
        print(f"  INSERT  {i['hiring_signal_fit'] or '-':<8} {i['name']} ({host(i['website'])}) slug={i['slug']}")
    for u in updates:
        print(f"  UPDATE  {u['_name']} [{u['_source']}] fill={sorted(u['fill'])} tags+={u['add_tags'] or '-'} "
              f"notes+={'yes' if u['notes_append'] else 'no'}")
    for s in skipped:
        print("  SKIP   ", s)
    for a in ambiguous:
        print("  AMBIGUOUS (skipped):", a)

    n_ins = n_upd = 0
    if not args.dry_run and inserts:
        payload = json.dumps([{k: i[k] for k in ["slug", "name", "website", *FIELDS]} for i in inserts])
        coldefs = ", ".join(["slug text", "name text", "website text"] + [f"{f} {TYPES.get(f, 'text')}" for f in FIELDS])
        names = ", ".join(["slug", "name", "website", *FIELDS])
        res = supa.query(f"""
            insert into public.companies (source, lead_tags, {names})
            select '{SOURCE}', array{json.dumps(tags).replace('"', "'")}, {', '.join('v.' + n.strip() for n in names.split(','))}
            from jsonb_to_recordset({dq(payload)}) as v({coldefs})
            returning id""")
        n_ins = len(res or [])
    if not args.dry_run and updates:
        payload = json.dumps([{"id": u["id"], "notes_append": u["notes_append"], "add_tags": u["add_tags"],
                               **{f: u["fill"].get(f) for f in FIELDS}} for u in updates])
        coldefs = ", ".join(["id bigint", "notes_append text", "add_tags text"] + [f"{f} {TYPES.get(f, 'text')}" for f in FIELDS])
        sets = ", ".join(f"{f} = coalesce(nullif(c.{f}::text, '')::{TYPES.get(f, 'text')}, v.{f})" for f in FIELDS)
        res = supa.query(f"""
            update public.companies c set {sets},
              lead_tags = c.lead_tags || array(select t from unnest(string_to_array(coalesce(v.add_tags, ''), ',')) t
                                               where t <> '' and not t = any(c.lead_tags)),
              notes = case when v.notes_append is null then c.notes
                           when coalesce(c.notes, '') = '' then v.notes_append
                           else c.notes || E'\\n' || v.notes_append end
            from jsonb_to_recordset({dq(payload)}) as v({coldefs})
            where c.id = v.id
            returning c.id""")
        n_upd = len(res or [])
    print(f"file: {args.file.name}  rows: {len(recs)}  insert: {len(inserts)}  update: {len(updates)}  "
          f"skipped: {len(skipped)}  ambiguous: {len(ambiguous)}" + (" (dry run)" if args.dry_run else
                                                                   f"  -> inserted {n_ins}, updated {n_upd}"))
    if not args.dry_run and (n_ins != len(inserts) or n_upd != len(updates)):
        sys.exit("ERROR: not every planned row was written")


if __name__ == "__main__":
    main()
