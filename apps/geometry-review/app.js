import { createSynchronizedGeometryViewers } from "./geometry-viewer.js";

const state = {
  data: null, reviews: null, selectedTarget: null, selectedAttempt: null,
  inputIndex: 0, reviewStartedAt: Date.now(), filters: { dataset: "all", model: "all", outcome: "all", review: "all" },
};
let geometryViewers = null;

const ISSUE_LABELS = {
  agent_geometry: "Agent geometry", agent_reasoning: "Agent reasoning", input_ambiguity: "Input ambiguity",
  ground_truth_error: "Ground-truth error", verifier_metric: "Verifier metric", verifier_threshold: "Verifier threshold",
  alignment_error: "Alignment", export_error: "Geometry export", mcp_error: "MCP interface",
  harness_error: "Harness", attempt_selection: "Attempt selection", none: "No issue",
};
const FINDING_CATEGORIES = Object.keys(ISSUE_LABELS).filter((key) => key !== "none");
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
const fmt = (value, digits = 2) => value == null ? "N/A" : Number(value).toFixed(digits);
const shortHash = (value) => value ? `${value.slice(0, 10)}…${value.slice(-6)}` : "unavailable";

function currentRun() { return state.data?.runs.find((run) => run.target_id === state.selectedTarget); }
function currentAttempt() { return currentRun()?.attempts.find((attempt) => attempt.attempt_id === state.selectedAttempt); }
function activeReviews() {
  const records = state.reviews?.records || [];
  const superseded = new Set(records.map((row) => row.supersedes_review_id).filter(Boolean));
  return records.filter((row) => !superseded.has(row.review_id));
}
function targetReviews(targetId, attemptId = null) {
  return activeReviews().filter((row) => row.binding.target_id === targetId && (!attemptId || row.binding.attempt_id === attemptId));
}

function setOptions(select, values, allLabel) {
  select.innerHTML = `<option value="all">${escapeHtml(allLabel)}</option>` + values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
}

function visibleRuns() {
  return state.data.runs.filter((run) => {
    const records = targetReviews(run.target_id);
    const disputed = records.some((row) => ["partially_agree", "disagree"].includes(row.verifier_decision));
    return (state.filters.dataset === "all" || run.dataset === state.filters.dataset) &&
      (state.filters.model === "all" || run.model === state.filters.model) &&
      (state.filters.outcome === "all" || (state.filters.outcome === "passed") === Boolean(run.passed)) &&
      (state.filters.review === "all" || (state.filters.review === "pending" && !records.length) ||
        (state.filters.review === "reviewed" && records.length) || (state.filters.review === "disputed" && disputed));
  });
}

function renderRunList() {
  const runs = visibleRuns();
  $("runCount").textContent = `${runs.length} of ${state.data.runs.length} runs`;
  $("runList").innerHTML = runs.map((run) => {
    const reviews = targetReviews(run.target_id);
    const disputed = reviews.some((row) => ["partially_agree", "disagree"].includes(row.verifier_decision));
    const reviewState = !reviews.length ? "pending" : disputed ? "disputed" : "reviewed";
    return `<button class="run-item ${run.target_id === state.selectedTarget ? "active" : ""}" data-target="${escapeHtml(run.target_id)}">
      <div><strong>${escapeHtml(run.sample_key)}</strong><span>${escapeHtml(run.model.replace("gpt-5.6-", ""))}</span></div>
      <div class="run-result"><span class="score ${run.passed ? "pass" : "fail"}">${fmt(run.score, 1)}</span><i class="review-dot ${reviewState}" title="${reviewState}"></i></div>
    </button>`;
  }).join("") || `<div class="empty">No runs match these filters.</div>`;
  document.querySelectorAll(".run-item").forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.target)));
  if (runs.length && !runs.some((run) => run.target_id === state.selectedTarget)) selectRun(runs[0].target_id);
}

function metric(label, value, tone = "") { return `<div class="metric"><span>${escapeHtml(label)}</span><strong class="${tone}">${escapeHtml(value)}</strong></div>`; }

function selectRun(targetId) {
  const run = state.data.runs.find((item) => item.target_id === targetId);
  if (!run) return;
  state.selectedTarget = targetId;
  state.selectedAttempt = run.selected_attempt_id || run.attempts.at(-1)?.attempt_id;
  state.inputIndex = 0;
  state.reviewStartedAt = Date.now();
  resetReviewForm();
  renderRun();
  renderRunList();
}

