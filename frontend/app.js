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
/* Build a File from the generated PDF and put it in the file input, so the
   form submits identically to a resume the candidate picked themselves.
   DataTransfer is the only way to set input.files programmatically. */
async function attachGeneratedResume(input, info) {
  const res = await fetch(`/api/simulate/resume/${encodeURIComponent(info.token)}`);
  if (!res.ok) throw new Error("Could not fetch the generated resume.");
  const blob = await res.blob();
  const file = new File([blob], info.filename, { type: "application/pdf" });
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  return file;
}

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

  const fileInput = document.getElementById("resume");
  const nameInput = document.getElementById("full_name");
  const emailInput = document.getElementById("email");
  const simulate = document.getElementById("simulate");
  const simNote = document.getElementById("sim-note");
  let generated = false;

  // Clear only the fields Simulate filled, so a value the candidate typed
  // themselves is never wiped out from under them.
  function clearSimulated() {
    generated = false;
    if (nameInput.dataset.simulated) {
      nameInput.value = "";
      delete nameInput.dataset.simulated;
    }
    if (emailInput.dataset.simulated) {
      emailInput.value = "";
      delete emailInput.dataset.simulated;
    }
    simNote.className = "simnote";
    simNote.textContent = "";
  }

  // A file the candidate picks themselves is not ours to push to Drive, and
  // it makes the simulated name and email stale.
  fileInput.addEventListener("change", () => {
    if (!generated) return;
    clearSimulated();
  });

  simulate.addEventListener("click", async () => {
    simulate.disabled = true;
    simNote.className = "simnote";
    simNote.textContent = "Writing a resume\u2026";
    try {
      const info = await api("/api/simulate/resume", { method: "POST" });
      generated = true;
      await attachGeneratedResume(fileInput, info);
      // Fill the form from the same persona the PDF was rendered from, so
      // what the recruiter sees matches the attached resume.
      if (info.full_name) {
        nameInput.value = info.full_name;
        nameInput.dataset.simulated = "1";
      }
      if (info.email) {
        emailInput.value = info.email;
        emailInput.dataset.simulated = "1";
      }
      simNote.className = "simnote ok";
      simNote.textContent =
        `Filled in ${info.full_name || "candidate"}` +
        `${info.email ? " <" + info.email + ">" : ""}` +
        `${info.headline ? ", " + info.headline : ""} ` +
        `and attached ${info.filename}. ` +
        `It will be uploaded to Drive on submit.`;
    } catch (err) {
      generated = false;
      simNote.className = "simnote bad";
      simNote.textContent = err.message;
    } finally {
      simulate.disabled = false;
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    banner(msg, "");
    result.innerHTML = `<div class="spinner">Reading your resume and screening…</div>`;
    button.disabled = true;

    try {
      const data = new FormData(form);
      data.append("job_id", jobId);
      // Only a resume we generated gets pushed to the shared Drive folder.
      data.append("upload_to_drive", generated ? "true" : "false");
      const app = await api("/api/applications", { method: "POST", body: data });
      result.innerHTML =
        `<h2>Your screening result</h2>` + applicantCard(app);
      if (app.warning) {
        banner(msg, app.warning, "warn");
      } else {
        banner(msg, generated
          ? "Application submitted and the resume was added to Drive."
          : "Application submitted.", "ok");
      }
      generated = false;
      simNote.className = "simnote";
      simNote.textContent = "";
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
  const msg = document.getElementById("banner");
  const formMsg = document.getElementById("form-banner");

  await showEngineNotice(msg);

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
      banner(formMsg, `Posted \u201c${job.title}\u201d.`, "ok");
    } catch (err) {
      banner(formMsg, err.message);
    } finally {
      button.disabled = false;
    }
  });
}

