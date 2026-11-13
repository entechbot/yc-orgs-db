/* YC Companies outreach UI: plain JS + supabase-js, no build step. */
const { supabaseUrl, supabaseKey } = window.APP_CONFIG;
const db = window.supabase.createClient(supabaseUrl, supabaseKey);

const PAGE_SIZE = 50;
const CONTACT_STATUSES = [
  "not_contacted", "queued", "contacted", "replied", "interested", "not_interested", "customer", "do_not_contact",
];
const LIST_COLUMNS = "id,slug,name,one_liner,logo_url,batch,status,industry,team_size,all_locations,contact_status,owner";
const CORE_FIELDS = ["name", "slug", "website", "batch", "status", "industry", "team_size", "all_locations", "one_liner"];
const OUTREACH_FIELDS = ["contact_status", "owner", "contact_name", "contact_email", "last_contacted_at", "next_follow_up", "notes"];

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const label = (s) => String(s).replace(/_/g, " ");

let page = 0;
let total = 0;
let current = null; // company open in the dialog (null = new)
let facetsLoaded = false;

// ---------- auth ----------
const signupMode = () => location.hash === "#signup";

async function showView() {
  const { data: { session } } = await db.auth.getSession();
  $("#login-view").hidden = !!session;
  $("#app-view").hidden = !session;
  if (session) {
    $("#user-email").textContent = session.user.email;
    if (!facetsLoaded) await loadFacets();
    await load();
  } else {
    $("#login-submit").textContent = signupMode() ? "Create account" : "Sign in";
    $("#login-mode-text").textContent = signupMode() ? "Create an account (only works while sign-ups are enabled)" : "Sign in to continue";
  }
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  const email = $("#login-email").value.trim();
  const password = $("#login-password").value;
  const { error } = signupMode()
    ? await db.auth.signUp({ email, password })
    : await db.auth.signInWithPassword({ email, password });
  if (error) { $("#login-error").textContent = error.message; return; }
  $("#login-password").value = "";
  if (signupMode()) history.replaceState(null, "", location.pathname);
  showView();
});

$("#logout-btn").addEventListener("click", async () => { await db.auth.signOut(); facetsLoaded = false; showView(); });

// ---------- filters ----------
function fillSelect(sel, values, fmt = (v) => v) {
  const first = sel.options[0];
  sel.replaceChildren(first, ...values.map((v) => new Option(fmt(v), v.value ?? v)));
}

async function facet(name, order) {
  const { data, error } = await db.from("company_facets").select("value,sort,n").eq("facet", name)
    .order(order, { ascending: order === "value" }).limit(1000);
  if (error) throw error;
  return data;
}

async function loadFacets() {
  const [batches, statuses, industries, regions, tags] = await Promise.all([
    facet("batch", "sort"), facet("status", "n"), facet("industry", "n"), facet("region", "n"), facet("tag", "value"),
  ]);
  const withCount = (f) => `${f.value} (${f.n})`;
  fillSelect($("#f-batch"), batches, withCount);
  fillSelect($("#f-status"), statuses, withCount);
  fillSelect($("#f-industry"), industries, withCount);
  fillSelect($("#f-region"), regions, withCount);
  $("#tag-options").replaceChildren(...tags.map((t) => new Option(t.value)));
  fillSelect($("#f-contact"), CONTACT_STATUSES, label);
  $("#d-contact-status").replaceChildren(...CONTACT_STATUSES.map((s) => new Option(label(s), s)));
  facetsLoaded = true;
}