function selectAttempt(attemptId) {
  state.selectedAttempt = attemptId;
  state.reviewStartedAt = Date.now();
  resetReviewForm();
  renderRun();
}

function renderRun() {
  const run = currentRun();
  const attempt = currentAttempt();
  if (!run || !attempt) return;
  $("datasetLabel").textContent = `${run.dataset}${run.category ? ` / ${run.category}` : ""}`;
  $("taskTitle").textContent = run.task;
  $("modelLabel").textContent = `${run.model} · ${run.reasoning_effort || "default"}`;
  $("targetId").textContent = run.target_id;
  $("metrics").innerHTML = [
    metric("Selected score", fmt(run.score), run.passed ? "good" : "bad"),
    metric("Attempt score", fmt(attempt.score), attempt.passed ? "good" : "bad"),
    metric("Strict label", attempt.passed ? "PASS" : "FAIL", attempt.passed ? "good" : "bad"),
    metric("Attempts", run.attempts.length),
    metric("Elapsed", `${fmt(attempt.elapsed_seconds, 1)} s`),
    metric("Ledger", run.integrity?.ok ? "VERIFIED" : "CHECK", run.integrity?.ok ? "good" : "bad"),
  ].join("");
  const annotation = run.data_quality_annotation;
  $("annotationBanner").hidden = !annotation;
  if (annotation) $("annotationBanner").innerHTML = `<strong>Data-quality annotation: ${escapeHtml(annotation.status)}</strong><span>${escapeHtml((annotation.issue_types || []).join(" · "))}</span><p>${escapeHtml(annotation.recommended_use || "")}</p>`;
  renderAttempts(run);
  renderEvidence(run, attempt);
  renderVerifier(attempt);
  renderReflection(attempt);
  renderMcp(attempt);
  renderReviewPanel(run, attempt);
}

function renderAttempts(run) {
  $("attemptButtons").innerHTML = run.attempts.map((attempt) => `<button class="attempt-button ${attempt.attempt_id === state.selectedAttempt ? "active" : ""} ${attempt.passed ? "passed" : "failed"}" data-attempt="${escapeHtml(attempt.attempt_id)}">
    <span>${escapeHtml(attempt.attempt_id)}</span><strong>${fmt(attempt.score, 1)}</strong><small>${attempt.safety_stop_reason ? `safety: ${escapeHtml(attempt.safety_stop_reason)}` : attempt.agent_decision ? `agent: ${escapeHtml(attempt.agent_decision)}` : attempt.selected ? "selected" : attempt.timed_out ? "timeout" : attempt.passed ? "pass" : "no decision"}</small>
  </button>`).join("");
  document.querySelectorAll(".attempt-button").forEach((button) => button.addEventListener("click", () => selectAttempt(button.dataset.attempt)));
}

function setImage(id, source, emptyText) {
  const image = $(id);
  image.src = source || "";
  image.hidden = !source;
  image.parentElement.classList.toggle("missing", !source);
  image.parentElement.dataset.empty = source ? "" : emptyText;
}

function renderEvidence(run, attempt) {
  const inputs = run.input_images || [];
  setImage("inputImage", inputs[state.inputIndex], "Input image unavailable");
  $("inputSwitcher").innerHTML = inputs.map((_, index) => `<button class="${index === state.inputIndex ? "active" : ""}" data-input="${index}">${index + 1}</button>`).join("");
  document.querySelectorAll("[data-input]").forEach((button) => button.addEventListener("click", () => { state.inputIndex = Number(button.dataset.input); renderEvidence(run, attempt); }));
  setImage("truthImage", attempt.images.ground_truth, "Ground-truth render unavailable");
  setImage("candidateImage", attempt.images.candidate, "Candidate render unavailable");
  setImage("overlayImage", attempt.images.overlay, "Overlay unavailable");
  geometryViewers?.dispose();
  geometryViewers = createSynchronizedGeometryViewers({
    containers: {
      truth: $("truthViewer"), candidate: $("candidateViewer"), overlay: $("overlayViewer"),
    },
    geometry: attempt.geometry || {},
  });
  $("candidateCaption").textContent = attempt.attempt_id;
  $("truthCaption").textContent = `SHA ${shortHash(run.ground_truth_sha256)}`;
  $("candidateState").textContent = `SHA ${shortHash(attempt.evidence?.candidate?.sha256)}`;
  $("overlayState").textContent = attempt.render_error ? `Render error: ${attempt.render_error}` : "Axis-permutation and translation alignment; no scale";
}

