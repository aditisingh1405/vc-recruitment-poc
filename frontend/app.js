/* Shared helpers + per-page controllers. Pages opt in via <body data-page="..."> */

const API = "";

async function api(path, options = {}) {
  const res = await fetch(API + path, options);
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return body;
}

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

const VERDICT_LABEL = {
  strong_fit: "Strong fit",
  possible_fit: "Possible fit",
  not_a_fit: "Not a fit",
};

const qs = (key) => new URLSearchParams(location.search).get(key);

function banner(el, message, kind = "error") {
  if (!el) return;
  el.className = message ? `banner ${kind}` : "banner";
  el.textContent = message || "";
}

function tags(items, className = "tag") {
  if (!items || !items.length) return "";
  return `<div class="tags">${items
    .map((s) => `<span class="${className}">${esc(s)}</span>`)
    .join("")}</div>`;
}

function jobMeta(job) {
  const bits = [job.location, job.employment_type];
  if (job.min_years_experience) bits.push(`${job.min_years_experience}+ years`);
  if (!job.is_open) bits.push("Closed");
  return bits.filter(Boolean).map(esc).join(" · ");
}

/** Warn when verdicts are coming from the keyword fallback, not an LLM. */
async function showEngineNotice(el) {
  try {
    const health = await api("/api/health");
    if (health.screening_engine === "rules") {
      banner(
        el,
        "No GROQ_API_KEY is configured, so scores come from keyword matching " +
          "rather than an LLM. Add a key to .env and restart to enable AI screening.",
        "warn"
      );
    }
  } catch (_) {
    /* the page still works if health is unreachable */
  }
}

function applicantCard(app, { recruiter = false } = {}) {
  const c = app.candidate;
  const verdict = app.verdict
    ? `<span class="verdict ${esc(app.verdict)}">${esc(
        VERDICT_LABEL[app.verdict] || app.verdict
      )}</span>`
    : "";
  const years =
    c.years_experience != null ? `${c.years_experience} yrs experience` : "experience unknown";

  const controls = recruiter
    ? `<div class="controls">
         <select data-status="${app.id}" aria-label="Application status">
           ${["new", "screened", "shortlisted", "rejected"]
             .map(
               (s) =>
                 `<option value="${s}"${s === app.status ? " selected" : ""}>${s}</option>`
             )
             .join("")}
         </select>
         <button class="ghost" data-rescreen="${app.id}">Re-screen</button>
         <span class="muted" style="font-size:12px">screened by ${esc(
           app.screened_by || "n/a"
         )}</span>
       </div>`
    : "";

  return `<div class="card applicant">
    <div class="score-col">
      <div class="score">${app.score ?? "–"}<small>/100</small></div>
    </div>
    <div class="body">
      <div class="job-head">
        <div>
          <div class="name">${esc(c.full_name)}</div>
          <div class="job-meta">${esc(c.email)} · ${esc(years)}</div>
        </div>
        ${verdict}
      </div>
      <p class="reasoning">${esc(app.reasoning || "Not screened yet.")}</p>
      ${tags(app.matched_skills, "tag hit")}
      ${tags(app.missing_skills, "tag miss")}
      ${controls}
    </div>
  </div>`;
}

/* ------------------------------------------------------------------ */
/* jobs.html -- open roles                                             */
/* ------------------------------------------------------------------ */
async function initJobs() {
  const list = document.getElementById("jobs");
  try {
    const jobs = await api("/api/jobs?open_only=true");
    if (!jobs.length) {
      list.innerHTML =
        `<div class="empty">No open roles right now.<br>` +
        `<a href="recruiter.html">Post one from the recruiter view.</a></div>`;
      return;
    }
    list.innerHTML = jobs
      .map(
        (job) => `<div class="card">
          <div class="job-head">
            <div>
              <p class="job-title">${esc(job.title)}</p>
              <div class="job-meta">${jobMeta(job)}</div>
            </div>
            <a class="button" href="apply.html?job=${job.id}">Apply</a>
          </div>
          <p class="job-desc">${esc(job.description)}</p>
          ${tags(job.required_skills)}
        </div>`
      )
      .join("");
  } catch (err) {
    list.innerHTML = "";
    banner(document.getElementById("banner"), err.message);
  }
}