/* ------------------------------------------------------------------ */
/* drive.html -- resumes read live from Google Drive                   */
/*                                                                     */
/* Two stages, matching the API: the document list is parsed without   */
/* an LLM and arrives immediately, then each card's candidate details  */
/* are fetched one at a time and filled in.                            */
/* ------------------------------------------------------------------ */
function driveFileRow(doc) {
  return `<div class="filerow">
      <span>${esc(doc.filename)}</span>
      ${doc.domain ? `<span class="tag plain">${esc(doc.domain)}</span>` : ""}
      ${doc.chars ? `<span>${doc.chars.toLocaleString()} chars</span>` : ""}
      ${doc.web_view_link
        ? `<a href="${esc(doc.web_view_link)}" target="_blank" rel="noopener">Open in Drive</a>`
        : ""}
    </div>`;
}

/* Which posting this resume was submitted against -- the one field the
   Applicants view adds. Drive knows the file; only the database knows this. */
function appliedRow(applicant) {
  if (!applicant) return "";
  const when = applicant.created_at
    ? new Date(applicant.created_at).toLocaleDateString(undefined, {
        day: "numeric", month: "short", year: "numeric",
      })
    : "";
  return `<div class="applied">
      <span class="applied-label">Applied to</span>
      <span class="applied-job">${esc(applicant.job.title)}</span>
      ${applicant.job.location ? `<span class="tag plain">${esc(applicant.job.location)}</span>` : ""}
      ${when ? `<span class="applied-when">${esc(when)}</span>` : ""}
    </div>`;
}

/* The screening result, shown on the Applicants view. This is the recruiter
   review that used to live on the Recruiter tab: verdict, reasoning, skill
   hits and misses, plus the status and re-screen controls. */
function screeningBlock(applicant) {
  const app = applicant && applicant.application;
  if (!app) return "";
  const verdict = app.verdict
    ? `<span class="verdict ${esc(app.verdict)}">${esc(
        VERDICT_LABEL[app.verdict] || app.verdict
      )}</span>`
    : "";
  return `<div class="screening">
    <div class="screening-head">
      <span class="score-inline">${app.score ?? "\u2013"}<small>/100</small></span>
      ${verdict}
      <span class="screened-by">screened by ${esc(app.screened_by || "n/a")}</span>
    </div>
    <p class="reasoning">${esc(app.reasoning || "Not screened yet.")}</p>
    ${tags(app.matched_skills, "tag hit")}
    ${tags(app.missing_skills, "tag miss")}
    <div class="controls">
      <select data-status="${app.id}" aria-label="Application status">
        ${["new", "screened", "shortlisted", "rejected"]
          .map((st) => `<option value="${st}"${st === app.status ? " selected" : ""}>${st}</option>`)
          .join("")}
      </select>
      <button class="ghost" data-rescreen="${app.id}">Re-screen</button>
    </div>
  </div>`;
}

function driveCard(doc, applicant) {
  const badge = `<span class="badge ${esc(doc.state)}">${esc(doc.state)}</span>`;

  if (doc.state !== "parsed") {
    return `<div class="card dcard dim">
      <div class="job-head">
        <div><p class="job-title">${esc(doc.filename)}</p>
          <div class="job-meta">${esc(doc.reason || "Not parsed.")}</div></div>
        ${badge}
      </div>
      ${appliedRow(applicant)}
      ${screeningBlock(applicant)}
      ${driveFileRow(doc)}
    </div>`;
  }

  // Details arrive later; the slot is filled in by fillDetails().
  return `<div class="card dcard" id="doc-${esc(doc.file_id)}">
    <div class="job-head">
      <div>
        <p class="job-title">${esc(doc.display_name || doc.filename)}</p>
        <div class="job-meta" data-slot="sub">Reading details&hellip;</div>
      </div>
      ${badge}
    </div>
    ${appliedRow(applicant)}
    ${screeningBlock(applicant)}
    <div data-slot="body"></div>
    ${driveFileRow(doc)}
  </div>`;
}

/* An applicant row whose file has since been removed from the folder. The
   application is still a real record, so it is shown rather than dropped. */