function thresholdText(check) {
  if (check.minimum != null) return `≥ ${fmt(check.minimum, 3)}`;
  if (check.maximum != null) return `≤ ${fmt(check.maximum, 3)}`;
  return String(check.expected);
}

function renderVerifier(attempt) {
  const verdict = attempt.verdict || {};
  $("checkList").innerHTML = (verdict.rubrics || []).map((check) => `<div class="check-row">
    <span class="status-mark ${check.status}"></span><strong>${escapeHtml(check.id.replaceAll("_", " "))}</strong>
    <code>${escapeHtml(String(check.actual))}</code><span>target ${escapeHtml(thresholdText(check))}</span>
  </div>`).join("") || `<div class="empty">Verifier produced no checks.</div>`;
  const candidate = verdict.candidate_geometry || {};
  const truth = verdict.ground_truth_geometry || {};
  const rows = [
    ["Extents", JSON.stringify(candidate.extents), JSON.stringify(truth.extents)],
    ["Volume", fmt(candidate.volume, 3), fmt(truth.volume, 3)],
    ["Surface area", fmt(candidate.surface_area, 3), fmt(truth.surface_area, 3)],
    ["Watertight", String(candidate.watertight), String(truth.watertight)],
    ["Triangles", candidate.triangles ?? "N/A", truth.triangles ?? "N/A"],
  ];
  $("geometryTable").innerHTML = `<div class="geometry-head"><span>Measure</span><span>Candidate</span><span>Truth</span></div>` + rows.map((row) => `<div><span>${escapeHtml(row[0])}</span><code>${escapeHtml(row[1])}</code><code>${escapeHtml(row[2])}</code></div>`).join("");
  $("protocolBinding").textContent = verdict.protocol || state.data.campaign.protocol;
  $("evidenceHash").textContent = attempt.evidence_sha256;
}

function listBlock(title, items) {
  return `<section><h3>${escapeHtml(title)}</h3>${items?.length ? `<ol>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>` : `<div class="empty">Not recorded</div>`}</section>`;
}

function renderReflection(attempt) {
  const reflection = attempt.reflection || {};
  const decision = attempt.agent_decision || reflection.decision;
  const safety = attempt.safety_stop_reason;
  $("iterationDecision").className = `iteration-decision ${decision || "unavailable"} ${safety ? "safety" : ""}`;
  $("iterationDecision").innerHTML = `<div><span>Agent decision</span><strong>${escapeHtml(decision || "unavailable")}</strong></div><p>${escapeHtml(attempt.decision_reason || reflection.decision_reason || "No decision reason was recorded.")}</p><div class="decision-facts"><span>Can improve <strong>${reflection.can_improve ?? attempt.can_improve ?? "N/A"}</strong></span><span>Expected gain <strong>${reflection.expected_score_gain == null ? "N/A" : fmt(reflection.expected_score_gain, 1)}</strong></span><span>Safety stop <strong>${escapeHtml(safety || "none")}</strong></span></div><div class="structure-assessment"><span>Structure assessment</span><p>${escapeHtml(reflection.structure_assessment || "Not recorded")}</p><span>System change proposal</span><p>${escapeHtml(reflection.system_change_proposal || "None")}</p></div>`;
  $("feedbackPacket").textContent = attempt.feedback_packet ? JSON.stringify(attempt.feedback_packet, null, 2) : "Feedback packet was not recorded for this legacy attempt.";
  $("reflectionContent").innerHTML = `<section class="owner"><h3>Failure owner</h3><strong>${escapeHtml(reflection.failure_owner || "not recorded")}</strong><span>Confidence ${reflection.confidence == null ? "N/A" : fmt(reflection.confidence, 2)}</span></section>` +
    listBlock("Observed failures", reflection.observed_failures) + listBlock("Root causes", reflection.root_causes) + listBlock("Planned changes", reflection.planned_geometry_changes);
  $("publicEvents").innerHTML = (attempt.public_events || []).map((event, index) => {
    const title = event.type === "agent_message" ? "Agent message" : event.type === "mcp_tool_call" ? `MCP · ${event.tool}` : "Command";
    const detail = event.text || event.command || JSON.stringify(event.arguments || {});
    return `<details ${index < 2 ? "open" : ""}><summary><span>${index + 1}</span><strong>${escapeHtml(title)}</strong><i>${escapeHtml(event.phase || "action")}</i><i class="${event.status === "completed" ? "ok" : "warn"}">${escapeHtml(event.status || "")}</i></summary><pre>${escapeHtml(detail)}</pre>${event.error ? `<p class="error-text">${escapeHtml(JSON.stringify(event.error))}</p>` : ""}</details>`;
  }).join("") || `<div class="empty">No public action events were recorded.</div>`;
}

