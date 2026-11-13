"""Apply supabase/schema.sql to the project. Safe to re-run."""
import pathlib

import supa

sql = (pathlib.Path(__file__).resolve().parent.parent / "supabase" / "schema.sql").read_text()
supa.query(sql)
print("schema applied to", supa.PROJECT_REF)
