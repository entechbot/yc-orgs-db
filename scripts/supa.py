"""Minimal Supabase Management API client (Python stdlib + curl).

Env:
  SUPABASE_ACCESS_TOKEN  personal access token (https://supabase.com/dashboard/account/tokens)
  SUPABASE_PROJECT_REF   project ref, defaults to the YC-Leads project
"""
import json
import os
import subprocess
import sys
import time

API = "https://api.supabase.com/v1"
PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "swgepccnutjowghlgtnc")


def _token():
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if not token:
        sys.exit("SUPABASE_ACCESS_TOKEN is not set")
    return token


def request(method, path, body=None, retries=3):
    # curl rather than urllib: works through HTTP(S) proxies that answer with HTTP/2.
    args = ["curl", "-sS", "--max-time", "180", "-X", method, "-w", "\\n%{http_code}",
            "-H", "Authorization: Bearer " + _token(),
            "-H", "Content-Type: application/json", "-H", "Connection: close",
            API + path]
    data = None
    if body is not None:
        args += ["--data-binary", "@-"]
        data = json.dumps(body).encode()
    for attempt in range(retries):
        out = subprocess.run(args, input=data, capture_output=True)
        text = out.stdout.decode(errors="replace")
        raw, _, code = text.rpartition("\n")
        if out.returncode == 0 and code.startswith("2"):
            return json.loads(raw) if raw.strip() else None
        retryable = out.returncode != 0 or code in ("429", "502", "503", "504")
        if retryable and attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
            continue
        raise RuntimeError(f"{method} {path} -> HTTP {code or '?'}: {(raw or out.stderr.decode())[:500]}")


def query(sql):
    """Run SQL on the project's database (as postgres) and return rows."""
    return request("POST", f"/projects/{PROJECT_REF}/database/query", {"query": sql})