function renderMcp(attempt) {
  const events = attempt.mcp_events || [];
  const failed = events.filter((event) => event.status !== "pass").length;
  const totalMs = events.reduce((sum, event) => sum + Number(event.duration_ms || 0), 0);
  $("auditSummary").innerHTML = `<span><strong>${events.length}</strong> calls</span><span><strong>${failed}</strong> failed</span><span><strong>${fmt(totalMs, 0)}</strong> ms observed</span>`;
  $("mcpEvents").innerHTML = events.map((event, index) => `<details class="${event.status === "pass" ? "" : "failed"}"><summary><span>${index + 1}</span><strong>${escapeHtml(event.tool)}</strong><i class="${event.status === "pass" ? "ok" : "warn"}">${escapeHtml(event.status)}</i><code>${fmt(event.duration_ms, 1)} ms</code></summary><pre>${escapeHtml(JSON.stringify(event.arguments || {}, null, 2))}</pre>${event.error ? `<p class="error-text">${escapeHtml(JSON.stringify(event.error))}</p>` : ""}</details>`).join("") || `<div class="empty">No MCP calls were recorded for this attempt.</div>`;
}

function renderReviewPanel(run, attempt) {
  $("reviewTarget").textContent = `${run.sample_key} · ${attempt.attempt_id}`;
  $("reviewBinding").innerHTML = `<span>Review binds to this exact evidence</span><code>${shortHash(attempt.evidence_sha256)}</code>${attempt.selected ? `<strong>Campaign-selected attempt</strong>` : `<strong class="warning">Not the campaign-selected attempt</strong>`}`;
  const history = targetReviews(run.target_id, attempt.attempt_id);
  $("historyCount").textContent = `${history.length} active`;
  $("reviewHistory").innerHTML = history.map((record) => `<article><div><strong>${escapeHtml(record.reviewer.id)}</strong><span>${escapeHtml(record.created_at)}</span></div><div><span class="decision ${escapeHtml(record.verifier_decision)}">${escapeHtml(record.verifier_decision.replaceAll("_", " "))}</span><span>${escapeHtml(record.recommended_action.replaceAll("_", " "))}</span></div><p>${escapeHtml(record.notes || "No notes")}</p><button type="button" class="secondary revise" data-review="${record.review_id}">Revise</button></article>`).join("") || `<div class="empty">No active human review for this attempt.</div>`;
  document.querySelectorAll(".revise").forEach((button) => button.addEventListener("click", () => populateRevision(button.dataset.review)));
}

function resetReviewForm() {
  $("reviewForm").reset();
  $("reviewerId").value = localStorage.getItem("evocadReviewerId") || "";
  $("reviewerExpertise").value = localStorage.getItem("evocadReviewerExpertise") || "";
  $("strictAssessment").value = "correct";
  $("selectionAssessment").value = "correct";
  $("recommendedAction").value = "keep";
  $("supersedesId").value = "";
  $("findings").innerHTML = "";
  $("formStatus").textContent = "";
  document.querySelector('input[name="issueType"][value="none"]')?.click();
}