/* ------------------------------------------------------------------ */
/* apply.html -- upload a resume against one job                       */
/* ------------------------------------------------------------------ */
async function initApply() {
  const jobId = qs("job");
  const summary = document.getElementById("job-summary");
  const form = document.getElementById("apply-form");
  const result = document.getElementById("result");
  const msg = document.getElementById("banner");

  if (!jobId) {
    banner(msg, "No job selected. Pick a role from the Open roles page.");
    form.style.display = "none";
    return;
  }

  try {
    const job = await api(`/api/jobs/${jobId}`);
    summary.innerHTML = `<div class="card">
      <p class="job-title">${esc(job.title)}</p>
      <div class="job-meta">${jobMeta(job)}</div>
      <p class="job-desc">${esc(job.description)}</p>
      ${tags(job.required_skills)}
    </div>`;
    if (!job.is_open) {
      banner(msg, "This role is closed and no longer accepting applications.");
      form.style.display = "none";
    }
  } catch (err) {
    banner(msg, err.message);
    form.style.display = "none";
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    banner(msg, "");
    result.innerHTML = `<div class="spinner">Reading your resume and screening…</div>`;
    button.disabled = true;

    try {
      const data = new FormData(form);
      data.append("job_id", jobId);
      const app = await api("/api/applications", { method: "POST", body: data });
      result.innerHTML =
        `<h2>Your screening result</h2>` + applicantCard(app);
      banner(msg, "Application submitted.", "ok");
      form.reset();
    } catch (err) {
      result.innerHTML = "";
      banner(msg, err.message);
    } finally {
      button.disabled = false;
    }
  });
}

