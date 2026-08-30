const state = { data: null, sample: "all", model: "all", selectedRunId: null };

const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 2) => Number(value || 0).toFixed(digits);
const shortModel = (value) => value.replace("gpt-5.6-", "");

function dataUrl() {
  return new URLSearchParams(location.search).get("data") ||
    "/reports/generated/pilot-v4-20260829/explorer/explorer-data.json";
}

function visibleRuns() {
  const passed = $("showPassed").checked;
  const failed = $("showFailed").checked;
  return state.data.runs.filter((run) =>
    (state.sample === "all" || run.sample_id === state.sample) &&
    (state.model === "all" || run.model === state.model) &&
    ((run.status === "passed" && passed) || (run.status !== "passed" && failed))
  );
}

function setModels() {
  const holder = $("modelSegments");
  holder.innerHTML = "";
  ["all", ...state.data.models].forEach((model) => {
    const button = document.createElement("button");
    button.textContent = model === "all" ? "All" : shortModel(model);
    button.className = state.model === model ? "active" : "";
    button.addEventListener("click", () => { state.model = model; setModels(); renderRunList(); });
    holder.appendChild(button);
  });
}

function renderRunList() {
  const runs = visibleRuns();
  const holder = $("runList");
  holder.innerHTML = "";
  runs.forEach((run) => {
    const button = document.createElement("button");
    button.className = `run-item ${run.run_id === state.selectedRunId ? "active" : ""}`;
    button.innerHTML = `<div><strong>${run.sample_key} · ${shortModel(run.model)}</strong><span>${run.domain}</span></div><span class="score">${fmt(run.eqc, 1)}</span>`;
    button.addEventListener("click", () => selectRun(run.run_id));
    holder.appendChild(button);
  });
  if (!runs.some((run) => run.run_id === state.selectedRunId) && runs.length) selectRun(runs[0].run_id);
}

function metric(label, value, tone = "") {
  return `<div class="metric"><label>${label}</label><strong class="${tone}">${value}</strong></div>`;
}

function renderImages(run) {
  const reference = $("referenceImage");
  const switcher = $("referenceSwitcher");
  switcher.innerHTML = "";
  run.reference_images.forEach((source, index) => {
    const button = document.createElement("button");
    button.textContent = index + 1;
    button.className = index === 0 ? "active" : "";
    button.addEventListener("click", () => {
      reference.src = source;
      [...switcher.children].forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
    });
    switcher.appendChild(button);
  });
  reference.src = run.reference_images[0] || "";
  const candidate = $("candidateImage");
  candidate.src = run.candidate_image || "";
  candidate.hidden = !run.candidate_image;
  $("candidateState").textContent = run.render_error ? "Native render unavailable; cached scene render shown." : `Selected checkpoint ${run.selected_attempt_id}`;
}

function renderTrajectory(run) {
  $("trajectoryRows").innerHTML = run.attempts.map((attempt) => `
    <tr class="${attempt.selected ? "selected" : ""}">
      <td class="mono">${attempt.attempt_id}${attempt.selected ? " · selected" : ""}</td>
      <td>${attempt.kind}</td><td class="mono">${fmt(attempt.eqc)}</td>
      <td class="mono">${fmt(attempt.score)}</td><td class="mono">${fmt(attempt.coverage)}%</td>
      <td class="mono">${fmt(attempt.elapsed_seconds, 1)}s</td><td>${attempt.status}</td>
    </tr>`).join("");
}

function renderRubrics(run) {
  const counts = run.rubrics.reduce((acc, item) => { acc[item.final_status] = (acc[item.final_status] || 0) + 1; return acc; }, {});
  $("rubricSummary").innerHTML = `<span>${counts.pass || 0} passed</span><span>${counts.fail || 0} failed</span><span>${counts.unverified || 0} unresolved</span>`;
  $("rubricList").innerHTML = run.rubrics.map((item) => {
    const evidence = item.explanation || (item.evidence || []).map((entry) => typeof entry === "string" ? entry : entry.description).filter(Boolean).join(" · ") || "No accepted evidence";
    const confidence = item.confidence == null ? item.evidence_source : `${item.evidence_source} · ${fmt(item.confidence)}`;
    return `<article class="rubric"><code>${item.id}</code><div><span class="badge ${item.final_status}">${item.final_status}</span><small>${confidence}</small></div><p>${item.requirement}</p><p class="evidence">${evidence}</p></article>`;
  }).join("");
}

function selectRun(runId) {
  state.selectedRunId = runId;
  const run = state.data.runs.find((item) => item.run_id === runId);
  if (!run) return;
  $("domainLabel").textContent = run.domain;
  $("taskTitle").textContent = run.task;
  $("modelLabel").textContent = run.model;
  $("runId").textContent = run.run_id;
  $("metrics").innerHTML = [
    metric("EQC", fmt(run.eqc), run.status === "passed" ? "good" : "bad"),
    metric("Nominal", fmt(run.legacy_score)),
    metric("Det. coverage", `${fmt(run.deterministic_coverage)}%`),
    metric("Attempts", run.attempts.length),
    metric("Selected", run.selected_attempt_id),
    metric("Integrity", run.integrity.ok ? "PASS" : "FAIL", run.integrity.ok ? "good" : "bad"),
  ].join("");
  renderImages(run);
  renderTrajectory(run);
  renderRubrics(run);
  renderRunList();
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".tab, .tab-panel").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    $(`${tab.dataset.tab}Panel`).classList.add("active");
  }));
}

async function start() {
  const response = await fetch(dataUrl());
  if (!response.ok) throw new Error(`Failed to load campaign data: ${response.status}`);
  state.data = await response.json();
  $("campaignName").textContent = state.data.campaign.campaign_id;
  $("manifestHash").textContent = state.data.campaign.manifest_sha256;
  $("integrityState").textContent = `${state.data.runs.filter((run) => run.integrity.ok).length}/${state.data.runs.length} ledgers verified`;
  const samples = [...new Map(state.data.runs.map((run) => [run.sample_id, run])).values()];
  $("sampleSelect").innerHTML = `<option value="all">All workflows</option>` + samples.map((run) => `<option value="${run.sample_id}">${run.sample_key} · ${run.domain}</option>`).join("");
  $("sampleSelect").addEventListener("change", (event) => { state.sample = event.target.value; renderRunList(); });
  ["showPassed", "showFailed"].forEach((id) => $(id).addEventListener("change", renderRunList));
  setModels();
  renderRunList();
  bindTabs();
}

start().catch((error) => {
  $("taskTitle").textContent = error.message;
  $("integrityState").textContent = "Data unavailable";
});