function populateRevision(reviewId) {
  const record = state.reviews.records.find((row) => row.review_id === reviewId);
  if (!record) return;
  $("reviewerId").value = record.reviewer.id;
  $("reviewerExpertise").value = record.reviewer.expertise;
  document.querySelector(`input[name="verifierDecision"][value="${record.verifier_decision}"]`).checked = true;
  $("strictAssessment").value = record.strict_pass_assessment;
  $("selectionAssessment").value = record.selected_attempt_assessment;
  document.querySelectorAll("[data-rating]").forEach((select) => { select.value = record.ratings[select.dataset.rating] ?? ""; });
  document.querySelectorAll('input[name="issueType"]').forEach((input) => { input.checked = record.issue_types.includes(input.value); });
  $("recommendedAction").value = record.recommended_action;
  $("reviewNotes").value = record.notes;
  $("supersedesId").value = record.review_id;
  $("findings").innerHTML = "";
  record.findings.forEach((finding) => addFinding(finding));
  $("formStatus").textContent = `Revision of ${record.review_id.slice(0, 10)}. The original remains in history.`;
  $("reviewForm").scrollIntoView({ behavior: "smooth", block: "start" });
}

function addFinding(value = {}) {
  const index = document.querySelectorAll(".finding").length + 1;
  const wrapper = document.createElement("div");
  wrapper.className = "finding";
  wrapper.innerHTML = `<div class="finding-header"><strong>Finding ${index}</strong><button type="button" class="remove-finding">Remove</button></div><div class="two-col"><label>Category<select data-field="category">${FINDING_CATEGORIES.map((key) => `<option value="${key}">${escapeHtml(ISSUE_LABELS[key])}</option>`).join("")}</select></label><label>Severity<select data-field="severity"><option value="note">Note</option><option value="minor">Minor</option><option value="major">Major</option><option value="critical">Critical</option></select></label></div><label>Location<input data-field="location" maxlength="500" placeholder="feature, view, metric, or event"></label><label>Observation<textarea data-field="observation" rows="2" maxlength="4000" required></textarea></label><label>Recommendation<textarea data-field="recommendation" rows="2" maxlength="4000"></textarea></label>`;
  wrapper.querySelector('[data-field="category"]').value = value.category || "agent_geometry";
  wrapper.querySelector('[data-field="severity"]').value = value.severity || "major";
  ["location", "observation", "recommendation"].forEach((key) => { wrapper.querySelector(`[data-field="${key}"]`).value = value[key] || ""; });
  wrapper.querySelector(".remove-finding").addEventListener("click", () => wrapper.remove());
  $("findings").appendChild(wrapper);
}

function collectFindings() {
  return [...document.querySelectorAll(".finding")].map((finding) => Object.fromEntries([...finding.querySelectorAll("[data-field]")].map((field) => [field.dataset.field, field.value])));
}