/* ------------------------------------------------------------------ */
/* recruiter.html -- post roles, review ranked applicants              */
/* ------------------------------------------------------------------ */
async function initRecruiter() {
  const jobForm = document.getElementById("job-form");
  const picker = document.getElementById("job-picker");
  const applicants = document.getElementById("applicants");
  const msg = document.getElementById("banner");
  const formMsg = document.getElementById("form-banner");

  await showEngineNotice(msg);

  async function loadJobs(selectId) {
    const jobs = await api("/api/jobs");
    picker.innerHTML = jobs.length
      ? jobs
          .map(
            (j) =>
              `<option value="${j.id}">${esc(j.title)}${
                j.is_open ? "" : " (closed)"
              } — ${j.location ? esc(j.location) : "no location"}</option>`
          )
          .join("")
      : `<option value="">No jobs posted yet</option>`;
    if (selectId) picker.value = String(selectId);
    await loadApplicants();
  }

  async function loadApplicants() {
    const jobId = picker.value;
    if (!jobId) {
      applicants.innerHTML = `<div class="empty">Post a job to start collecting applicants.</div>`;
      return;
    }
    applicants.innerHTML = `<div class="spinner">Loading applicants…</div>`;
    try {
      const apps = await api(`/api/jobs/${jobId}/applications`);
      applicants.innerHTML = apps.length
        ? apps.map((a) => applicantCard(a, { recruiter: true })).join("")
        : `<div class="empty">No applications for this role yet.</div>`;
    } catch (err) {
      applicants.innerHTML = "";
      banner(msg, err.message);
    }
  }

  jobForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = jobForm.querySelector("button");
    button.disabled = true;
    banner(formMsg, "");
    try {
      const raw = Object.fromEntries(new FormData(jobForm));
      const job = await api("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title: raw.title,
          description: raw.description,
          location: raw.location || null,
          employment_type: raw.employment_type || null,
          min_years_experience: Number(raw.min_years_experience || 0),
          required_skills: String(raw.required_skills || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        }),
      });
      jobForm.reset();
      banner(formMsg, `Posted “${job.title}”.`, "ok");
      await loadJobs(job.id);
    } catch (err) {
      banner(formMsg, err.message);
    } finally {
      button.disabled = false;
    }
  });

  picker.addEventListener("change", loadApplicants);

  // Delegated: applicant cards are re-rendered on every load.
  applicants.addEventListener("click", async (event) => {
    const id = event.target.dataset.rescreen;
    if (!id) return;
    event.target.disabled = true;
    try {
      await api(`/api/applications/${id}/rescreen`, { method: "POST" });
      await loadApplicants();
    } catch (err) {
      banner(msg, err.message);
      event.target.disabled = false;
    }
  });

  applicants.addEventListener("change", async (event) => {
    const id = event.target.dataset.status;
    if (!id) return;
    try {
      await api(`/api/applications/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status: event.target.value }),
      });
      await loadApplicants();
    } catch (err) {
      banner(msg, err.message);
    }
  });

  try {
    await loadJobs();
  } catch (err) {
    banner(msg, err.message);
  }
}

/* ------------------------------------------------------------------ */
/* drive.html -- resumes read live from Google Drive                   */
/* ------------------------------------------------------------------ */
function driveCard(row) {
  const badge = `<span class="badge ${esc(row.state)}">${esc(row.state)}</span>`;
  const opened = row.web_view_link
    ? `<a href="${esc(row.web_view_link)}" target="_blank" rel="noopener">Open in Drive</a>`
    : "";
  const fileRow = `<div class="filerow">
      <span>${esc(row.filename)}</span>
      ${row.domain ? `<span class="tag plain">${esc(row.domain)}</span>` : ""}
      ${row.extracted_by ? `<span>read by ${esc(row.extracted_by)}</span>` : ""}
      ${row.chars ? `<span>${row.chars.toLocaleString()} chars</span>` : ""}
      ${opened}
    </div>`;

  if (row.state !== "parsed") {
    return `<div class="card dcard dim">
      <div class="job-head">
        <div><p class="job-title">${esc(row.filename)}</p>
          <div class="job-meta">${esc(row.reason || "Not parsed.")}</div></div>
        ${badge}
      </div>
      ${fileRow}
    </div>`;
  }

  const years = row.years_experience != null ? `${row.years_experience} yrs` : "unknown";
  const cell = (label, value) =>
    `<div><span>${esc(label)}</span>${esc(value || "—")}</div>`;

  return `<div class="card dcard">
    <div class="job-head">
      <div>
        <p class="job-title">${esc(row.full_name || row.filename)}</p>
        <div class="job-meta">${esc(row.email || "no email found")}</div>
      </div>
      ${badge}
    </div>
    ${row.summary ? `<p class="reasoning">${esc(row.summary)}</p>` : ""}
    <div class="meta-grid">
      ${cell("Experience", years)}
      ${cell("Location", row.location)}
      ${cell("Phone", row.phone)}
      ${cell("Education", (row.education || [])[0])}
    </div>
    ${tags(row.skills)}
    ${fileRow}
  </div>`;
}

async function initDrive() {
  const list = document.getElementById("list");
  const countsEl = document.getElementById("counts");
  const msg = document.getElementById("banner");
  const button = document.getElementById("refresh");

  function renderCounts(data) {
    const c = data.counts || {};
    const age = data.cached
      ? `cached ${Math.round((data.age_seconds || 0) / 60)} min ago`
      : "just read from Drive";
    countsEl.innerHTML =
      `<span><b>${c.parsed || 0}</b> parsed</span>` +
      `<span><b>${c.skipped || 0}</b> skipped</span>` +
      `<span><b>${c.failed || 0}</b> failed</span>` +
      `<span>${esc(age)}</span>`;
  }

  async function load(force) {
    banner(msg, "");
    countsEl.innerHTML = "";
    list.innerHTML = `<div class="spinner">${
      force ? "Re-reading every resume from Drive&hellip; this takes a while."
            : "Reading resumes from Drive&hellip;"}</div>`;
    button.disabled = true;
    try {
      const data = force
        ? await api("/api/drive/refresh", { method: "POST" })
        : await api("/api/drive/candidates");
      renderCounts(data);
      list.innerHTML = data.candidates.length
        ? data.candidates.map(driveCard).join("")
        : `<div class="empty">No documents found in that Drive folder.</div>`;
    } catch (err) {
      list.innerHTML = "";
      banner(msg, err.message);
    } finally {
      button.disabled = false;
    }
  }

  button.addEventListener("click", () => load(true));
  await load(false);
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  if (page === "jobs") initJobs();
  if (page === "apply") initApply();
  if (page === "recruiter") initRecruiter();
  if (page === "drive") initDrive();
});