function applyFilters(q) {
  // Characters that would break PostgREST's or=(...) syntax are dropped from the search text.
  const search = $("#f-search").value.trim().replace(/[,()*%\\]/g, " ").trim();
  if (search) {
    const p = `*${search}*`;
    q = q.or(`name.ilike.${p},one_liner.ilike.${p},website.ilike.${p},slug.ilike.${p},long_description.ilike.${p}`);
  }
  const v = (id) => $(id).value.trim();
  if (v("#f-batch")) q = q.eq("batch", v("#f-batch"));
  if (v("#f-status")) q = q.eq("status", v("#f-status"));
  if (v("#f-industry")) q = q.eq("industry", v("#f-industry"));
  if (v("#f-region")) q = q.contains("regions", [v("#f-region")]);
  if (v("#f-tag")) q = q.contains("tags", [v("#f-tag")]);
  if (v("#f-contact")) q = q.eq("contact_status", v("#f-contact"));
  if (v("#f-owner")) q = q.ilike("owner", `%${v("#f-owner")}%`);
  if ($("#f-hiring").checked) q = q.eq("is_hiring", true);
  if ($("#f-removed").checked) q = q.not("removed_from_source_at", "is", null);
  const [col, dir] = $("#f-sort").value.split(".");
  return q.order(col, { ascending: dir === "asc", nullsFirst: false }).order("id");
}

// ---------- list ----------
async function load() {
  const from = page * PAGE_SIZE;
  const { data, count, error } = await applyFilters(db.from("companies").select(LIST_COLUMNS, { count: "exact" }))
    .range(from, from + PAGE_SIZE - 1);
  if (error) { alert(error.message); return; }
  total = count ?? 0;
  $("#total").textContent = `${total.toLocaleString()} ${total === 1 ? "company" : "companies"}`;
  $("#page-info").textContent = total ? `${from + 1}–${Math.min(from + PAGE_SIZE, total)} of ${total.toLocaleString()}` : "No matches";
  $("#prev-btn").disabled = page === 0;
  $("#next-btn").disabled = from + PAGE_SIZE >= total;
  $("#results tbody").innerHTML = data.map((c) => `
    <tr data-id="${c.id}">
      <td>${c.logo_url ? `<img src="${esc(c.logo_url)}" alt="" loading="lazy">` : ""}</td>
      <td><a href="#" class="open-company"><strong>${esc(c.name)}</strong></a><div class="one-liner">${esc(c.one_liner)}</div></td>
      <td>${esc(c.batch)}</td><td>${esc(c.status)}</td><td>${esc(c.industry)}</td>
      <td>${c.team_size ?? ""}</td><td>${esc(c.all_locations)}</td>
      <td><span class="pill ${esc(c.contact_status)}">${esc(label(c.contact_status))}</span></td>
      <td>${esc(c.owner)}</td>
    </tr>`).join("");
}

let debounce;
$("#filters").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => { page = 0; load(); }, 250); });
$("#filters").addEventListener("submit", (e) => e.preventDefault());
$("#reset-btn").addEventListener("click", () => { $("#filters").reset(); page = 0; load(); });
$("#prev-btn").addEventListener("click", () => { page--; load(); });
$("#next-btn").addEventListener("click", () => { page++; load(); });
// Whole row is clickable; the name is a real link so it also works from the keyboard.
$("#results tbody").addEventListener("click", (e) => {
  const tr = e.target.closest("tr");
  if (!tr) return;
  e.preventDefault();
  openCompany(Number(tr.dataset.id));
});

// ---------- detail / edit ----------
const form = $("#detail-form");

async function openCompany(id) {
  const { data, error } = await db.from("companies").select("*").eq("id", id).single();
  if (error) { alert(error.message); return; }
  showDetail(data);
}