function missingApplicantCard(applicant) {
  return `<div class="card dcard dim">
    <div class="job-head">
      <div>
        <p class="job-title">${esc((applicant.candidate && applicant.candidate.full_name) || applicant.drive_filename)}</p>
        <div class="job-meta">This file is no longer in the Drive folder.</div>
      </div>
      <span class="badge skipped">missing</span>
    </div>
    ${appliedRow(applicant)}
    ${screeningBlock(applicant)}
    <div class="filerow">
      <span>${esc(applicant.drive_filename)}</span>
      ${applicant.drive_web_link
        ? `<a href="${esc(applicant.drive_web_link)}" target="_blank" rel="noopener">Open in Drive</a>`
        : ""}
    </div>
  </div>`;
}

function renderDetails(card, d) {
  const cell = (label, value) =>
    `<div><span>${esc(label)}</span>${esc(value || "—")}</div>`;
  const years = d.years_experience != null ? `${d.years_experience} yrs` : "unknown";

  const title = card.querySelector(".job-title");
  if (title && d.full_name) title.textContent = d.full_name;

  card.querySelector('[data-slot="sub"]').innerHTML =
    `${esc(d.email || "no email found")} · read by ${esc(d.extracted_by || "?")}`;

  card.querySelector('[data-slot="body"]').innerHTML =
    (d.summary ? `<p class="reasoning">${esc(d.summary)}</p>` : "") +
    `<div class="meta-grid">
       ${cell("Experience", years)}
       ${cell("Location", d.location)}
       ${cell("Phone", d.phone)}
       ${cell("Education", (d.education || [])[0])}
     </div>` +
    tags(d.skills);
}

