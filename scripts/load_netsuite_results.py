"""Load NetSuite check results (yc_netsuite_free_<date>.json) into the netsuite_* columns.

Each file has `confirmed[]` (name, domain, strength, evidence[{quote, role, posted, url, source}], caveats[])
and `dropped_borderline[]` (name, domain, signal, reason). Mapping:
- confirmed[]                                  -> netsuite_status = confirmed, strength from the file
- dropped_borderline[] with a strong/medium signal (dropped for size/ICP, not for the evidence)
                                               -> likely, note = why it was dropped
- dropped_borderline[] with weak / vendor signal -> ruled_out, note = reason
- dropped_borderline[] that were a wrong-company match (signal n/a) say nothing about the YC company: skipped

Companies are matched by `slug` (if a record has one), else by domain vs. the host of `website`
(www. ignored). Unmatched and ambiguous records are reported, never guessed.
Files are applied in date order (date from the file name, else `created`): later files win per company.
Companies a file does not mention keep their values. Only the netsuite_* columns are written.

Env: SUPABASE_ACCESS_TOKEN (see scripts/supa.py)

  python3 scripts/load_netsuite_results.py [--dry-run] yc_netsuite_free_2026-11-16.json [more files...]
"""
import argparse
import json
import pathlib
import re
import secrets
import sys
import urllib.parse

import supa

FIELDS = ["netsuite_status", "netsuite_strength", "netsuite_evidence", "netsuite_checked_at", "netsuite_note"]


def host(url):
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    h = (urllib.parse.urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h or None


def file_date(path, data):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return m.group(1) if m else data["created"][:10]


def fmt_evidence(items):
    out = []
    for e in items or []:
        meta = ", ".join(x for x in (e.get("role"), e.get("posted"), e.get("source")) if x)
        out.append(f"\"{e.get('quote', '').strip()}\"" + (f" ({meta})" if meta else "") + (f"\n{e['url']}" if e.get("url") else ""))
    return "\n\n".join(out) or None


def from_confirmed(c, checked):
    strength = c.get("strength") if c.get("strength") in ("strong", "medium", "weak") else None
    return {"netsuite_status": "confirmed", "netsuite_strength": strength,
            "netsuite_evidence": fmt_evidence(c.get("evidence")),
            "netsuite_checked_at": checked, "netsuite_note": "\n".join(c.get("caveats") or []) or None}


def wrong_company(c):
    return (c.get("signal") or "").strip().lower().startswith("n/a") or (c.get("reason") or "").startswith("Wrong company")


def from_borderline(c, checked):
    signal = (c.get("signal") or "").strip()
    first = re.match(r"[a-z/ -]+", signal.lower())
    word = first.group(0).strip() if first else ""
    if word.startswith("strong-ish"):
        strength = "medium"
    else:
        strength = next((s for s in ("strong", "medium", "weak") if word.startswith(s)), None)
    positive = strength in ("strong", "medium")
    return {"netsuite_status": "likely" if positive else "ruled_out", "netsuite_strength": strength,
            "netsuite_evidence": signal or None, "netsuite_checked_at": checked,
            "netsuite_note": ("Not in the confirmed list: " if positive else "") + (c.get("reason") or "").strip() or None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=pathlib.Path)
    ap.add_argument("--dry-run", action="store_true", help="match and report, write nothing")
    args = ap.parse_args()

    loaded = []
    for p in args.files:
        data = json.loads(p.read_text())
        loaded.append((file_date(p, data), p, data))
    loaded.sort(key=lambda t: (t[0], t[1].name))

    companies = supa.query("select id, slug, name, website from public.companies")
    by_slug = {c["slug"]: c for c in companies}
    by_host = {}
    for c in companies:
        if host(c["website"]):
            by_host.setdefault(host(c["website"]), []).append(c)

    updates = {}  # company id -> row; later files overwrite earlier ones
    unmatched, ambiguous, skipped = [], [], []
    for checked, path, data in loaded:
        records = [(c, from_confirmed(c, checked)) for c in data.get("confirmed") or []]
        for c in data.get("dropped_borderline") or []:
            if wrong_company(c):
                skipped.append(f"{c.get('name')} ({c.get('domain')}) [{path.name}]: {c.get('reason')}")
            else:
                records.append((c, from_borderline(c, checked)))
        for rec, row in records:
            label = f"{rec.get('name')} ({rec.get('domain')}) [{path.name}]"
            if rec.get("slug") in by_slug:
                hits = [by_slug[rec["slug"]]]
            else:
                hits = by_host.get(host(rec.get("domain")), [])
            if not hits:
                unmatched.append(label)
            elif len(hits) > 1:
                ambiguous.append(f"{label} -> " + ", ".join(f"{h['id']} {h['name']}" for h in hits))
            else:
                updates[hits[0]["id"]] = dict(row, id=hits[0]["id"], _name=hits[0]["name"])

    rows = sorted(updates.values(), key=lambda r: (r["netsuite_status"], r["_name"]))
    for r in rows:
        print(f"  {r['netsuite_status']:<10} {r['netsuite_strength'] or '-':<7} {r['_name']}")
    for u in unmatched:
        print("  UNMATCHED:", u)
    for k in skipped:
        print("  SKIPPED (wrong-company match):", k)
    for a in ambiguous:
        print("  AMBIGUOUS (skipped):", a)

    if rows and not args.dry_run:
        payload = json.dumps([{k: r[k] for k in ["id", *FIELDS]} for r in rows])
        tag = "j" + secrets.token_hex(8)  # dollar-quote tag that cannot occur in the payload
        while f"${tag}$" in payload:
            tag = "j" + secrets.token_hex(8)
        sets = ", ".join(f"{f} = v.{f}" for f in FIELDS)
        res = supa.query(f"""
            update public.companies c set {sets}
            from jsonb_to_recordset(${tag}${payload}${tag}$::jsonb)
              as v(id bigint, netsuite_status text, netsuite_strength text, netsuite_evidence text,
                   netsuite_checked_at date, netsuite_note text)
            where c.id = v.id
            returning c.id""")
        written = len(res or [])
    else:
        written = 0
    print(f"files: {', '.join(p.name for _, p, _ in loaded)}")
    print(f"matched: {len(rows)}  updated: {written}{' (dry run)' if args.dry_run else ''}  "
          f"unmatched: {len(unmatched)}  ambiguous: {len(ambiguous)}  skipped wrong-company: {len(skipped)}")
    if not args.dry_run and written != len(rows):
        sys.exit("ERROR: not every matched row was updated")


if __name__ == "__main__":
    main()