function showDetail(c) {
  current = c;
  form.reset();
  $("#save-msg").textContent = "";
  const isNew = !c;
  const imported = c?.source === "yc-oss";
  $("#d-title").textContent = isNew ? "New company" : c.name;
  $("#d-logo").hidden = !c?.logo_url;
  if (c?.logo_url) $("#d-logo").src = c.logo_url;
  $("#d-links").innerHTML = isNew ? "" : [
    c.website && `<a href="${esc(c.website)}" target="_blank" rel="noopener">${esc(c.website)}</a>`,
    c.yc_url && `<a href="${esc(c.yc_url)}" target="_blank" rel="noopener">YC profile</a>`,
    `source: ${esc(c.source)}`,
    c.removed_from_source_at && `<b>no longer in YC data since ${esc(c.removed_from_source_at.slice(0, 10))}</b>`,
  ].filter(Boolean).join(" · ");
  $("#d-info").innerHTML = isNew ? "" : `
    <div>${[c.batch, c.status, c.stage, c.industry, c.team_size != null && `${c.team_size} people`, c.is_hiring && "hiring"].filter(Boolean).map(esc).join(" · ")}</div>
    ${c.subindustry ? `<div><b>Sub-industry:</b> ${esc(c.subindustry)}</div>` : ""}
    ${c.all_locations ? `<div><b>Location:</b> ${esc(c.all_locations)}</div>` : ""}
    ${c.regions?.length ? `<div><b>Regions:</b> ${c.regions.map(esc).join(", ")}</div>` : ""}
    ${c.tags?.length ? `<div><b>Tags:</b> ${c.tags.map((t) => `<span class="pill">${esc(t)}</span>`).join(" ")}</div>` : ""}
    ${c.long_description ? `<div class="desc">${esc(c.long_description)}</div>` : ""}`;

  for (const f of [...CORE_FIELDS, ...OUTREACH_FIELDS]) {
    const el = form.elements[f];
    el.value = c?.[f] ?? (f === "contact_status" ? "not_contacted" : "");
  }
  // Imported rows: company fields come from yc-oss and are overwritten by the next import.
  $("#core-fields").disabled = imported;
  $("#core-fields legend").textContent = imported ? "Company (from YC data, read-only)" : "Company";
  $("#delete-btn").hidden = isNew;
  $("#detail").showModal();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fields = current?.source === "yc-oss" ? OUTREACH_FIELDS : [...CORE_FIELDS, ...OUTREACH_FIELDS];
  const row = {};
  for (const f of fields) {
    const v = form.elements[f].value.trim();
    row[f] = v === "" ? null : f === "team_size" ? Number(v) : v;
  }
  row.contact_status ??= "not_contacted";
  $("#save-btn").disabled = true;
  const res = current
    ? await db.from("companies").update(row).eq("id", current.id).select().single()
    : await db.from("companies").insert(row).select().single();
  $("#save-btn").disabled = false;
  if (res.error) { $("#save-msg").textContent = res.error.message; return; }
  $("#detail").close();
  load();
});

$("#delete-btn").addEventListener("click", async () => {
  if (!current || !confirm(`Delete ${current.name}? Imported companies come back on the next import (without outreach data).`)) return;
  const { error } = await db.from("companies").delete().eq("id", current.id);
  if (error) { $("#save-msg").textContent = error.message; return; }
  $("#detail").close();
  load();
});

$("#cancel-btn").addEventListener("click", () => $("#detail").close());
$("#close-btn").addEventListener("click", () => $("#detail").close());
$("#add-btn").addEventListener("click", () => showDetail(null));
form.elements.name.addEventListener("input", () => {
  if (!current) form.elements.slug.value = form.elements.name.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
});

// ---------- CSV export of the current filter ----------
$("#export-btn").addEventListener("click", async () => {
  const cols = ["id", "name", "slug", "website", "one_liner", "batch", "status", "industry", "team_size", "all_locations", "yc_url", ...OUTREACH_FIELDS];
  const rows = [];
  for (let from = 0; ; from += 1000) {
    const { data, error } = await applyFilters(db.from("companies").select(cols.join(","))).range(from, from + 999);
    if (error) { alert(error.message); return; }
    rows.push(...data);
    if (data.length < 1000) break;
  }
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\n");
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "yc-companies.csv",
  });
  a.click();
  URL.revokeObjectURL(a.href);
});

window.addEventListener("hashchange", showView);
db.auth.onAuthStateChange((event) => { if (event === "SIGNED_OUT") showView(); });
showView();