async function submitReview(event) {
  event.preventDefault();
  const run = currentRun(); const attempt = currentAttempt();
  const issues = [...document.querySelectorAll('input[name="issueType"]:checked')].map((input) => input.value);
  const decision = document.querySelector('input[name="verifierDecision"]:checked')?.value;
  const payload = {
    target_id: run.target_id, attempt_id: attempt.attempt_id,
    reviewer: { id: $("reviewerId").value, expertise: $("reviewerExpertise").value },
    verifier_decision: decision, strict_pass_assessment: $("strictAssessment").value,
    selected_attempt_assessment: $("selectionAssessment").value,
    ratings: Object.fromEntries([...document.querySelectorAll("[data-rating]")].map((select) => [select.dataset.rating, select.value ? Number(select.value) : null])),
    issue_types: issues, recommended_action: $("recommendedAction").value,
    findings: collectFindings(), notes: $("reviewNotes").value,
    duration_seconds: (Date.now() - state.reviewStartedAt) / 1000,
    supersedes_review_id: $("supersedesId").value || null,
  };
  $("submitReview").disabled = true;
  $("formStatus").textContent = "Saving…";
  try {
    const response = await fetch("/api/reviews", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    localStorage.setItem("evocadReviewerId", payload.reviewer.id);
    localStorage.setItem("evocadReviewerExpertise", payload.reviewer.expertise);
    state.reviews = await fetch("/api/reviews", { cache: "no-store" }).then((result) => result.json());
    resetReviewForm();
    $("formStatus").textContent = `Saved ${body.review_id.slice(0, 10)} · ledger hash ${shortHash(body.record_sha256)}`;
    renderHeader(); renderRunList(); renderReviewPanel(run, attempt);
  } catch (error) {
    $("formStatus").textContent = `Save failed: ${error.message}`;
  } finally { $("submitReview").disabled = false; }
}

function renderHeader() {
  $("campaignName").textContent = state.data.campaign.campaign_id;
  $("protocolLabel").textContent = state.data.campaign.protocol;
  const summary = state.reviews.summary;
  $("reviewProgress").textContent = `${summary.reviewed_targets} / ${summary.total_targets} reviewed`;
  $("ledgerIntegrity").textContent = state.reviews.integrity.ok ? `${state.reviews.integrity.records} records · verified` : "Ledger integrity error";
  $("ledgerIntegrity").classList.toggle("bad", !state.reviews.integrity.ok);
  const decisions = summary.decisions;
  const labels = summary.strict_pass_assessments;
  const issues = summary.issue_counts;
  const decided = decisions.agree + decisions.partially_agree + decisions.disagree;
  const agreement = decided ? (100 * decisions.agree / decided).toFixed(0) + "%" : "N/A";
  $("reviewAuditMetrics").innerHTML = [
    ["Verifier agreement", agreement],
    ["Disputed reviews", decisions.partially_agree + decisions.disagree],
    ["False +/- labels", labels.false_positive + labels.false_negative],
    ["Data flags", issues.input_ambiguity + issues.ground_truth_error],
    ["Verifier flags", issues.verifier_metric + issues.verifier_threshold + issues.alignment_error],
    ["Reviewer conflicts", summary.conflicted_evidence],
  ].map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

function bindControls() {
  ["dataset", "model", "outcome", "review"].forEach((key) => $(key + "Filter").addEventListener("change", (event) => { state.filters[key] = event.target.value; renderRunList(); }));
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".tab, .tab-panel").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active"); $(tab.dataset.tab + "Panel").classList.add("active");
  }));
  document.querySelectorAll("[data-rating]").forEach((select) => { select.innerHTML = `<option value="">N/A</option>` + [1, 2, 3, 4, 5].map((value) => `<option>${value}</option>`).join(""); });
  $("issueInputs").innerHTML = Object.entries(ISSUE_LABELS).map(([key, label]) => `<label><input type="checkbox" name="issueType" value="${key}"><span>${escapeHtml(label)}</span></label>`).join("");
  $("issueInputs").addEventListener("change", (event) => {
    if (!event.target.matches('input[name="issueType"]')) return;
    const none = document.querySelector('input[name="issueType"][value="none"]');
    if (event.target === none && none.checked) document.querySelectorAll('input[name="issueType"]:not([value="none"])').forEach((input) => { input.checked = false; });
    else if (event.target.checked) none.checked = false;
    if (![...document.querySelectorAll('input[name="issueType"]:checked')].length) none.checked = true;
  });
  $("addFinding").addEventListener("click", () => addFinding());
  $("reviewForm").addEventListener("submit", submitReview);
  $("exportReviews").addEventListener("click", () => {
    const blob = new Blob([(state.reviews.records || []).map((row) => JSON.stringify(row)).join("\n") + "\n"], { type: "application/x-ndjson" });
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${state.data.campaign.campaign_id}-human-reviews.jsonl`; link.click(); URL.revokeObjectURL(link.href);
  });
  document.querySelectorAll(".image-button").forEach((button) => button.addEventListener("click", () => {
    const image = button.querySelector("img"); if (!image.src || image.hidden) return;
    $("dialogImage").src = image.src; $("imageDialog").showModal();
  }));
  $("closeDialog").addEventListener("click", () => $("imageDialog").close());
}

async function start() {
  bindControls();
  [state.data, state.reviews] = await Promise.all([
    fetch("/data/review-data.json", { cache: "no-store" }).then((response) => { if (!response.ok) throw new Error("Review bundle unavailable"); return response.json(); }),
    fetch("/api/reviews", { cache: "no-store" }).then((response) => { if (!response.ok) throw new Error("Review ledger unavailable"); return response.json(); }),
  ]);
  setOptions($("datasetFilter"), [...new Set(state.data.runs.map((run) => run.dataset))].sort(), "All datasets");
  setOptions($("modelFilter"), state.data.models, "All models");
  renderHeader(); resetReviewForm(); renderRunList();
}

start().catch((error) => { $("taskTitle").textContent = error.message; $("ledgerIntegrity").textContent = "Data unavailable"; });