async function initDrive() {
  const list = document.getElementById("list");
  const countsEl = document.getElementById("counts");
  const msg = document.getElementById("banner");
  const button = document.getElementById("refresh");
  const rebuild = document.getElementById("rebuild");
  const viewSwitch = document.getElementById("view-switch");
  let run = 0; // cancels an in-flight detail sweep when a reload starts

  let view = "candidates";
  let data = null;       // the last Drive listing
  let applicants = [];   // rows from the applicants table
  // file_id -> detail, so flipping the switch does not re-run the model on
  // resumes that have already been read.
  const details = new Map();

  const byFile = () => new Map(applicants.map((a) => [a.drive_file_id, a]));

  function renderCounts(detailed, shown) {
    if (!data) return;
    const c = data.counts || {};
    const age = data.cached
      ? `cached ${Math.round((data.age_seconds || 0) / 60)} min ago`
      : "just read from Drive";
    const head =
      view === "applicants"
        ? `<span><b>${shown}</b> applicant${shown === 1 ? "" : "s"}</span>`
        : `<span><b>${c.parsed || 0}</b> parsed</span>` +
          (c.skipped ? `<span><b>${c.skipped}</b> skipped</span>` : "") +
          (c.failed ? `<span><b>${c.failed}</b> failed</span>` : "") +
          (c.reused ? `<span><b>${c.reused}</b> unchanged, reused</span>` : "") +
          (c.reparsed ? `<span><b>${c.reparsed}</b> newly parsed</span>` : "");
    countsEl.innerHTML =
      head +
      `<span><b>${detailed}</b> of ${shown} detailed</span>` +
      `<span>${esc(age)}</span>`;
  }

  /* Which documents the current view shows. Candidates is the whole folder;
     Applicants is only what came in through an application. */
  function visibleDocs() {
    if (!data) return [];
    if (view !== "applicants") return data.documents;
    const linked = byFile();
    return data.documents.filter((d) => linked.has(d.file_id));
  }

  function render() {
    const linked = byFile();
    const docs = visibleDocs();
    let html = docs.map((d) => driveCard(d, linked.get(d.file_id))).join("");

    if (view === "applicants") {
      const seen = new Set(docs.map((d) => d.file_id));
      html += applicants
        .filter((a) => !seen.has(a.drive_file_id))
        .map(missingApplicantCard)
        .join("");
      if (!html) {
        html = `<div class="empty">No applications have uploaded a resume yet.</div>`;
      }
    } else if (!html) {
      html = `<div class="empty">No documents found in that Drive folder.</div>`;
    }
    list.innerHTML = html;

    // Put back everything the model has already told us about these files.
    let known = 0;
    for (const doc of docs) {
      const detail = details.get(doc.file_id);
      const card = document.getElementById(`doc-${doc.file_id}`);
      if (detail && card) {
        renderDetails(card, detail);
        known += 1;
      }
    }
    renderCounts(known, docs.length);
    return known;
  }

  /* One request at a time: the free Groq tier is capped per minute, and a
     burst of parallel extractions just triggers rate limiting. */
  async function fillDetails(token) {
    let done = render();
    for (const doc of visibleDocs()) {
      if (token !== run) return;
      if (doc.state !== "parsed" || details.has(doc.file_id)) continue;
      const card = document.getElementById(`doc-${doc.file_id}`);
      if (!card) continue;
      try {
        const detail = await api(`/api/drive/documents/${doc.file_id}/details`);
        if (token !== run) return;
        details.set(doc.file_id, detail);
        // The card can be gone if the view changed under us.
        const live = document.getElementById(`doc-${doc.file_id}`);
        if (live) renderDetails(live, detail);
        done += 1;
      } catch (err) {
        const sub = card.querySelector('[data-slot="sub"]');
        if (sub) sub.textContent = `Details unavailable: ${err.message}`;
      }
      renderCounts(done, visibleDocs().length);
    }
  }

  async function load(mode) {
    const full = mode === "full";
    const force = full || mode === "check";
    const token = ++run;

    banner(msg, "");
    countsEl.innerHTML = "";
    list.innerHTML = `<div class="spinner">${
      full ? "Re-reading every resume from Drive&hellip;"
           : force ? "Checking Drive for changes&hellip;"
                   : "Reading resumes from Drive&hellip;"}</div>`;
    button.disabled = true;
    rebuild.disabled = true;
    if (full) details.clear(); // a rebuild discards the cached extractions

    try {
      // The applicants table is cheap and independent of Drive, so it is
      // fetched alongside rather than only when the switch is flipped.
      const [listing, applicantData] = await Promise.all([
        force
          ? api(`/api/drive/refresh${full ? "?full=true" : ""}`, { method: "POST" })
          : api("/api/drive/documents"),
        api("/api/applicants").catch(() => ({ applicants: [] })),
      ]);
      if (token !== run) return;

      data = listing;
      applicants = applicantData.applicants || [];

      // The list is on screen; now fill in what the model has to say.
      fillDetails(token);
    } catch (err) {
      list.innerHTML = "";
      banner(msg, err.message);
    } finally {
      button.disabled = false;
      rebuild.disabled = false;
    }
  }

  async function reloadApplicants() {
    try {
      const fresh = await api("/api/applicants");
      applicants = fresh.applicants || [];
      render();
    } catch (err) {
      banner(msg, err.message);
    }
  }

  /* Delegated: the cards are rebuilt on every render, so the listeners live
     on the container rather than on each button. */
  list.addEventListener("click", async (event) => {
    const id = event.target.dataset.rescreen;
    if (!id) return;
    event.target.disabled = true;
    try {
      await api(`/api/applications/${id}/rescreen`, { method: "POST" });
      await reloadApplicants();
    } catch (err) {
      banner(msg, err.message);
      event.target.disabled = false;
    }
  });

  list.addEventListener("change", async (event) => {
    const id = event.target.dataset.status;
    if (!id) return;
    try {
      await api(`/api/applications/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status: event.target.value }),
      });
      await reloadApplicants();
    } catch (err) {
      banner(msg, err.message);
    }
  });

  viewSwitch.addEventListener("change", (event) => {
    if (!event.target.name || event.target.name !== "view") return;
    view = event.target.value;
    if (!data) return;
    // No refetch: the switch is a filter over what is already loaded. Details
    // still missing for the newly visible cards are fetched on the way past.
    fillDetails(++run);
  });

  button.addEventListener("click", () => load("check"));
  rebuild.addEventListener("click", () => load("full"));
  await load(null);
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  if (page === "jobs") initJobs();
  if (page === "apply") initApply();
  if (page === "recruiter") initRecruiter();
  if (page === "drive") initDrive();
});
