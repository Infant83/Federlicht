const $ = (sel) => document.querySelector(sel);

const state = {
  info: null,
  runs: [],
  templates: [],
  templateDetails: {},
  templateStyles: [],
  templateStyleContent: {},
  templateBuilder: {
    meta: {},
    sections: [],
    guides: {},
    writerGuidance: [],
    css: "",
  },
  runSummary: null,
  instructionFiles: {},
  filePreview: {
    path: "",
    content: "",
    dirty: false,
    canEdit: false,
    mode: "text",
    objectUrl: "",
    htmlDoc: "",
  },
  saveAs: {
    open: false,
    path: "",
    entries: [],
    mode: "preview",
  },
  runPicker: {
    items: [],
    filtered: [],
    selected: "",
  },
  instructionModal: {
    items: [],
    filtered: [],
    selectedPath: "",
    runRel: "",
    mode: "feather",
  },
  activeJobId: null,
  activeJobKind: null,
  activeSource: null,
  jobs: [],
  jobsExpanded: false,
  historyLogs: {},
  logsCollapsed: false,
  logBuffer: [],
  pipeline: {
    order: [],
    selected: new Set(),
    draggingId: null,
    activeStageId: null,
  },
  templateGen: {
    log: "",
    active: false,
  },
  agentProfiles: {
    list: [],
    activeId: "",
    activeSource: "",
    activeProfile: null,
    memoryText: "",
    readOnly: false,
  },
  canvas: {
    open: false,
    runRel: "",
    basePath: "",
    baseRel: "",
    outputPath: "",
    updatePath: "",
    selection: "",
    reportText: "",
    reportHtml: "",
  },
};

const LOG_LINE_LIMIT = 1400;

const STAGE_DEFS = [
  {
    id: "scout",
    label: "Scout",
    desc:
      "Map the archive, read indices, and propose a focused reading plan. Best-effort triage before deeper extraction.",
  },
  {
    id: "plan",
    label: "Plan",
    desc:
      "Translate scout notes into a concrete execution plan. Useful when you want the run steps documented explicitly.",
  },
  {
    id: "evidence",
    label: "Evidence",
    desc:
      "Read the key sources and extract structured evidence. This stage is the main bridge between raw documents and writing.",
  },
  {
    id: "writer",
    label: "Writer",
    desc:
      "Synthesize the evidence into the report body using the selected template, depth, and language constraints.",
  },
  {
    id: "quality",
    label: "Quality",
    desc:
      "Run critique/revision loops and structural repair. Helps with completeness but may add latency and token cost.",
  },
];

const STAGE_INDEX = Object.fromEntries(STAGE_DEFS.map((s, i) => [s.id, i]));

function isFederlichtActive() {
  return document.body?.dataset?.tab === "federlicht";
}

function isMissingFileError(err) {
  const msg = String(err?.message ?? err ?? "").toLowerCase();
  return msg.includes("404") && msg.includes("not found");
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (!theme || theme === "default") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
  localStorage.setItem("federnett-theme", theme || "default");
  const select = $("#theme-select");
  if (select && select.value !== theme) {
    select.value = theme || "default";
  }
}

function initTheme() {
  const saved = localStorage.getItem("federnett-theme") || "default";
  applyTheme(saved);
  $("#theme-select")?.addEventListener("change", (e) => {
    applyTheme(e.target.value);
  });
}

async function fetchJSON(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${text}`.trim());
  }
  return res.json();
}

function joinPath(a, b) {
  if (!a) return b || "";
  if (!b) return a;
  const left = a.replace(/[\\/]+$/, "");
  const right = b.replace(/^[\\/]+/, "");
  return `${left}/${right}`;
}

function toFileUrl(absPath) {
  const posix = absPath.replace(/\\/g, "/");
  return `file:///${posix}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function isElementInViewport(el) {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  const viewHeight = window.innerHeight || document.documentElement.clientHeight;
  return rect.top >= 0 && rect.bottom <= viewHeight;
}

function focusPanel(selector) {
  const el = document.querySelector(selector);
  if (!el) return;
  if (!isElementInViewport(el)) {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

const TEXT_PREVIEW_EXTS = new Set([
  ".txt",
  ".md",
  ".json",
  ".jsonl",
  ".yml",
  ".yaml",
  ".csv",
  ".tsv",
  ".html",
  ".css",
  ".js",
  ".ts",
  ".py",
  ".tex",
  ".log",
]);
const INSTRUCTION_EXTS = new Set([
  ".txt",
  ".md",
  ".text",
  ".prompt",
  ".instruct",
  ".instruction",
]);

function isTextPreviewable(path) {
  if (!path) return false;
  const lower = path.toLowerCase();
  const dot = lower.lastIndexOf(".");
  if (dot === -1) return true;
  return TEXT_PREVIEW_EXTS.has(lower.slice(dot));
}

function hasFileExtension(value) {
  const cleaned = normalizePathString(value);
  if (!cleaned) return false;
  const last = cleaned.split("/").pop() || "";
  const dot = last.lastIndexOf(".");
  if (dot <= 0) return false;
  const ext = last.slice(dot).toLowerCase();
  return INSTRUCTION_EXTS.has(ext) || Boolean(ext);
}

function rootAbs() {
  return state.info?.root_abs || "";
}

function toAbsPath(relPath) {
  const root = rootAbs();
  if (!root || !relPath) return "";
  return joinPath(root, relPath);
}

function toFileUrlFromRel(relPath) {
  const abs = toAbsPath(relPath);
  return abs ? toFileUrl(abs) : "";
}

function apiRawUrl(relPath) {
  if (!relPath) return "";
  return `/api/raw?path=${encodeURIComponent(relPath)}`;
}

function rawFileUrl(relPath) {
  const cleaned = String(relPath || "")
    .trim()
    .replaceAll("\\", "/")
    .replace(/^\//, "");
  if (!cleaned) return "";
  const encoded = cleaned
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `/raw/${encoded}`;
}

function openPath(relPath) {
  const url = toFileUrlFromRel(relPath);
  if (url) {
    window.open(url, "_blank");
  } else if (relPath) {
    appendLog(`[open] unable to resolve ${relPath}\n`);
  }
}

function openSaveAsModal(initialPath, mode = "preview") {
  const modal = $("#saveas-modal");
  const list = $("#saveas-list");
  const pathInput = $("#saveas-path");
  const filenameInput = $("#saveas-filename");
  if (!modal || !list || !pathInput || !filenameInput) return;
  state.saveAs.mode = mode || "preview";
  state.saveAs.open = true;
  if (initialPath) {
    state.saveAs.path = initialPath.replace(/\/[^/]*$/, "");
  } else {
    state.saveAs.path = "";
  }
  modal.classList.add("open");
  loadSaveAsDir(state.saveAs.path || "");
  filenameInput.value = "";
}

function closeSaveAsModal() {
  const modal = $("#saveas-modal");
  if (modal) modal.classList.remove("open");
  state.saveAs.open = false;
  state.saveAs.mode = "preview";
}

function openHelpModal() {
  const modal = $("#help-modal");
  if (!modal) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeHelpModal() {
  const modal = $("#help-modal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function openJobsModal() {
  const modal = $("#jobs-modal");
  if (!modal) return;
  const runRel = selectedRunRel();
  if (!runRel) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  const subtitle = $("#jobs-modal-subtitle");
  if (subtitle) {
    subtitle.textContent = runRel
      ? `Latest activity for ${runBaseName(runRel)}.`
      : "Select a run folder to view activity.";
  }
  renderJobs();
}

function closeJobsModal() {
  const modal = $("#jobs-modal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

async function loadSaveAsDir(relPath) {
  const list = $("#saveas-list");
  const pathInput = $("#saveas-path");
  if (!list || !pathInput) return;
  list.innerHTML = `<div class="modal-item muted">Loading...</div>`;
  try {
    const data = await fetchJSON(`/api/fs?path=${encodeURIComponent(relPath || "")}`);
    state.saveAs.path = data.path || "";
    pathInput.value = data.path || "";
    list.innerHTML = "";
    for (const entry of data.entries || []) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "modal-item";
      item.innerHTML = `<strong>${escapeHtml(entry.name)}</strong><small>${entry.is_dir ? "folder" : "file"}</small>`;
      item.addEventListener("click", () => {
        if (entry.is_dir) {
          loadSaveAsDir(entry.path);
        } else {
          const filenameInput = $("#saveas-filename");
          if (filenameInput) filenameInput.value = entry.name;
        }
      });
      list.appendChild(item);
    }
  } catch (err) {
    list.innerHTML = `<div class="modal-item muted">Failed to load folder: ${escapeHtml(String(err))}</div>`;
  }
}

function flashElement(el) {
  if (!el) return;
  el.classList.add("flash");
  window.setTimeout(() => el.classList.remove("flash"), 1200);
}

function formatDate(isoString) {
  if (!isoString) return "-";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString();
}

function setText(selector, value) {
  const el = $(selector);
  if (el) el.textContent = value ?? "";
}

function updateHeroStats() {
  const selected = selectedRunRel();
  const badge = selected ? runBaseName(selected) : "-";
  setText("#run-roots-badge", badge);
  setText("#run-count", String(state.runs.length || 0));
  setText("#template-count", String(state.templates.length || 0));
  updateRecentJobsCard();
}

function updateRecentJobsCard() {
  const card = $("#hero-card-recent");
  if (!card) return;
  const runRel = selectedRunRel();
  const subtitle = $("#recent-jobs-subtitle");
  if (subtitle) {
    subtitle.textContent = runRel
      ? `Latest activity for ${runBaseName(runRel)}.`
      : "Select a run folder to view activity.";
  }
  updateRecentJobsSummary();
}

function buildRecentJobs(runRel) {
  const history = runRel ? state.historyLogs[runRel] || [] : [];
  const historyJobs = history.map((entry) => ({
    job_id: `history:${entry.path}`,
    kind: entry.kind || "log",
    status: entry.status || "history",
    updated_at: entry.updated_at,
    run_rel: entry.run_rel,
    log_path: entry.path,
    label: entry.name || entry.path,
    source: "history",
  }));
  const liveJobs = state.jobs
    .filter((job) => !job.run_rel || !runRel || job.run_rel === runRel)
    .map((job) => ({ ...job, source: "live" }));
  return [...liveJobs, ...historyJobs].sort((a, b) => {
    const ta = a.updated_at ? Date.parse(a.updated_at) : a.started_at || 0;
    const tb = b.updated_at ? Date.parse(b.updated_at) : b.started_at || 0;
    return tb - ta;
  });
}

function updateRecentJobsSummary() {
  const runRel = selectedRunRel();
  const countEl = $("#recent-jobs-count");
  const lastEl = $("#recent-jobs-last");
  const openBtn = $("#jobs-open");
  if (!countEl || !lastEl) return;
  if (!runRel) {
    countEl.textContent = "0";
    lastEl.textContent = "No run selected.";
    if (openBtn) openBtn.disabled = true;
    return;
  }
  const jobs = buildRecentJobs(runRel);
  countEl.textContent = String(jobs.length || 0);
  if (!jobs.length) {
    lastEl.textContent = "No recent jobs.";
    if (openBtn) openBtn.disabled = true;
    return;
  }
  const top = jobs[0];
  const label = top.label || top.kind || "job";
  const status = top.status || "";
  lastEl.textContent = status ? `${label} · ${status}` : label;
  if (openBtn) openBtn.disabled = false;
}

function setMetaStrip() {
  const strip = $("#meta-strip");
  if (!strip || !state.info) return;
  const { run_roots: runRoots } = state.info;
  const runRootsLabel = formatRunRoots(runRoots || []);
  const pills = [`run root: ${runRootsLabel}`];
  strip.innerHTML = pills.map((p) => `<span class="meta-pill">${p}</span>`).join("");
  updateHeroStats();
}

function bindHeroCards() {
  if (!state.info) return;
  const runRootsCard = $("#hero-card-run-roots");
  const templatesCard = $("#hero-card-templates");
  const runsCard = $("#hero-card-runs");
  const runRoots = state.info.run_roots || [];
  const openRuns = () => {
    openRunPickerModal();
    loadRunPickerItems();
  };

  if (templatesCard) {
    templatesCard.addEventListener("click", () => {
      const panel = $("#templates-panel");
      if (panel) {
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
        flashElement(panel);
      }
    });
  }
  if (runsCard) {
    runsCard.addEventListener("click", openRuns);
  }
  if (runRootsCard) {
    runRootsCard.addEventListener("click", () => {
      openRuns();
      if (runRoots.length > 1) {
        appendLog(`[run-roots] available: ${runRoots.join(", ")}\n`);
      }
    });
  }
}

async function loadInfo() {
  state.info = await fetchJSON("/api/info");
  setMetaStrip();
}

function sortRuns(runs) {
  return [...runs].sort((a, b) => {
    const da = Date.parse(a.updated_at || "") || 0;
    const db = Date.parse(b.updated_at || "") || 0;
    return db - da;
  });
}

function makeRunOption(run) {
  const label = run.latest_report_name
    ? `${run.run_name}  (${run.latest_report_name})`
    : run.run_name;
  return `<option value="${run.run_rel}">${label}</option>`;
}

function ensureRunSelection(selectEl, fallbackRel) {
  if (!selectEl) return;
  const current = selectEl.value;
  const exists = state.runs.some((r) => r.run_rel === current);
  if (exists) return;
  const preferred =
    fallbackRel && state.runs.some((r) => r.run_rel === fallbackRel)
      ? fallbackRel
      : state.runs[0]?.run_rel;
  if (preferred) selectEl.value = preferred;
}

function defaultReportPath(runRel) {
  if (!runRel) return "";
  const runName = runBaseName(runRel);
  return `${runName}/report_full.html`;
}

function defaultPromptPath(runRel) {
  if (!runRel) return "";
  const runName = runBaseName(runRel);
  return `${runName}/instruction/generated_prompt_${runName}.txt`;
}

function siteRunsBase() {
  const siteRoot = state.info?.site_root ? String(state.info.site_root) : "site";
  return `${siteRoot.replace(/\/+$/, "")}/runs`;
}

function siteRunsPrefix() {
  return siteRunsBase().replace(/\/+$/, "");
}

function expandSiteRunsPath(value) {
  const cleaned = normalizePathString(value);
  if (!cleaned) return "";
  const base = siteRunsPrefix();
  if (cleaned.startsWith(`${base}/`)) return cleaned;
  const blockedPrefixes = ["site/", "examples/", "runs/", "instruction/"];
  if (blockedPrefixes.some((prefix) => cleaned.startsWith(prefix))) return cleaned;
  return `${base}/${cleaned}`;
}

function stripSiteRunsPrefix(value) {
  const cleaned = normalizePathString(value);
  if (!cleaned) return "";
  const base = siteRunsPrefix();
  if (cleaned === base) return "";
  if (cleaned.startsWith(`${base}/`)) return cleaned.slice(base.length + 1);
  return cleaned;
}

function inferRunRelFromPayload(payload) {
  if (!payload) return "";
  if (payload.run) {
    const rel = stripSiteRunsPrefix(payload.run);
    return rel || payload.run;
  }
  if (payload.output) {
    const rel = stripSiteRunsPrefix(payload.output);
    if (!rel) return "";
    return rel.replace(/\/[^/]+$/, "");
  }
  return "";
}

function formatRunRoots(runRoots) {
  if (!runRoots || runRoots.length === 0) return "-";
  const base = normalizePathString(siteRunsPrefix());
  const normalized = runRoots.map((root) => {
    const cleaned = normalizePathString(root);
    return cleaned === base ? "." : root;
  });
  if (normalized.length === 1 && normalized[0] === ".") return ".";
  return normalized.join(", ");
}

function runBaseName(runRel) {
  if (!runRel) return "run";
  const parts = runRel.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || "run";
}

function defaultInstructionPath(runRel) {
  if (!runRel) return "";
  const base = runBaseName(runRel);
  const normalizedRun = runRel.replaceAll("\\", "/");
  return `${normalizedRun}/instruction/${base}.txt`;
}

let reportOutputTouched = false;
let promptOutputTouched = false;
let featherOutputTouched = false;
let featherInputTouched = false;
let promptFileTouched = false;
let promptInlineTouched = false;

function refreshRunDependentFields() {
  const runRel = $("#run-select")?.value;
  const promptRunRel = $("#prompt-run-select")?.value;
  const output = $("#federlicht-output");
  const promptOutput = $("#prompt-output");
  const promptFile = $("#federlicht-prompt-file");
  if (runRel && output && !reportOutputTouched) {
    output.value = defaultReportPath(runRel);
  }
  if (runRel && promptFile && !promptFileTouched) {
    promptFile.value = defaultPromptPath(runRel);
  }
  if (promptRunRel && promptOutput && !promptOutputTouched) {
    promptOutput.value = defaultPromptPath(promptRunRel);
  }
  if (runRel && isFederlichtActive()) {
    syncPromptFromFile(false).catch((err) => {
      if (!isMissingFileError(err)) {
        appendLog(`[prompt] failed to load: ${err}\n`);
      }
    });
  }
}

function refreshRunSelectors() {
  const runSelect = $("#run-select");
  const promptRunSelect = $("#prompt-run-select");
  const instructionRunSelect = $("#instruction-run-select");
  if (!runSelect && !promptRunSelect && !instructionRunSelect) return;
  const currentRun = runSelect?.value;
  const currentPromptRun = promptRunSelect?.value;
  const currentInstructionRun = instructionRunSelect?.value;
  const options = state.runs.map(makeRunOption).join("");
  if (runSelect) runSelect.innerHTML = options;
  if (promptRunSelect) promptRunSelect.innerHTML = options;
  if (instructionRunSelect) instructionRunSelect.innerHTML = options;
  if (runSelect) ensureRunSelection(runSelect, currentRun);
  if (promptRunSelect) {
    ensureRunSelection(promptRunSelect, currentPromptRun || runSelect?.value);
    if (!promptRunSelect.value && runSelect?.value) {
      promptRunSelect.value = runSelect.value;
    }
  }
  if (instructionRunSelect) {
    ensureRunSelection(instructionRunSelect, currentInstructionRun || runSelect?.value);
    if (!instructionRunSelect.value && runSelect?.value) {
      instructionRunSelect.value = runSelect.value;
    }
  }
  refreshRunDependentFields();
}

async function loadRuns() {
  const runs = await fetchJSON("/api/runs");
  state.runs = sortRuns(runs);
  refreshRunSelectors();
  updateHeroStats();
  renderRunHistory();
  const runRel = selectedRunRel();
  if (runRel) {
    await updateRunStudio(runRel).catch((err) => {
      appendLog(`[studio] failed to update run studio: ${err}\n`);
    });
  }
  appendLog(`[runs] loaded ${state.runs.length} run folders\n`);
}

function selectedRunRel() {
  return $("#run-select")?.value || "";
}

function setStudioMeta(runRel, updatedAt) {
  setText("#studio-run-rel", runRel || "-");
  setText("#studio-updated", updatedAt ? `updated ${formatDate(updatedAt)}` : "-");
}

function updateFilePreviewState(patch) {
  state.filePreview = { ...state.filePreview, ...patch };
  renderFilePreview();
}

function revokePreviewObjectUrl() {
  if (state.filePreview.objectUrl) {
    URL.revokeObjectURL(state.filePreview.objectUrl);
  }
}

function renderFilePreview() {
  const pathEl = $("#file-preview-path");
  const statusEl = $("#file-preview-status");
  const editor = $("#file-preview-editor");
  const markdown = $("#file-preview-markdown");
  const frame = $("#file-preview-frame");
  const image = $("#file-preview-image");
  const saveBtn = $("#file-preview-save");
  const saveAsBtn = $("#file-preview-saveas");
  const canvasBtn = $("#file-preview-canvas");
  if (pathEl) pathEl.textContent = state.filePreview.path || "No file selected";
  if (statusEl) {
    if (!state.filePreview.canEdit) {
      statusEl.textContent = "read-only";
    } else {
      statusEl.textContent = state.filePreview.dirty ? "modified" : "";
    }
  }
  if (saveBtn) saveBtn.disabled = !state.filePreview.canEdit;
  if (saveAsBtn) saveAsBtn.disabled = !state.filePreview.canEdit;
  if (canvasBtn) {
    const mode = state.filePreview.mode || "text";
    const canCanvas =
      !!state.filePreview.path && (mode === "html" || mode === "markdown" || mode === "text");
    canvasBtn.disabled = !canCanvas;
  }
  if (!editor || !markdown || !frame || !image) return;
  const mode = state.filePreview.mode || "text";
  editor.style.display = "none";
  markdown.style.display = "none";
  frame.style.display = "none";
  image.style.display = "none";
  if (mode === "markdown") {
    markdown.innerHTML = renderMarkdown(state.filePreview.content || "");
    markdown.style.display = "block";
  } else if (mode === "html" || mode === "pdf") {
    frame.removeAttribute("srcdoc");
    if (state.filePreview.htmlDoc && mode === "html") {
      frame.removeAttribute("src");
      frame.srcdoc = state.filePreview.htmlDoc;
    } else {
      frame.src = rawFileUrl(state.filePreview.path);
    }
    frame.style.display = "block";
  } else if (mode === "image") {
    image.src = rawFileUrl(state.filePreview.path);
    image.style.display = "block";
  } else if (mode === "binary") {
    markdown.innerHTML =
      "<p><strong>Unsupported preview format.</strong> Use Open to download or open the file in another app.</p>";
    markdown.style.display = "block";
  } else {
    editor.value = state.filePreview.content || "";
    editor.readOnly = !state.filePreview.canEdit;
    editor.wrap = "soft";
    editor.style.display = "block";
  }
}

function appendTemplateGenLog(text) {
  const el = $("#template-gen-log");
  if (!el) return;
  const line = String(text || "");
  state.templateGen.log = (state.templateGen.log + line).slice(-4000);
  el.textContent = state.templateGen.log || "Ready.";
  el.scrollTop = el.scrollHeight;
}

function renderMarkdown(text) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let inList = false;
  let inCode = false;
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith("```")) {
      if (!inCode) {
        if (inList) {
          html += "</ul>";
          inList = false;
        }
        html += "<pre><code>";
        inCode = true;
      } else {
        html += "</code></pre>";
        inCode = false;
      }
      continue;
    }
    if (inCode) {
      html += `${escapeHtml(raw)}\n`;
      continue;
    }
    if (!line) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      continue;
    }
    if (line.startsWith("#")) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      const level = Math.min(line.match(/^#+/)[0].length, 3);
      const text = line.replace(/^#+\s*/, "");
      html += `<h${level}>${escapeHtml(text)}</h${level}>`;
      continue;
    }
    if (line.startsWith("- ") || line.startsWith("* ")) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${escapeHtml(line.slice(2))}</li>`;
      continue;
    }
    if (inList) {
      html += "</ul>";
      inList = false;
    }
    html += `<p>${escapeHtml(line)}</p>`;
  }
  if (inList) html += "</ul>";
  if (inCode) html += "</code></pre>";
  return html;
}

function previewModeForPath(relPath) {
  const lower = String(relPath || "").toLowerCase();
  if (lower.endsWith(".pdf")) return "pdf";
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  if (lower.endsWith(".md")) return "markdown";
  if (lower.match(/\.(png|jpg|jpeg|gif|svg)$/)) return "image";
  if (isTextPreviewable(relPath)) return "text";
  return "binary";
}

async function fetchRawPreviewBlob(relPath) {
  const res = await fetch(apiRawUrl(relPath));
  const contentType = res.headers.get("content-type") || "";
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    if (contentType.includes("application/json")) {
      try {
        const payload = await res.json();
        if (payload?.error) detail = payload.error;
      } catch (err) {
        // ignore
      }
    }
    throw new Error(detail);
  }
  if (contentType.includes("application/json")) {
    const payload = await res.json();
    throw new Error(payload?.error || "unknown_endpoint");
  }
  const blob = await res.blob();
  return { blob, contentType };
}

async function loadFilePreview(relPath) {
  if (!relPath) return;
  revokePreviewObjectUrl();
  const mode = previewModeForPath(relPath);
  if (mode === "pdf" || mode === "html" || mode === "image") {
    updateFilePreviewState({
      path: relPath,
      content: "",
      canEdit: false,
      dirty: false,
      mode,
      objectUrl: "",
      htmlDoc: "",
    });
    focusPanel("#logs-wrap .preview-block");
    return;
  }
  if (mode === "binary") {
    updateFilePreviewState({
      path: relPath,
      content: "",
      canEdit: false,
      dirty: false,
      mode,
      objectUrl: "",
      htmlDoc: "",
    });
    focusPanel("#logs-wrap .preview-block");
    return;
  }
  try {
    const data = await fetchJSON(`/api/files?path=${encodeURIComponent(relPath)}`);
    const canEdit = mode === "text";
    updateFilePreviewState({
      path: data.path || relPath,
      content: data.content || "",
      canEdit,
      dirty: false,
      mode,
      objectUrl: "",
      htmlDoc: "",
    });
    focusPanel("#logs-wrap .preview-block");
  } catch (err) {
    updateFilePreviewState({
      path: relPath,
      content: `Failed to load file: ${err}`,
      canEdit: false,
      dirty: false,
      mode: "text",
      objectUrl: "",
      htmlDoc: "",
    });
    focusPanel("#logs-wrap .preview-block");
  }
}

function stripRunPrefix(pathValue, runRel) {
  const cleaned = normalizePathString(pathValue);
  const runPath = normalizePathString(runRel);
  if (runPath && cleaned.startsWith(`${runPath}/`)) {
    return cleaned.slice(runPath.length + 1);
  }
  return cleaned;
}

function inferRunRelFromPath(relPath) {
  const cleaned = normalizePathString(relPath);
  const runRoots = state.info?.run_roots || [];
  for (const root of runRoots) {
    const prefix = normalizePathString(root);
    if (!prefix) continue;
    if (cleaned.startsWith(`${prefix}/`)) {
      const rest = cleaned.slice(prefix.length + 1);
      const head = rest.split("/")[0];
      if (head) return `${prefix}/${head}`;
    }
  }
  return selectedRunRel();
}

function extractTextFromHtml(html) {
  const temp = document.createElement("div");
  temp.innerHTML = html || "";
  let text = temp.textContent || "";
  text = text.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  return text;
}

function truncateSelection(text, maxChars = 4000) {
  if (!text) return "";
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 1)}…`;
}

function guessNextReportPathFromBase(basePath) {
  if (!basePath) return "";
  const cleaned = normalizePathString(basePath);
  const match = cleaned.match(/^(.*\/)?report_full(?:_(\d+))?\.html$/);
  if (!match) return "";
  const prefix = match[1] || "";
  const idx = Number.parseInt(match[2] || "0", 10);
  const next = Number.isFinite(idx) ? idx + 1 : 1;
  return `${prefix}report_full_${next}.html`;
}

function setCanvasStatus(text) {
  const el = $("#canvas-status");
  if (el) el.textContent = text || "";
}

function updateCanvasFields() {
  const baseInput = $("#canvas-base-path");
  const outputInput = $("#canvas-output-path");
  const updatePathInput = $("#canvas-update-path");
  const selection = $("#canvas-selection");
  const textArea = $("#canvas-report-text");
  const runPill = $("#canvas-run-rel");
  const basePill = $("#canvas-base-rel");
  const frame = $("#canvas-preview-frame");
  if (baseInput) baseInput.value = state.canvas.basePath || "";
  if (outputInput && state.canvas.outputPath) outputInput.value = state.canvas.outputPath;
  if (updatePathInput && state.canvas.updatePath) updatePathInput.value = state.canvas.updatePath;
  if (selection) selection.value = state.canvas.selection || "";
  if (textArea) textArea.value = state.canvas.reportText || "";
  if (runPill) runPill.textContent = state.canvas.runRel ? `run: ${state.canvas.runRel}` : "-";
  if (basePill) {
    basePill.textContent = state.canvas.baseRel ? `base: ${state.canvas.baseRel}` : "-";
  }
  if (frame && state.canvas.basePath) {
    frame.src = rawFileUrl(state.canvas.basePath);
  }
}

async function loadCanvasReport(relPath) {
  if (!relPath) return;
  setCanvasStatus("Loading report...");
  try {
    const data = await fetchJSON(`/api/files?path=${encodeURIComponent(relPath)}`);
    const content = data.content || "";
    const mode = previewModeForPath(relPath);
    let text = content;
    if (mode === "html") {
      text = extractTextFromHtml(content);
    }
    state.canvas.reportText = text;
    state.canvas.reportHtml = content;
    updateCanvasFields();
    setCanvasStatus("Ready");
  } catch (err) {
    setCanvasStatus(`Failed to load report: ${err}`);
  }
}

async function nextUpdateRequestPath(runRel) {
  if (!runRel) return "";
  const now = new Date();
  const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(
    now.getDate(),
  ).padStart(2, "0")}`;
  const dir = joinPath(runRel, "report_notes");
  let existing = [];
  try {
    const listing = await fetchJSON(`/api/fs?path=${encodeURIComponent(dir)}`);
    existing = (listing.entries || []).map((entry) => entry.name);
  } catch (err) {
    existing = [];
  }
  let name = `update_request_${stamp}.txt`;
  if (existing.includes(name)) {
    let idx = 1;
    while (existing.includes(`update_request_${stamp}_${idx}.txt`)) {
      idx += 1;
    }
    name = `update_request_${stamp}_${idx}.txt`;
  }
  return `${dir}/${name}`;
}

function buildUpdatePromptContent({ updateText, secondPrompt, baseRel, selection }) {
  const lines = ["Update request:"];
  if (updateText) lines.push(updateText.trim());
  if (selection) {
    lines.push("");
    lines.push("Target excerpt:");
    lines.push("<<<");
    lines.push(selection.trim());
    lines.push(">>>");
  }
  if (secondPrompt) {
    lines.push("");
    lines.push("Second prompt:");
    lines.push(secondPrompt.trim());
  }
  lines.push("");
  lines.push(`Base report: ${baseRel || ""}`);
  lines.push("");
  lines.push("Instructions:");
  lines.push("- Read the base report file and keep its structure unless the update requests a change.");
  lines.push("- Apply only the requested edits; avoid rewriting everything from scratch.");
  lines.push("- Preserve citations and update them only if you change the referenced content.");
  if (selection) {
    lines.push("- Limit edits to the target excerpt unless the update requests broader changes.");
  }
  return lines.join("\n");
}

async function openCanvasModal(relPath) {
  const modal = $("#canvas-modal");
  if (!modal) return;
  const basePath = relPath || state.filePreview.path;
  if (!basePath) {
    appendLog("[canvas] select a report file first.\n");
    return;
  }
  const runRel = inferRunRelFromPath(basePath);
  if (runRel && $("#run-select") && $("#run-select").value !== runRel) {
    $("#run-select").value = runRel;
    refreshRunDependentFields();
    await updateRunStudio(runRel).catch(() => {});
  }
  const baseRel = stripRunPrefix(basePath, runRel);
  const outputPath =
    nextReportPath(state.runSummary) ||
    guessNextReportPathFromBase(basePath) ||
    joinPath(runRel, "report_full.html");
  state.canvas = {
    ...state.canvas,
    open: true,
    runRel: runRel || "",
    basePath,
    baseRel,
    outputPath,
    selection: "",
    updatePath: "",
  };
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  setCanvasStatus("Ready");
  updateCanvasFields();
  await loadCanvasReport(basePath);
  state.canvas.updatePath = await nextUpdateRequestPath(runRel);
  updateCanvasFields();
}

function closeCanvasModal() {
  const modal = $("#canvas-modal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  state.canvas.open = false;
}

function syncCanvasSelection() {
  const textArea = $("#canvas-report-text");
  if (!textArea) return;
  const start = textArea.selectionStart || 0;
  const end = textArea.selectionEnd || 0;
  if (start === end) {
    appendLog("[canvas] select text in the report area first.\n");
    return;
  }
  const raw = textArea.value.slice(start, end);
  const trimmed = truncateSelection(raw.trim());
  state.canvas.selection = trimmed;
  updateCanvasFields();
}

async function runCanvasUpdate() {
  const updateText = $("#canvas-update")?.value?.trim();
  if (!updateText) {
    appendLog("[canvas] update instructions are required.\n");
    return;
  }
  const secondPrompt = $("#canvas-second")?.value?.trim();
  const selection = $("#canvas-selection")?.value?.trim();
  const baseRel = state.canvas.baseRel || "";
  const runRel = state.canvas.runRel || selectedRunRel();
  if (!runRel) {
    appendLog("[canvas] run folder not resolved.\n");
    return;
  }
  let outputPath = $("#canvas-output-path")?.value?.trim() || state.canvas.outputPath;
  if (!outputPath) {
    outputPath = nextReportPath(state.runSummary);
  }
  if (!outputPath) {
    appendLog("[canvas] output path is required.\n");
    return;
  }
  let updatePath = $("#canvas-update-path")?.value?.trim() || state.canvas.updatePath;
  if (!updatePath) {
    updatePath = await nextUpdateRequestPath(runRel);
  }
  if (!updatePath) {
    appendLog("[canvas] update prompt path is required.\n");
    return;
  }
  const content = buildUpdatePromptContent({
    updateText,
    secondPrompt,
    baseRel,
    selection,
  });
  try {
    await fetchJSON("/api/files", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: updatePath, content }),
    });
    state.canvas.updatePath = updatePath;
    updateCanvasFields();
    setCanvasStatus("Update prompt saved.");
  } catch (err) {
    appendLog(`[canvas] failed to write update prompt: ${err}\n`);
    return;
  }
  const payload = buildFederlichtPayload();
  payload.run = runRel;
  payload.output = expandSiteRunsPath(outputPath);
  payload.prompt_file = expandSiteRunsPath(updatePath);
  delete payload.prompt;
  const cleanPayload = pruneEmpty(payload);
  setCanvasStatus("Running update...");
  await startJob("/api/federlicht/start", cleanPayload, {
    kind: "federlicht",
    onSuccess: async () => {
      await loadRuns().catch(() => {});
      if (runRel && $("#run-select")) {
        $("#run-select").value = runRel;
        refreshRunDependentFields();
        await updateRunStudio(runRel).catch(() => {});
      }
      setCanvasStatus("Update started.");
    },
    onDone: () => {
      setCanvasStatus("Ready");
    },
  });
}

async function saveFilePreview(targetPath) {
  const relPath = targetPath || state.filePreview.path;
  const editor = $("#file-preview-editor");
  if (!relPath || !editor || !state.filePreview.canEdit) return;
  const payload = { path: relPath, content: editor.value || "" };
  await fetchJSON("/api/files", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  updateFilePreviewState({ path: relPath, content: editor.value || "", dirty: false, canEdit: true });
  await loadRunSummary(selectedRunRel());
}

function renderRunFiles(summary) {
  const host = $("#run-file-list");
  if (!host) return;
  const groups = [
    { title: "Reports", files: summary?.report_files || [] },
    { title: "Index Files", files: summary?.index_files || [] },
    { title: "Archive PDFs", files: summary?.pdf_files || [] },
    { title: "Archive PPTX", files: summary?.pptx_files || [] },
    { title: "Web Extracts", files: summary?.extract_files || [] },
    { title: "Archive Texts", files: summary?.text_files || [] },
    { title: "Logs", files: summary?.log_files || [] },
    {
      title: "Instructions",
      files: (summary?.instruction_files || []).map((f) => f.path),
    },
  ];
  const hasAny = groups.some((g) => g.files && g.files.length);
  if (!hasAny) {
    host.innerHTML = `<span class="muted">No files to preview.</span>`;
    return;
  }
  host.innerHTML = groups
    .filter((group) => group.files && group.files.length)
    .map((group) => {
      const items = group.files
        .map((rel) => {
          const name = rel.split("/").pop() || rel;
          return `<button type="button" data-file="${escapeHtml(rel)}">${escapeHtml(name)}</button>`;
        })
        .join("");
      return `
        <div class="file-group">
          <div class="file-group-title">${escapeHtml(group.title)}</div>
          <div class="file-group-items">${items}</div>
        </div>
      `;
    })
    .join("");
  host.querySelectorAll("button[data-file]").forEach((btn) => {
    btn.addEventListener("click", () => loadFilePreview(btn.dataset.file));
  });
}

function renderRunSummary(summary) {
  state.runSummary = summary;
  setStudioMeta(summary?.run_rel, summary?.updated_at);
  const trashBtn = $("#run-trash");
  if (trashBtn) {
    trashBtn.disabled = !summary?.run_rel;
    trashBtn.onclick = () => {
      if (!summary?.run_rel) return;
      trashRun(summary.run_rel);
    };
  }
  const linesHost = $("#run-summary-lines");
  if (linesHost) {
    const lines = summary?.summary_lines || [];
    linesHost.innerHTML = lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("");
  }
  const linksHost = $("#run-summary-links");
  if (linksHost) {
    const links = [];
    if (summary?.run_rel) {
      const url = toFileUrlFromRel(summary.run_rel);
      if (url) links.push(`<a href="${url}" target="_blank" rel="noreferrer">Run Folder</a>`);
    }
    if (summary?.latest_report_rel) {
      const name = summary.latest_report_rel.split("/").pop() || summary.latest_report_rel;
      links.push(
        `<button type="button" class="summary-chip" data-file="${escapeHtml(summary.latest_report_rel)}">${escapeHtml(
          `Latest Report (${name})`,
        )}</button>`,
      );
    }
    linksHost.innerHTML = links.join("");
    linksHost.querySelectorAll("button[data-file]").forEach((btn) => {
      btn.addEventListener("click", () => loadFilePreview(btn.dataset.file));
    });
  }
  const reportsHost = $("#run-summary-reports");
  if (reportsHost) {
    const reportLinks = (summary?.report_files || []).slice(-8).reverse();
    const indexLinks = (summary?.index_files || []).slice(0, 6);
    const parts = [];
    if (reportLinks.length) {
      const items = reportLinks
        .map((rel) => {
          const name = rel.split("/").pop() || rel;
          return `<button type="button" class="summary-chip" data-file="${escapeHtml(
            rel,
          )}">${escapeHtml(name)}</button>`;
        })
        .join("");
      parts.push(`<div class="summary-reports">${items}</div>`);
    }
    if (indexLinks.length) {
      const items = indexLinks
        .map((rel) => {
          const name = rel.split("/").pop() || rel;
          return `<button type="button" class="summary-chip" data-file="${escapeHtml(
            rel,
          )}">${escapeHtml(name)}</button>`;
        })
        .join("");
      parts.push(`<div class="summary-links">${items}</div>`);
    }
    reportsHost.innerHTML = parts.join("");
    reportsHost.querySelectorAll("button[data-file]").forEach((btn) => {
      btn.addEventListener("click", () => loadFilePreview(btn.dataset.file));
    });
  }
  renderRunFiles(summary);
  applyRunSettings(summary);
}

async function trashRun(runRel) {
  if (!runRel) return;
  const ok = confirm(`Move run folder to trash?\n${runRel}`);
  if (!ok) return;
  try {
    const payload = { run: runRel };
    const result = await fetchJSON("/api/runs/trash", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    appendLog(`[runs] trashed ${runRel} -> ${result?.trash_rel || "trash"}\n`);
    await loadRuns();
  } catch (err) {
    appendLog(`[runs] trash failed: ${err}\n`);
  }
}

function nextReportPath(summary) {
  const runRel = summary?.run_rel;
  if (!runRel) return "";
  const files = summary?.report_files || [];
  let maxIndex = -1;
  let hasBase = false;
  files.forEach((rel) => {
    const name = rel.split("/").pop() || "";
    if (name === "report_full.html") {
      hasBase = true;
      maxIndex = Math.max(maxIndex, 0);
      return;
    }
    const match = name.match(/^report_full_(\d+)\.html$/);
    if (match) {
      const idx = Number.parseInt(match[1], 10);
      if (Number.isFinite(idx)) maxIndex = Math.max(maxIndex, idx);
    }
  });
  if (!hasBase && maxIndex < 0) {
    return `${runRel}/report_full.html`;
  }
  const next = maxIndex + 1;
  return `${runRel}/report_full_${next}.html`;
}

async function loadRunSummary(runRel) {
  if (!runRel) return;
  const summary = await fetchJSON(`/api/run-summary?run=${encodeURIComponent(runRel)}`);
  renderRunSummary(summary);
}

async function loadRunLogs(runRel) {
  if (!runRel) return;
  const logs = await fetchJSON(`/api/run-logs?run=${encodeURIComponent(runRel)}`);
  state.historyLogs[runRel] = Array.isArray(logs) ? logs : [];
  renderJobs();
}

function renderInstructionFiles(runRel) {
  const files = state.instructionFiles[runRel] || [];
  const fileSelect = $("#instruction-file-select");
  if (!fileSelect) return;
  const current = fileSelect.value;
  const defaultPath = defaultInstructionPath(runRel);
  const existingPaths = files.map((f) => f.path);
  const hasDefault = defaultPath && files.some((f) => f.path === defaultPath);
  const scopedLabel = (f) => {
    const scope = f.scope ? `[${f.scope}] ` : "";
    const tail = f.path || f.name || "";
    return `${scope}${tail}`;
  };
  const opts = files.map(
    (f) => `<option value="${f.path}">${escapeHtml(scopedLabel(f))}</option>`,
  );
  if (defaultPath && !hasDefault) {
    opts.unshift(
      `<option value="${defaultPath}">[new] ${escapeHtml(defaultPath)}</option>`,
    );
  }
  fileSelect.innerHTML = opts.join("");
  if (existingPaths.includes(current)) {
    fileSelect.value = current;
  }
  if (!fileSelect.value) {
    const preferred =
      files.find((f) => f.scope === "run")?.path || files[0]?.path || "";
    if (preferred) {
      fileSelect.value = preferred;
    } else if (defaultPath) {
      fileSelect.value = defaultPath;
    }
  }
}

async function loadInstructionFiles(runRel) {
  if (!runRel) return;
  const files = await fetchJSON(
    `/api/run-instructions?run=${encodeURIComponent(runRel)}`,
  );
  state.instructionFiles[runRel] = files;
  renderInstructionFiles(runRel);
  const newPath = $("#instruction-new-path");
  if (newPath && !newPath.value.trim()) {
    newPath.value = defaultInstructionPath(runRel);
  }
  const selectedPath = $("#instruction-file-select")?.value;
  const exists = files.some((f) => f.path === selectedPath);
  if (selectedPath && exists) {
    await loadInstructionContent(selectedPath).catch((err) => {
      appendLog(`[instruction] failed to load content: ${err}\n`);
    });
  } else {
    const editor = $("#instruction-editor");
    if (editor) {
      editor.value = "";
      editor.dataset.path = "";
    }
  }
}

async function loadInstructionContent(pathRel) {
  if (!pathRel) return;
  const payload = await fetchJSON(`/api/files?path=${encodeURIComponent(pathRel)}`);
  const editor = $("#instruction-editor");
  if (editor) {
    editor.value = payload.content || "";
    editor.dataset.path = payload.path || pathRel;
  }
}

async function loadFeatherInstructionContent(pathRel) {
  if (!pathRel) return;
  const payload = await fetchJSON(`/api/files?path=${encodeURIComponent(pathRel)}`);
  const editor = $("#feather-query");
  if (editor) {
    editor.value = payload.content || "";
    editor.dataset.path = payload.path || pathRel;
    editor.dataset.original = payload.content || "";
  }
}

async function loadFederlichtPromptContent(pathRel, opts = {}) {
  if (!pathRel) return;
  const force = Boolean(opts.force);
  if (!force && isPromptDirty()) return;
  let payload;
  try {
    payload = await fetchJSON(`/api/files?path=${encodeURIComponent(pathRel)}`);
  } catch (err) {
    if (isMissingFileError(err)) {
      const editor = $("#federlicht-prompt");
      if (editor) {
        editor.value = "";
        editor.dataset.path = pathRel;
        editor.dataset.original = "";
        promptInlineTouched = false;
      }
      return;
    }
    throw err;
  }
  const editor = $("#federlicht-prompt");
  if (editor) {
    editor.value = payload.content || "";
    editor.dataset.path = payload.path || pathRel;
    editor.dataset.original = payload.content || "";
    promptInlineTouched = false;
  }
}

function isFeatherInstructionDirty() {
  const editor = $("#feather-query");
  if (!editor) return false;
  const original = editor.dataset.original ?? "";
  return (editor.value || "") !== original;
}

function setFeatherInstructionSnapshot(pathRel, content) {
  const editor = $("#feather-query");
  if (!editor) return;
  editor.dataset.path = pathRel || "";
  editor.dataset.original = content || "";
}

function isPromptDirty() {
  const editor = $("#federlicht-prompt");
  if (!editor) return false;
  const original = editor.dataset.original ?? "";
  return (editor.value || "") !== original;
}

function setPromptSnapshot(pathRel, content) {
  const editor = $("#federlicht-prompt");
  if (!editor) return;
  editor.dataset.path = pathRel || "";
  editor.dataset.original = content || "";
  promptInlineTouched = false;
}

function normalizePromptPath(rawPath) {
  const runRel = $("#run-select")?.value;
  if (runRel) return expandSiteRunsPath(normalizeInstructionPath(runRel, rawPath || ""));
  let cleaned = (rawPath || "").trim().replaceAll("\\", "/");
  if (!cleaned) cleaned = "instruction/prompt.txt";
  cleaned = cleaned.replace(/^\/+/, "");
  if (cleaned.endsWith("/")) cleaned = `${cleaned}prompt.txt`;
  if (!hasFileExtension(cleaned)) cleaned = `${cleaned}.txt`;
  return expandSiteRunsPath(cleaned);
}

async function savePromptContent(pathRel, content) {
  if (!pathRel) throw new Error("Prompt path is required.");
  await fetchJSON("/api/files", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: pathRel, content: content || "" }),
  });
  appendLog(`[prompt] saved ${pathRel}\n`);
  setPromptSnapshot(pathRel, content || "");
}

async function syncPromptFromFile(force = false) {
  const rawPath = $("#federlicht-prompt-file")?.value?.trim();
  const pathRel = rawPath ? expandSiteRunsPath(rawPath) : rawPath;
  if (!pathRel) return;
  if (!force && promptInlineTouched) return;
  await loadFederlichtPromptContent(pathRel, { force });
}

function normalizeInstructionPath(runRel, rawPath) {
  const base = runBaseName(runRel);
  const fallback = defaultInstructionPath(runRel) || `instruction/${base}.txt`;
  let cleaned = (rawPath || "").trim().replaceAll("\\", "/");
  if (!cleaned) cleaned = fallback;
  cleaned = cleaned.replace(/^\/+/, "");
  if (cleaned.endsWith("/")) {
    cleaned = `${cleaned}${base}.txt`;
  }
  const last = cleaned.split("/").pop() || "";
  if (last && !hasFileExtension(last)) cleaned = `${cleaned}.txt`;
  return cleaned;
}

function pickInstructionRunRel() {
  const explicit = $("#feather-output")?.value?.trim();
  if (explicit) return normalizePathString(explicit);
  const selected = $("#run-select")?.value;
  if (selected) return selected;
  return state.runs[0]?.run_rel || "";
}

function normalizeFeatherInstructionPath(rawPath) {
  const runRel = pickInstructionRunRel();
  if (runRel) return expandSiteRunsPath(normalizeInstructionPath(runRel, rawPath));
  let cleaned = (rawPath || "").trim().replaceAll("\\", "/");
  if (!cleaned) cleaned = "instruction/new_instruction.txt";
  cleaned = cleaned.replace(/^\/+/, "");
  if (cleaned.endsWith("/")) cleaned = `${cleaned}instruction.txt`;
  if (!hasFileExtension(cleaned)) cleaned = `${cleaned}.txt`;
  return expandSiteRunsPath(cleaned);
}

function normalizePathString(value) {
  return (value || "").trim().replaceAll("\\", "/").replace(/\/+$/, "");
}

function parentPath(value) {
  const cleaned = normalizePathString(value);
  if (!cleaned || !cleaned.includes("/")) return "";
  return cleaned.split("/").slice(0, -1).join("/");
}

async function saveInstructionContent(pathRel, content) {
  if (!pathRel) throw new Error("Instruction path is required.");
  await fetchJSON("/api/files", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: pathRel, content: content || "" }),
  });
  appendLog(`[instruction] saved ${pathRel}\n`);
}

function openInstructionModal(mode = "feather") {
  state.instructionModal.mode = mode;
  const modal = $("#instruction-modal");
  if (!modal) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function openRunPickerModal() {
  const modal = $("#run-picker-modal");
  if (!modal) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeRunPickerModal() {
  const modal = $("#run-picker-modal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function closeInstructionModal() {
  const modal = $("#instruction-modal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function renderInstructionModalList() {
  const host = $("#instruction-list");
  if (!host) return;
  const items = state.instructionModal.filtered.length
    ? state.instructionModal.filtered
    : state.instructionModal.items;
  if (!items.length) {
    host.innerHTML = `<div class="modal-item"><strong>No instruction files</strong><small>Create a new path below.</small></div>`;
    return;
  }
  host.innerHTML = items
    .map((item) => {
      const active = item.path === state.instructionModal.selectedPath ? "active" : "";
      const scope = item.scope ? `[${item.scope}] ` : "";
      return `
        <div class="modal-item ${active}" data-instruction-item="${item.path}">
          <strong>${escapeHtml(scope + item.name)}</strong>
          <small>${escapeHtml(item.path)}</small>
        </div>
      `;
    })
    .join("");
  host.querySelectorAll("[data-instruction-item]").forEach((el) => {
    el.addEventListener("click", () => {
      const path = el.getAttribute("data-instruction-item");
      if (!path) return;
      state.instructionModal.selectedPath = path;
      const saveAs = $("#instruction-saveas");
      if (saveAs) saveAs.value = path;
      renderInstructionModalList();
    });
  });
}

function runPickerItems() {
  return state.runs || [];
}

function renderRunPickerList() {
  const host = $("#run-picker-list");
  if (!host) return;
  const items = state.runPicker.filtered.length
    ? state.runPicker.filtered
    : state.runPicker.items;
  if (!items.length) {
    host.innerHTML = `<div class="modal-item"><strong>No runs found</strong><small>Use Feather to create a run in site/runs.</small></div>`;
    return;
  }
  host.innerHTML = items
    .map((item) => {
      const active = item.run_rel === state.runPicker.selected ? "active" : "";
      const label = item.run_rel || item.run_name || "";
      return `
        <div class="modal-item ${active}" data-runpicker-item="${label}">
          <strong>${escapeHtml(item.run_name || label)}</strong>
          <small>${escapeHtml(label)}</small>
        </div>
      `;
    })
    .join("");
  host.querySelectorAll("[data-runpicker-item]").forEach((el) => {
    el.addEventListener("click", () => {
      const rel = el.getAttribute("data-runpicker-item");
      if (!rel) return;
      state.runPicker.selected = rel;
      renderRunPickerList();
    });
  });
}

async function loadRunPickerItems() {
  state.runPicker.items = runPickerItems();
  state.runPicker.filtered = [];
  state.runPicker.selected = state.runPicker.items[0]?.run_rel || "";
  renderRunPickerList();
}

async function loadInstructionModalItems() {
  const mode = state.instructionModal.mode || "feather";
  const runRel =
    mode === "prompt" ? $("#run-select")?.value || "" : pickInstructionRunRel();
  state.instructionModal.runRel = runRel;
  if (!runRel) {
    state.instructionModal.items = [];
    renderInstructionModalList();
    return;
  }
  try {
    const items = await fetchJSON(
      `/api/run-instructions?run=${encodeURIComponent(runRel)}`,
    );
    state.instructionModal.items = items || [];
    state.instructionModal.filtered = [];
    state.instructionModal.selectedPath = items?.[0]?.path || "";
    const saveAs = $("#instruction-saveas");
    if (saveAs && !saveAs.value.trim()) {
      saveAs.value =
        mode === "prompt" ? defaultPromptPath(runRel) : defaultInstructionPath(runRel);
    }
    renderInstructionModalList();
  } catch (err) {
    appendLog(`[instruction] modal load failed: ${err}\n`);
    state.instructionModal.items = [];
    state.instructionModal.filtered = [];
    renderInstructionModalList();
  }
}

async function saveInstruction(runRel) {
  const editor = $("#instruction-editor");
  if (!editor) return;
  const basePath = editor.dataset.path || "";
  const newPathRaw = $("#instruction-new-path")?.value;
  const targetPath = normalizeInstructionPath(runRel, newPathRaw || basePath);
  if (!targetPath) {
    throw new Error("Instruction path is required.");
  }
  await saveInstructionContent(targetPath, editor.value || "");
  const newPath = $("#instruction-new-path");
  if (newPath) newPath.value = targetPath;
  await loadInstructionFiles(runRel);
  await loadRunSummary(runRel);
}

async function updateRunStudio(runRel) {
  await Promise.all([loadRunSummary(runRel), loadInstructionFiles(runRel), loadRunLogs(runRel)]);
}


function refreshTemplateSelectors() {
  const templateSelect = $("#template-select");
  const promptTemplateSelect = $("#prompt-template-select");
  if (!templateSelect && !promptTemplateSelect) return;
  const currentTemplate = templateSelect?.value;
  const currentPromptTemplate = promptTemplateSelect?.value;
  const options = state.templates
    .map((t) => {
      const label = t.includes("/custom_templates/") ? `custom:${t.split("/").pop()?.replace(/\\.md$/, "")}` : t;
      return `<option value="${escapeHtml(t)}">${escapeHtml(label || t)}</option>`;
    })
    .join("");
  if (templateSelect) templateSelect.innerHTML = options;
  if (promptTemplateSelect) promptTemplateSelect.innerHTML = options;
  if (templateSelect && state.templates.includes(currentTemplate || "")) {
    templateSelect.value = currentTemplate || "";
  }
  if (promptTemplateSelect && state.templates.includes(currentPromptTemplate || "")) {
    promptTemplateSelect.value = currentPromptTemplate || "";
  }
  if (templateSelect && !templateSelect.value && state.templates[0]) {
    templateSelect.value = state.templates[0];
  }
  if (promptTemplateSelect && !promptTemplateSelect.value && templateSelect?.value) {
    promptTemplateSelect.value = templateSelect.value;
  }
}

function renderTemplatesPanel() {
  const host = $("#templates-grid");
  if (!host) return;
  if (!state.templates.length) {
    host.innerHTML = `<div class="template-card"><h3>No templates</h3><p>Templates are loaded from <code>src/federlicht/templates</code>.</p></div>`;
    return;
  }
  const currentTemplate = $("#template-select")?.value || "";
  host.innerHTML = state.templates
    .map((name) => {
      const detail = state.templateDetails[name];
      const displayName = name.includes("/custom_templates/")
        ? `custom:${name.split("/").pop()?.replace(/\\.md$/, "")}`
        : name;
      const meta = detail?.meta || {};
      const pills = [meta.tone, meta.audience, meta.description]
        .filter(Boolean)
        .slice(0, 3)
        .map((v) => `<span class="template-pill">${escapeHtml(v)}</span>`)
        .join("");
      const sections = (detail?.sections || [])
        .slice(0, 12)
        .map((s) => `<span class="template-section">${escapeHtml(s)}</span>`)
        .join("");
      const active = currentTemplate === name ? "active" : "";
      return `
        <article class="template-card ${active}" data-template="${escapeHtml(name)}">
          <h3>${escapeHtml(displayName)}</h3>
          <div class="template-meta">${pills || "<span class=\"template-pill\">template</span>"}</div>
          <div class="template-sections">${sections || "<span class=\"template-section\">No sections parsed</span>"}</div>
          <div class="template-actions">
            <button type="button" class="ghost" data-template-use="${escapeHtml(name)}">Use</button>
            <button type="button" class="ghost" data-template-preview="${escapeHtml(name)}">Preview</button>
          </div>
        </article>
      `;
    })
    .join("");
  host.querySelectorAll("[data-template-use]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.getAttribute("data-template-use");
      if (name) applyTemplateSelection(name, { loadBase: true });
    });
  });
  host.querySelectorAll("[data-template-preview]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.getAttribute("data-template-preview");
      if (name) openTemplateModal(name);
    });
  });
}

function normalizeTemplateName(raw) {
  const cleaned = String(raw || "")
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^a-zA-Z0-9_-]/g, "");
  if (!cleaned) return "";
  return cleaned.startsWith("custom_") ? cleaned : `custom_${cleaned}`;
}

function templateStoreChoice() {
  return $("#template-store-site")?.checked ? "site" : "run";
}

function templateEditorTargetPath(name) {
  if (!name) return "";
  const useSite = $("#template-store-site")?.checked;
  const runRel = $("#run-select")?.value;
  if (useSite || !runRel) {
    return `site/custom_templates/${name}.md`;
  }
  return `${runRel}/custom_templates/${name}.md`;
}

function slugifyLabel(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/_{2,}/g, "_")
    .replace(/^_+|_+$/g, "");
}

function stripFrontmatter(text) {
  const raw = String(text || "");
  if (!raw.startsWith("---")) {
    return { frontmatter: "", body: raw };
  }
  const parts = raw.split("\n");
  let endIndex = -1;
  for (let i = 1; i < parts.length; i += 1) {
    if (parts[i].trim() === "---") {
      endIndex = i;
      break;
    }
  }
  if (endIndex === -1) {
    return { frontmatter: "", body: raw };
  }
  const body = parts.slice(endIndex + 1).join("\n").trimStart();
  return { frontmatter: parts.slice(0, endIndex + 1).join("\n"), body };
}

function buildFrontmatter(meta, sections, guides, writerGuidance) {
  const lines = ["---"];
  const metaEntries = Object.entries(meta || {}).filter(([, v]) => v !== undefined && v !== "");
  metaEntries.forEach(([key, value]) => {
    lines.push(`${key}: ${value}`);
  });
  (sections || []).forEach((section) => {
    if (section) lines.push(`section: ${section}`);
  });
  Object.entries(guides || {}).forEach(([section, guide]) => {
    if (section && guide) lines.push(`guide ${section}: ${guide}`);
  });
  (writerGuidance || []).forEach((note) => {
    if (note) lines.push(`writer_guidance: ${note}`);
  });
  lines.push("---", "");
  return lines.join("\n");
}

function collectTemplateBuilderData() {
  const cssSelect = $("#template-style-select");
  const writerBox = $("#template-writer-guidance");
  const rows = [...document.querySelectorAll(".template-section-row")];
  const sections = [];
  const guides = {};
  rows.forEach((row) => {
    const nameInput = row.querySelector("[data-section-name]");
    const guideInput = row.querySelector("[data-section-guide]");
    const name = String(nameInput?.value || "").trim();
    const guide = String(guideInput?.value || "").trim();
    if (name) {
      sections.push(name);
      if (guide) guides[name] = guide;
    }
  });
  const writerGuidance = String(writerBox?.value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  return {
    css: cssSelect?.value || "",
    sections,
    guides,
    writerGuidance,
  };
}

function resolveStyleOption(cssName) {
  if (!cssName) return "";
  if (state.templateStyles.includes(cssName)) return cssName;
  const match = state.templateStyles.find((entry) => entry.endsWith(`/${cssName}`) || entry === cssName);
  return match || cssName;
}

function renderTemplateSections(rows) {
  const host = $("#template-sections-list");
  if (!host) return;
  host.innerHTML = rows
    .map(
      (row, idx) => `
      <div class="template-section-row" data-section-index="${idx}">
        <input class="ghost-input" data-section-name value="${escapeHtml(row.name || "")}" placeholder="Section name" />
        <input class="ghost-input" data-section-guide value="${escapeHtml(row.guide || "")}" placeholder="Guidance (optional)" />
        <div class="template-section-actions">
          <button type="button" class="ghost" data-section-move="up">↑</button>
          <button type="button" class="ghost" data-section-move="down">↓</button>
          <button type="button" class="ghost" data-section-move="remove">✕</button>
        </div>
      </div>
    `,
    )
    .join("");
  host.querySelectorAll("[data-section-move]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest(".template-section-row");
      if (!row) return;
      const index = Number(row.dataset.sectionIndex || "0");
      const action = btn.getAttribute("data-section-move");
      const list = [...host.querySelectorAll(".template-section-row")].map((el) => ({
        name: el.querySelector("[data-section-name]")?.value || "",
        guide: el.querySelector("[data-section-guide]")?.value || "",
      }));
      if (action === "remove") {
        list.splice(index, 1);
      } else if (action === "up" && index > 0) {
        [list[index - 1], list[index]] = [list[index], list[index - 1]];
      } else if (action === "down" && index < list.length - 1) {
        [list[index + 1], list[index]] = [list[index], list[index + 1]];
      }
      renderTemplateSections(list);
    });
  });
}

function applyBuilderToEditor() {
  const body = $("#template-editor-body");
  if (!body) return;
  const { css, sections, guides, writerGuidance } = collectTemplateBuilderData();
  const { body: rawBody } = stripFrontmatter(body.value || "");
  const meta = { ...(state.templateBuilder.meta || {}) };
  const nameInput = $("#template-editor-name");
  const nameValue = String(nameInput?.value || "").trim();
  if (nameValue) {
    meta.name = nameValue;
  }
  if (css) {
    const cssValue = css.includes("/custom_templates/") ? css.split("/").pop() : css;
    meta.css = cssValue || css;
  }
  const frontmatter = buildFrontmatter(meta, sections, guides, writerGuidance);
  body.value = frontmatter + rawBody;
}

async function refreshTemplatePreview() {
  const frame = $("#template-preview-frame");
  if (!frame) return;
  const nameInput = $("#template-editor-name");
  const title = String(nameInput?.value || state.templateBuilder.meta?.name || "Template Preview").trim();
  const data = collectTemplateBuilderData();
  try {
    const payload = await fetchJSON("/api/template-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: slugifyLabel(title || "template"),
        title,
        css: data.css,
        sections: data.sections,
        guides: data.guides,
        writer_guidance: data.writerGuidance,
      }),
    });
    frame.srcdoc = payload.html || "<p>Preview unavailable.</p>";
  } catch (err) {
    appendLog(`[templates] preview failed: ${err}\n`);
  }
}

function refreshTemplateEditorOptions() {
  const select = $("#template-editor-base");
  if (!select) return;
  const current = select.value;
  select.innerHTML = state.templates.map((t) => `<option value="${t}">${t}</option>`).join("");
  if (state.templates.includes(current)) {
    select.value = current;
  }
}

function updateTemplateEditorPath() {
  const input = $("#template-editor-name");
  const pathField = $("#template-editor-path");
  if (!input || !pathField) return;
  const name = normalizeTemplateName(input.value);
  pathField.value = templateEditorTargetPath(name);
}

async function loadTemplateEditorBase() {
  const baseSelect = $("#template-editor-base");
  const body = $("#template-editor-body");
  const meta = $("#template-editor-meta");
  if (!baseSelect || !body) return;
  const name = baseSelect.value;
  if (!name) return;
  try {
    const detail = state.templateDetails[name]
      || (await fetchJSON(`/api/templates/${encodeURIComponent(name)}`));
    if (!detail?.path) {
      throw new Error("Template path not found.");
    }
    const file = await fetchJSON(`/api/files?path=${encodeURIComponent(detail.path)}`);
    body.value = file.content || "";
    if (meta) meta.textContent = `Loaded base template: ${detail.path}`;
    const builderMeta = detail?.meta || {};
    state.templateBuilder.meta = { ...builderMeta };
    state.templateBuilder.css = resolveStyleOption(builderMeta.css || "");
    const sections = (detail?.sections || []).map((section) => ({
      name: section,
      guide: (detail?.guides || {})[section] || "",
    }));
    renderTemplateSections(sections);
    const writerBox = $("#template-writer-guidance");
    if (writerBox) writerBox.value = (detail?.writer_guidance || []).join("\n");
    refreshTemplateStyleSelect();
    const cssSelect = $("#template-style-select");
    if (cssSelect && state.templateBuilder.css) {
      cssSelect.value = resolveStyleOption(state.templateBuilder.css);
    }
    const nameInput = $("#template-editor-name");
    if (nameInput && !nameInput.value) {
      const baseName = name.includes("/") ? name.split("/").pop()?.replace(/\\.md$/, "") : name;
      nameInput.value = normalizeTemplateName(baseName || name);
      updateTemplateEditorPath();
    }
    refreshTemplatePreview();
  } catch (err) {
    appendLog(`[template-editor] failed to load base: ${err}\n`);
  }
}

async function saveTemplateEditor() {
  const nameInput = $("#template-editor-name");
  const body = $("#template-editor-body");
  const meta = $("#template-editor-meta");
  if (!nameInput || !body) return;
  const name = normalizeTemplateName(nameInput.value);
  if (!name) {
    appendLog("[template-editor] template name is required.\n");
    return;
  }
  applyBuilderToEditor();
  const path = templateEditorTargetPath(name);
  try {
    await fetchJSON("/api/files", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content: body.value || "" }),
    });
    if (meta) meta.textContent = `Saved template: ${path}`;
    nameInput.value = name;
    updateTemplateEditorPath();
    await loadTemplates();
    applyTemplateSelection(name);
  } catch (err) {
    appendLog(`[template-editor] save failed: ${err}\n`);
  }
}

function applyTemplateSelection(name, opts = {}) {
  const templateSelect = $("#template-select");
  const promptTemplateSelect = $("#prompt-template-select");
  if (templateSelect) templateSelect.value = name;
  if (promptTemplateSelect) promptTemplateSelect.value = name;
  if (opts.loadBase) {
    const baseSelect = $("#template-editor-base");
    if (baseSelect) baseSelect.value = name;
    loadTemplateEditorBase();
  }
  renderTemplatesPanel();
}

function applyRunFolderSelection(runRel) {
  const runName = runBaseName(runRel);
  const runInput = $("#feather-run-name");
  const output = $("#feather-output");
  const input = $("#feather-input");
  const updateRun = $("#feather-update-run");
  if (runInput) runInput.value = runName;
  featherOutputTouched = false;
  featherInputTouched = false;
  if (output) output.value = runRel;
  if (input) input.value = `${runRel}/instruction/${runName}.txt`;
  if (updateRun) updateRun.checked = true;
  updateHeroStats();
}

function openTemplateModal(name) {
  const modal = $("#template-modal");
  if (!modal) return;
  const detail = state.templateDetails[name];
  const meta = detail?.meta || {};
  const title = $("#template-modal-title");
  const metaLine = $("#template-modal-meta");
  const body = $("#template-modal-body");
  if (title) title.textContent = name;
  if (metaLine) {
    const description = meta.description || meta.tone || "Template details";
    metaLine.textContent = description;
  }
  if (body) {
    const metaRows = Object.entries(meta || {})
      .map(([k, v]) => `<li><strong>${escapeHtml(k)}</strong>: ${escapeHtml(v)}</li>`)
      .join("");
    const sections = (detail?.sections || [])
      .map((s) => `<span class="template-section">${escapeHtml(s)}</span>`)
      .join("");
    const guides = Object.entries(detail?.guides || {})
      .map(
        ([k, v]) =>
          `<li><strong>${escapeHtml(k)}</strong>: ${escapeHtml(v)}</li>`,
      )
      .join("");
    const guidance = (detail?.writer_guidance || [])
      .map((g) => `<li>${escapeHtml(g)}</li>`)
      .join("");
    body.innerHTML = `
      <div class="template-modal-section">
        <h4>Metadata</h4>
        <ul>${metaRows || "<li>No metadata.</li>"}</ul>
      </div>
      <div class="template-modal-section">
        <h4>Sections</h4>
        <div class="template-sections">${sections || "<span class=\"template-section\">No sections</span>"}</div>
      </div>
      <div class="template-modal-section">
        <h4>Section Guidance</h4>
        <ul>${guides || "<li>No section guidance.</li>"}</ul>
      </div>
      <div class="template-modal-section">
        <h4>Writer Guidance</h4>
        <ul>${guidance || "<li>No writer guidance.</li>"}</ul>
      </div>
      <div class="template-modal-preview">
        <iframe title="Template preview"></iframe>
      </div>
    `;
    const frame = body.querySelector("iframe");
    fetchJSON(`/api/template-preview?name=${encodeURIComponent(name)}`)
      .then((payload) => {
        if (frame && payload?.html) frame.srcdoc = payload.html;
      })
      .catch((err) => {
        appendLog(`[templates] preview failed: ${err}\n`);
      });
  }
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeTemplateModal() {
  const modal = $("#template-modal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

async function loadTemplateDetails(names) {
  const entries = await Promise.all(
    names.map(async (name) => {
      try {
        const detail = await fetchJSON(`/api/templates/${encodeURIComponent(name)}`);
        return [name, detail];
      } catch (err) {
        appendLog(`[templates] failed to load details for ${name}: ${err}\n`);
        return [name, null];
      }
    }),
  );
  state.templateDetails = Object.fromEntries(entries.filter(([, v]) => v));
}

function refreshTemplateStyleSelect() {
  const select = $("#template-style-select");
  if (!select) return;
  const current = select.value || state.templateBuilder.css || "";
  select.innerHTML = state.templateStyles
    .map((name) => {
      const label = name.includes("/custom_templates/")
        ? `custom:${name.split("/").pop()?.replace(/\\.css$/, "")}`
        : name;
      return `<option value="${escapeHtml(name)}">${escapeHtml(label || name)}</option>`;
    })
    .join("");
  if (current && state.templateStyles.includes(current)) {
    select.value = current;
  } else if (state.templateStyles[0]) {
    select.value = state.templateStyles[0];
  }
}

async function loadTemplateStyles(runRel) {
  try {
    const query = runRel ? `?run=${encodeURIComponent(runRel)}` : "";
    state.templateStyles = await fetchJSON(`/api/template-styles${query}`);
  } catch (err) {
    appendLog(`[templates] failed to load styles: ${err}\n`);
    state.templateStyles = [];
  }
  refreshTemplateStyleSelect();
}

async function loadTemplates() {
  const runRel = $("#run-select")?.value;
  const query = runRel ? `?run=${encodeURIComponent(runRel)}` : "";
  state.templates = await fetchJSON(`/api/templates${query}`);
  await loadTemplateDetails(state.templates);
  await loadTemplateStyles(runRel);
  refreshTemplateSelectors();
  refreshTemplateEditorOptions();
  updateHeroStats();
  renderTemplatesPanel();
}

function parseStageCsv(csv) {
  return String(csv || "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s && STAGE_INDEX[s] !== undefined);
}

function selectedStagesInOrder() {
  return state.pipeline.order.filter((id) => state.pipeline.selected.has(id));
}

function updatePipelineOutputs() {
  const selected = selectedStagesInOrder();
  const skipped = STAGE_DEFS.map((s) => s.id).filter((id) => !state.pipeline.selected.has(id));
  const stagesCsv = selected.join(",");
  const skipCsv = skipped.join(",");
  const stagesInput = $("#federlicht-stages");
  const skipInput = $("#federlicht-skip-stages");
  if (stagesInput) stagesInput.value = stagesCsv;
  if (skipInput) skipInput.value = skipCsv;
  setText("#pipeline-stages-value", stagesCsv || "-");
  setText("#pipeline-skip-value", skipCsv || "-");
}

function renderStageDetail(stageId) {
  const def = STAGE_DEFS.find((s) => s.id === stageId);
  setText("#stage-detail-title", def ? `${def.label} (${def.id})` : "Stage Details");
  const body = $("#stage-detail-body");
  if (!body) return;
  body.textContent = def ? def.desc : "Select a stage to see details.";
}

function renderPipelineChips() {
  const host = $("#pipeline-chips");
  if (!host) return;
  host.innerHTML = STAGE_DEFS.map((def) => {
    const active = state.pipeline.selected.has(def.id) ? "active" : "";
    return `<button type="button" class="pipeline-chip ${active}" data-stage-chip="${def.id}">${escapeHtml(def.label)}</button>`;
  }).join("");
  host.querySelectorAll("[data-stage-chip]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-stage-chip");
      if (id) toggleStage(id);
    });
  });
}

function moveStageBefore(order, movingId, beforeId) {
  const next = order.filter((id) => id !== movingId);
  const beforeIdx = next.indexOf(beforeId);
  if (beforeIdx === -1) {
    next.push(movingId);
    return next;
  }
  next.splice(beforeIdx, 0, movingId);
  return next;
}

function renderPipelineSelected() {
  const host = $("#pipeline-selected");
  if (!host) return;
  const selected = selectedStagesInOrder();
  host.innerHTML = selected
    .map((id) => {
      const def = STAGE_DEFS.find((s) => s.id === id);
      const label = def?.label || id;
      return `
        <div class="pipeline-item" draggable="true" data-stage-item="${id}">
          <span>${escapeHtml(label)}</span>
          <span class="handle">drag</span>
        </div>
      `;
    })
    .join("");
  host.querySelectorAll("[data-stage-item]").forEach((el) => {
    el.addEventListener("click", () => {
      const id = el.getAttribute("data-stage-item");
      if (id) {
        state.pipeline.activeStageId = id;
        renderStageDetail(id);
      }
    });
    el.addEventListener("dragstart", (ev) => {
      const id = el.getAttribute("data-stage-item");
      if (!id) return;
      state.pipeline.draggingId = id;
      el.classList.add("dragging");
      ev.dataTransfer?.setData("text/plain", id);
      ev.dataTransfer?.setDragImage(el, 12, 12);
    });
    el.addEventListener("dragend", () => {
      state.pipeline.draggingId = null;
      el.classList.remove("dragging");
    });
    el.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      const overId = el.getAttribute("data-stage-item");
      const draggingId = state.pipeline.draggingId;
      if (!overId || !draggingId || overId === draggingId) return;
      state.pipeline.order = moveStageBefore(state.pipeline.order, draggingId, overId);
      renderPipelineSelected();
      updatePipelineOutputs();
    });
  });
}

function insertStageInOrder(id) {
  if (state.pipeline.order.includes(id)) return;
  const idx = STAGE_INDEX[id];
  let insertAt = state.pipeline.order.findIndex((stageId) => STAGE_INDEX[stageId] > idx);
  if (insertAt < 0) insertAt = state.pipeline.order.length;
  state.pipeline.order.splice(insertAt, 0, id);
}

function toggleStage(id) {
  const isActive = state.pipeline.selected.has(id);
  if (isActive) {
    state.pipeline.selected.delete(id);
  } else {
    state.pipeline.selected.add(id);
    insertStageInOrder(id);
  }
  state.pipeline.activeStageId = id;
  renderStageDetail(id);
  renderPipelineChips();
  renderPipelineSelected();
  updatePipelineOutputs();
}

function initPipelineFromInputs() {
  state.pipeline.order = STAGE_DEFS.map((s) => s.id);
  const stagesCsv = $("#federlicht-stages")?.value;
  const skipCsv = $("#federlicht-skip-stages")?.value;
  const explicitStages = parseStageCsv(stagesCsv);
  const explicitSkip = new Set(parseStageCsv(skipCsv));
  const preferredDefault = ["scout", "evidence", "writer", "quality"].filter(
    (id) => STAGE_INDEX[id] !== undefined,
  );
  const defaultStages = explicitStages.length
    ? explicitStages
    : explicitSkip.size
      ? STAGE_DEFS.map((s) => s.id).filter((id) => !explicitSkip.has(id))
      : preferredDefault;
  state.pipeline.selected = new Set(defaultStages);
  defaultStages.forEach((id) => insertStageInOrder(id));
  state.pipeline.activeStageId = defaultStages[0] || STAGE_DEFS[0]?.id || null;
  renderPipelineChips();
  renderPipelineSelected();
  renderStageDetail(state.pipeline.activeStageId);
  updatePipelineOutputs();
}

function normalizeLogText(text) {
  if (!text) return "";
  return text.endsWith("\n") ? text : `${text}\n`;
}

function setLogBufferFromText(text) {
  const content = String(text || "");
  const lines = content.split(/\r?\n/);
  const buffer = lines.map((line, idx) => {
    if (idx === lines.length - 1 && line === "") return "";
    return normalizeLogText(line);
  });
  state.logBuffer = buffer.slice(-LOG_LINE_LIMIT);
  renderLogs();
}

function renderLogs() {
  const out = $("#log-output");
  if (!out) return;
  out.textContent = state.logBuffer.join("");
  out.scrollTop = out.scrollHeight;
}

function appendLog(text) {
  if (!text) return;
  state.logBuffer.push(normalizeLogText(text));
  if (state.logBuffer.length > LOG_LINE_LIMIT) {
    state.logBuffer.splice(0, state.logBuffer.length - LOG_LINE_LIMIT);
  }
  renderLogs();
}

function clearLogs() {
  state.logBuffer = [];
  renderLogs();
}

function shortId(id) {
  return id ? id.slice(0, 8) : "";
}

async function loadHistoryLog(relPath, runRel) {
  try {
    closeActiveSource();
    setKillEnabled(false);
    setJobStatus(`History log: ${relPath.split("/").pop() || relPath}`, false);
    if (runRel) {
      if ($("#run-select")) $("#run-select").value = runRel;
      if ($("#prompt-run-select")) $("#prompt-run-select").value = runRel;
      if ($("#instruction-run-select")) $("#instruction-run-select").value = runRel;
      refreshRunDependentFields();
      await updateRunStudio(runRel).catch((err) => {
        appendLog(`[studio] failed to refresh run studio: ${err}\n`);
      });
      applyRunFolderSelection(runRel);
    }
    const payload = await fetchJSON(`/api/files?path=${encodeURIComponent(relPath)}`);
    setLogBufferFromText(payload.content || "");
    focusPanel("#logs-wrap .logs-block");
  } catch (err) {
    appendLog(`[logs] failed to load history: ${err}\n`);
  }
}

function upsertJob(jobPatch) {
  const now = Date.now();
  const idx = state.jobs.findIndex((j) => j.job_id === jobPatch.job_id);
  const base = idx >= 0 ? state.jobs[idx] : {};
  const next = {
    started_at: base.started_at || now,
    ...base,
    ...jobPatch,
  };
  if (idx >= 0) {
    state.jobs[idx] = next;
  } else {
    state.jobs.unshift(next);
  }
  state.jobs = state.jobs.slice(0, 12);
  renderJobs();
}

function renderJobs() {
  const host = $("#jobs-modal-list");
  if (!host) return;
  const runRel = selectedRunRel();
  const limit = 6;
  const collapsed = !state.jobsExpanded;
  const allJobs = buildRecentJobs(runRel);
  const jobs = collapsed ? allJobs.slice(0, limit) : allJobs;
  host.classList.toggle("is-collapsed", collapsed);
  host.classList.toggle("is-expanded", !collapsed);
  if (!jobs.length) {
    host.innerHTML = `<div class="muted">No recent jobs yet.</div>`;
  } else {
    host.innerHTML = jobs
      .map((job) => {
        const status = job.status || "unknown";
        const code =
          typeof job.returncode === "number" ? `rc=${job.returncode}` : "";
        const title = job.label || job.kind || "job";
        const when = job.updated_at ? formatDate(job.updated_at) : "";
        const extraPill = when ? `<span class="job-pill">${escapeHtml(when)}</span>` : "";
        return `
          <div class="job-item">
            <div>
              <strong>${escapeHtml(title)}</strong>
              <div class="job-meta">
                <span class="job-pill">${status}</span>
                ${code ? `<span class="job-pill">${code}</span>` : ""}
                ${extraPill}
              </div>
            </div>
            <button class="ghost" data-job-open="${job.job_id}" data-job-source="${job.source}" data-job-path="${escapeHtml(
              job.log_path || "",
            )}" data-job-run="${escapeHtml(job.run_rel || "")}">Open</button>
          </div>
        `;
      })
      .join("");
  }
  const toggle = $("#jobs-toggle");
  if (toggle) {
    toggle.style.display = allJobs.length > limit ? "inline-flex" : "none";
    toggle.textContent = state.jobsExpanded ? "Show less" : "Show more";
    toggle.onclick = () => {
      state.jobsExpanded = !state.jobsExpanded;
      renderJobs();
    };
  }
  host.querySelectorAll("[data-job-open]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const jobId = btn.getAttribute("data-job-open");
      if (!jobId) return;
      const source = btn.getAttribute("data-job-source");
      if (source === "history") {
        const path = btn.getAttribute("data-job-path");
        const runRel = btn.getAttribute("data-job-run");
        if (path) {
          loadHistoryLog(path, runRel || "");
        }
        return;
      }
      attachToJob(jobId);
    });
  });
  updateRecentJobsSummary();
}

function renderRunHistory() {
  const host = $("#jobs-history-list");
  if (!host) return;
  const runs = [...(state.runs || [])]
    .filter((run) => run.run_rel)
    .sort((a, b) => {
      const da = Date.parse(a.updated_at || "") || 0;
      const db = Date.parse(b.updated_at || "") || 0;
      return db - da;
    })
    .slice(0, 5);
  if (!runs.length) {
    host.innerHTML = `<div class="muted">No past runs.</div>`;
    return;
  }
  host.innerHTML = runs
    .map((run) => {
      const rel = run.run_rel || "";
      const name = run.run_name || rel || "run";
      const updated = run.updated_at ? formatDate(run.updated_at) : "";
      return `
        <div class="job-item secondary">
          <div>
            <strong>${escapeHtml(name)}</strong>
            <div class="job-meta">
              <span class="job-pill">${escapeHtml(rel)}</span>
              ${updated ? `<span class="job-pill">${escapeHtml(updated)}</span>` : ""}
            </div>
          </div>
          <button class="ghost" data-run-open="${escapeHtml(rel)}">Open</button>
        </div>
      `;
    })
    .join("");
  host.querySelectorAll("[data-run-open]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const runRel = btn.getAttribute("data-run-open");
      if (!runRel) return;
      if ($("#run-select")) $("#run-select").value = runRel;
      if ($("#prompt-run-select")) $("#prompt-run-select").value = runRel;
      if ($("#instruction-run-select")) $("#instruction-run-select").value = runRel;
      refreshRunDependentFields();
      updateRunStudio(runRel).catch(() => {});
    });
  });
}

function setJobStatus(text, running = false) {
  const el = $("#job-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("is-running", !!running);
}

function setLogsCollapsed(collapsed) {
  state.logsCollapsed = !!collapsed;
  document.body.dataset.logsCollapsed = collapsed ? "true" : "false";
  const button = $("#log-toggle");
  if (button) button.textContent = collapsed ? "Show Logs" : "Hide Logs";
  localStorage.setItem("federnett-logs-collapsed", collapsed ? "true" : "false");
}

function normalizeLanguage(value) {
  if (!value) return "";
  const lowered = String(value).trim().toLowerCase();
  if (lowered.startsWith("ko") || lowered.includes("korean")) return "ko";
  if (lowered.startsWith("en") || lowered.includes("english")) return "en";
  if (lowered.startsWith("de") || lowered.includes("german")) return "de";
  return lowered;
}

function applyRunSettings(summary) {
  const meta = summary?.report_meta || {};
  const template = meta.template;
  if (template) {
    const templateSelect = $("#template-select");
    if (templateSelect && Array.from(templateSelect.options).some((o) => o.value === template)) {
      templateSelect.value = template;
    }
    const promptTemplateSelect = $("#prompt-template-select");
    if (
      promptTemplateSelect &&
      Array.from(promptTemplateSelect.options).some((o) => o.value === template)
    ) {
      promptTemplateSelect.value = template;
    }
  }
  const lang = normalizeLanguage(meta.language);
  if (lang) {
    const langSelect = $("#federlicht-lang");
    if (langSelect && Array.from(langSelect.options).some((o) => o.value === lang)) {
      langSelect.value = lang;
    }
  }
  if (meta.model) {
    const modelInput = $("#federlicht-model");
    if (modelInput) modelInput.value = meta.model;
  }
  if (meta.quality_model) {
    const checkModelInput = $("#federlicht-check-model");
    if (checkModelInput) checkModelInput.value = meta.quality_model;
  }
  if (meta.model_vision) {
    const visionInput = $("#federlicht-model-vision");
    if (visionInput) visionInput.value = meta.model_vision;
  }
  if (meta.agent_profile) {
    const profileId =
      typeof meta.agent_profile === "string" ? meta.agent_profile : meta.agent_profile.id;
    const select = $("#federlicht-agent-profile");
    if (profileId && select) {
      const match = Array.from(select.options).find((o) => o.value === profileId);
      if (match) {
        select.value = match.value;
      }
    }
  }
}

function setKillEnabled(enabled) {
  const kill = $("#job-kill");
  if (kill) kill.disabled = !enabled;
}

function setFederlichtRunEnabled(enabled) {
  const runBtn = $("#federlicht-run");
  if (runBtn) runBtn.disabled = !enabled;
}

function closeActiveSource() {
  if (state.activeSource) {
    state.activeSource.close();
    state.activeSource = null;
  }
}

function attachToJob(jobId, opts = {}) {
  closeActiveSource();
  state.activeJobId = jobId;
  state.activeJobKind = opts.kind || "job";
  if (state.activeJobKind === "federlicht") {
    setFederlichtRunEnabled(false);
  }
  setKillEnabled(true);
  setJobStatus(`Streaming job ${shortId(jobId)} ...`, true);
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  state.activeSource = source;
  source.addEventListener("log", (ev) => {
    try {
      const payload = JSON.parse(ev.data);
      appendLog(payload.text || "");
      if (state.activeJobKind === "template") {
        appendTemplateGenLog(payload.text || "");
      }
    } catch (err) {
      appendLog(`[log] failed to parse event: ${err}\n`);
    }
  });
  source.addEventListener("done", (ev) => {
    try {
      const payload = JSON.parse(ev.data);
      const status = payload.status || "done";
      const code =
        typeof payload.returncode === "number" ? ` (rc=${payload.returncode})` : "";
      appendLog(`[done] ${status}${code}\n`);
      upsertJob({
        job_id: jobId,
        status,
        returncode: payload.returncode,
        kind: opts.kind || "job",
      });
      if (opts.onDone) opts.onDone(payload);
      if (payload.returncode === 0 && opts.onSuccess) opts.onSuccess(payload);
      setJobStatus(`Job ${shortId(jobId)} ${status}${code}`, false);
    } catch (err) {
      appendLog(`[done] failed to parse event: ${err}\n`);
    } finally {
      setKillEnabled(false);
      if (state.activeJobKind === "federlicht") {
        setFederlichtRunEnabled(true);
      }
      if (opts.runRel) {
        loadRunLogs(opts.runRel).catch(() => {});
      }
      state.activeJobKind = null;
      closeActiveSource();
    }
  });
  source.onerror = () => {
    appendLog("[error] event stream closed unexpectedly\n");
    setJobStatus("Stream closed unexpectedly.", false);
    setKillEnabled(false);
    if (state.activeJobKind === "federlicht") {
      setFederlichtRunEnabled(true);
    }
    state.activeJobKind = null;
    closeActiveSource();
  };
}

async function startJob(endpoint, payload, meta = {}) {
  const body = JSON.stringify(payload || {});
  appendLog(`\n[start] POST ${endpoint}\n`);
  const res = await fetchJSON(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const jobId = res.job_id;
  const inferredRunRel = inferRunRelFromPayload(payload);
  upsertJob({
    job_id: jobId,
    status: "running",
    kind: meta.kind || "job",
    run_rel: meta.runRel || inferredRunRel || "",
  });
  setJobStatus(`Job ${shortId(jobId)} running…`, true);
  focusPanel("#logs-wrap .logs-block");
  attachToJob(jobId, { ...meta, runRel: meta.runRel || inferredRunRel || "" });
  return jobId;
}

function pruneEmpty(obj) {
  const out = {};
  Object.entries(obj || {}).forEach(([k, v]) => {
    if (v === null || v === undefined) return;
    if (typeof v === "string" && v.trim() === "") return;
    out[k] = v;
  });
  return out;
}

function buildFeatherPayload() {
  const inputValueRaw = $("#feather-input")?.value?.trim();
  const inputValue = inputValueRaw ? expandSiteRunsPath(inputValueRaw) : inputValueRaw;
  const queryValue = $("#feather-query")?.value;
  const payload = {
    input: inputValue,
    query: inputValue ? undefined : queryValue,
    output: expandSiteRunsPath($("#feather-output")?.value),
    lang: $("#feather-lang")?.value,
    days: Number.parseInt($("#feather-days")?.value || "", 10),
    max_results: Number.parseInt($("#feather-max-results")?.value || "", 10),
    download_pdf: $("#feather-download-pdf")?.checked,
    openalex: $("#feather-openalex")?.checked,
    youtube: $("#feather-youtube")?.checked,
    yt_transcript: $("#feather-yt-transcript")?.checked,
    update_run: $("#feather-update-run")?.checked,
    yt_order: $("#feather-yt-order")?.value,
    extra_args: $("#feather-extra-args")?.value,
  };
  if (!payload.input && !payload.query) {
    throw new Error("Provide either an instruction path or a query.");
  }
  if (!payload.output) {
    throw new Error("Output folder is required.");
  }
  if (!Number.isFinite(payload.days)) delete payload.days;
  if (!Number.isFinite(payload.max_results)) delete payload.max_results;
  return pruneEmpty(payload);
}

function buildFederlichtPayload() {
  const figuresEnabled = $("#federlicht-figures")?.checked;
  const noTags = $("#federlicht-no-tags")?.checked;
  const agentSelect = $("#federlicht-agent-profile");
  const agentProfile = agentSelect?.value;
  const agentSource =
    agentSelect?.selectedOptions?.[0]?.getAttribute("data-source") || "builtin";
  const agentProfileDir =
    agentSource === "site" ? joinPath(state.info?.site_root || "site", "agent_profiles") : "";
  const payload = {
    run: $("#run-select")?.value,
    output: expandSiteRunsPath($("#federlicht-output")?.value),
    template: $("#template-select")?.value,
    lang: $("#federlicht-lang")?.value,
    depth: $("#federlicht-depth")?.value,
    prompt: $("#federlicht-prompt")?.value,
    prompt_file: expandSiteRunsPath($("#federlicht-prompt-file")?.value),
    model: $("#federlicht-model")?.value,
    check_model: $("#federlicht-check-model")?.value,
    model_vision: $("#federlicht-model-vision")?.value,
    stages: $("#federlicht-stages")?.value,
    skip_stages: $("#federlicht-skip-stages")?.value,
    quality_iterations: Number.parseInt(
      $("#federlicht-quality-iterations")?.value || "",
      10,
    ),
    quality_strategy: $("#federlicht-quality-strategy")?.value,
    max_chars: Number.parseInt($("#federlicht-max-chars")?.value || "", 10),
    max_pdf_pages: Number.parseInt(
      $("#federlicht-max-pdf-pages")?.value || "",
      10,
    ),
    tags: noTags ? undefined : $("#federlicht-tags")?.value,
    no_tags: noTags ? true : undefined,
    figures: figuresEnabled ? true : undefined,
    no_figures: figuresEnabled ? undefined : true,
    figures_mode: $("#federlicht-figures-mode")?.value,
    figures_select: $("#federlicht-figures-select")?.value,
    web_search: $("#federlicht-web-search")?.checked,
    site_output: $("#federlicht-site-output")?.value,
    agent_profile: agentProfile,
    agent_profile_dir: agentProfileDir,
    extra_args: $("#federlicht-extra-args")?.value,
  };
  if (!payload.run) {
    throw new Error("Run folder is required.");
  }
  if (!payload.output) {
    throw new Error("Output report path is required.");
  }
  if (!Number.isFinite(payload.quality_iterations)) delete payload.quality_iterations;
  if (!Number.isFinite(payload.max_chars)) delete payload.max_chars;
  if (!Number.isFinite(payload.max_pdf_pages)) delete payload.max_pdf_pages;
  return pruneEmpty(payload);
}

function buildPromptPayload() {
  const run = $("#prompt-run-select")?.value;
  let output = $("#prompt-output")?.value;
  if (!output && run) {
    output = defaultPromptPath(run);
    const field = $("#prompt-output");
    if (field) field.value = output;
  }
  const payload = {
    run,
    output: expandSiteRunsPath(output),
    template: $("#prompt-template-select")?.value,
    depth: $("#prompt-depth")?.value,
    model: $("#prompt-model")?.value,
    extra_args: $("#prompt-extra-args")?.value,
  };
  if (!payload.run) throw new Error("Run folder is required.");
  return pruneEmpty(payload);
}

function buildPromptPayloadFromFederlicht() {
  const run = $("#run-select")?.value;
  if (!run) throw new Error("Run folder is required.");
  let output = $("#federlicht-prompt-file")?.value;
  if (!output) {
    output = defaultPromptPath(run);
    const field = $("#federlicht-prompt-file");
    if (field) field.value = output;
  }
  const payload = {
    run,
    output: expandSiteRunsPath(output),
    template: $("#template-select")?.value,
    depth: $("#federlicht-depth")?.value,
    model: $("#federlicht-model")?.value,
  };
  return pruneEmpty(payload);
}

function handleTabs() {
  const tabs = Array.from(document.querySelectorAll(".tab"));
  const panels = {
    feather: $("#tab-feather"),
    federlicht: $("#tab-federlicht"),
  };
  const setActiveTab = (key) => {
    const resolved = key || "feather";
    document.body.dataset.tab = resolved;
    if (resolved === "federlicht") {
      syncPromptFromFile(true).catch((err) => {
        if (!isMissingFileError(err)) {
          appendLog(`[prompt] failed to load: ${err}\n`);
        }
      });
    }
  };
  const initial = tabs.find((t) => t.classList.contains("active"))?.dataset.tab;
  setActiveTab(initial || "feather");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const key = tab.dataset.tab;
      setActiveTab(key || "feather");
      Object.entries(panels).forEach(([name, panel]) => {
        if (!panel) return;
        panel.classList.toggle("active", name === key);
      });
    });
  });
}

function handleFeatherRunName() {
  const runName = $("#feather-run-name");
  const output = $("#feather-output");
  const input = $("#feather-input");
  if (!runName || !output) return;
  runName.addEventListener("input", () => {
    if (featherOutputTouched) return;
    const value = runName.value.trim();
    if (!value) return;
    output.value = value;
    if (input && !featherInputTouched) {
      input.value = `${value}/instruction/${value}.txt`;
    }
  });
  output.addEventListener("input", () => {
    featherOutputTouched = true;
    if (input && !featherInputTouched) {
      const cleaned = normalizePathString(output.value || "");
      if (cleaned) {
        const name = cleaned.split("/").pop() || "run";
        input.value = `${cleaned}/instruction/${name}.txt`;
      }
    }
  });
  input?.addEventListener("input", () => {
    featherInputTouched = true;
  });
}

function handleRunOutputTouch() {
  $("#federlicht-output")?.addEventListener("input", () => {
    reportOutputTouched = true;
  });
  $("#federlicht-prompt-file")?.addEventListener("input", () => {
    promptFileTouched = true;
  });
  $("#federlicht-prompt-file")?.addEventListener("change", () => {
    promptFileTouched = true;
    syncPromptFromFile(true).catch((err) => {
      if (!isMissingFileError(err)) {
        appendLog(`[prompt] failed to load: ${err}\n`);
      }
    });
  });
  $("#prompt-output")?.addEventListener("input", () => {
    promptOutputTouched = true;
  });
  $("#federlicht-prompt")?.addEventListener("input", () => {
    promptInlineTouched = true;
  });
}

function handlePipelineInputs() {
  $("#federlicht-stages")?.addEventListener("change", () => {
    initPipelineFromInputs();
  });
  $("#federlicht-skip-stages")?.addEventListener("change", () => {
    initPipelineFromInputs();
  });
}

function handleRunChanges() {
  $("#run-select")?.addEventListener("change", () => {
    const runRel = $("#run-select").value;
    if ($("#prompt-run-select")) $("#prompt-run-select").value = runRel;
    if ($("#instruction-run-select")) $("#instruction-run-select").value = runRel;
    const newPath = $("#instruction-new-path");
    if (newPath) newPath.value = defaultInstructionPath(runRel);
    promptFileTouched = false;
    promptInlineTouched = false;
    refreshRunDependentFields();
    updateTemplateEditorPath();
    loadTemplates().catch((err) => {
      appendLog(`[templates] failed to refresh: ${err}\n`);
    });
    updateHeroStats();
    updateRunStudio(runRel).catch((err) => {
      appendLog(`[studio] failed to refresh run studio: ${err}\n`);
    });
  });
  $("#instruction-run-select")?.addEventListener("change", () => {
    const runRel = $("#instruction-run-select").value;
    if ($("#run-select")) $("#run-select").value = runRel;
    if ($("#prompt-run-select")) $("#prompt-run-select").value = runRel;
    const newPath = $("#instruction-new-path");
    if (newPath) newPath.value = defaultInstructionPath(runRel);
    promptFileTouched = false;
    promptInlineTouched = false;
    refreshRunDependentFields();
    updateTemplateEditorPath();
    loadTemplates().catch((err) => {
      appendLog(`[templates] failed to refresh: ${err}\n`);
    });
    updateHeroStats();
    updateRunStudio(runRel).catch((err) => {
      appendLog(`[studio] failed to refresh run studio: ${err}\n`);
    });
  });
  $("#prompt-run-select")?.addEventListener("change", () => {
    const runRel = $("#prompt-run-select").value;
    if ($("#run-select")) $("#run-select").value = runRel;
    if ($("#instruction-run-select")) $("#instruction-run-select").value = runRel;
    const newPath = $("#instruction-new-path");
    if (newPath) newPath.value = defaultInstructionPath(runRel);
    promptFileTouched = false;
    promptInlineTouched = false;
    refreshRunDependentFields();
    updateTemplateEditorPath();
    loadTemplates().catch((err) => {
      appendLog(`[templates] failed to refresh: ${err}\n`);
    });
    updateHeroStats();
    updateRunStudio(runRel).catch((err) => {
      appendLog(`[studio] failed to refresh run studio: ${err}\n`);
    });
  });
}

function handleRunOpen() {
  $("#run-open")?.addEventListener("click", () => {
    openRunPickerModal();
    loadRunPickerItems();
  });
}

function handleInstructionEditor() {
  $("#instruction-file-select")?.addEventListener("change", () => {
    const pathRel = $("#instruction-file-select").value;
    loadInstructionContent(pathRel).catch((err) => {
      appendLog(`[instruction] failed to load file: ${err}\n`);
    });
  });
  $("#instruction-reload")?.addEventListener("click", () => {
    const runRel = $("#instruction-run-select")?.value;
    if (!runRel) return;
    loadInstructionFiles(runRel).catch((err) => {
      appendLog(`[instruction] reload failed: ${err}\n`);
    });
  });
  $("#instruction-save")?.addEventListener("click", () => {
    const runRel = $("#instruction-run-select")?.value;
    if (!runRel) return;
    saveInstruction(runRel).catch((err) => {
      appendLog(`[instruction] save failed: ${err}\n`);
    });
  });
  $("#instruction-new")?.addEventListener("click", () => {
    const runRel = $("#instruction-run-select")?.value;
    if (!runRel) return;
    const input = $("#instruction-new-path");
    if (!input) return;
    input.value = defaultInstructionPath(runRel);
    const editor = $("#instruction-editor");
    if (editor) {
      editor.value = "";
      editor.dataset.path = "";
    }
    input.focus();
    input.select();
  });
  $("#instruction-use-feather")?.addEventListener("click", () => {
    const runRel = $("#instruction-run-select")?.value;
    if (!runRel) return;
    const selected =
      $("#instruction-new-path")?.value ||
      $("#instruction-file-select")?.value ||
      defaultInstructionPath(runRel);
    if (!selected) return;
    const featherInput = $("#feather-input");
    if (featherInput) featherInput.value = selected;
    const featherOutput = $("#feather-output");
    if (featherOutput && !featherOutputTouched) {
      featherOutput.value = runRel;
    }
    appendLog(`[instruction] wired into Feather: ${selected}\n`);
  });
}

function handleFilePreviewControls() {
  const editor = $("#file-preview-editor");
  const saveAsInput = $("#file-preview-saveas-path");
  editor?.addEventListener("input", () => {
    if (!state.filePreview.canEdit) return;
    state.filePreview.dirty = true;
    state.filePreview.content = editor.value || "";
    const statusEl = $("#file-preview-status");
    if (statusEl) statusEl.textContent = "modified";
  });
  $("#file-preview-open")?.addEventListener("click", () => {
    const rel = state.filePreview.path;
    if (!rel) return;
    const url = state.filePreview.objectUrl || rawFileUrl(rel);
    if (!url) return;
    const lower = String(rel).toLowerCase();
    if (lower.endsWith(".pptx")) {
      const name = rel.split("/").pop() || "download.pptx";
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      return;
    }
    window.open(url, "_blank", "noopener");
  });
  $("#file-preview-canvas")?.addEventListener("click", () => {
    const rel = state.filePreview.path;
    if (!rel) return;
    const url = `./canvas.html?report=${encodeURIComponent(rel)}`;
    window.open(url, "_blank", "noopener");
  });
  $("#file-preview-save")?.addEventListener("click", async () => {
    const rel = state.filePreview.path;
    const saveAsPath = saveAsInput?.value?.trim();
    try {
      if (!rel && !saveAsPath) {
        openSaveAsModal(rel || "", "preview");
        return;
      }
      await saveFilePreview(rel || saveAsPath);
      appendLog(`[file] saved ${rel || saveAsPath}\n`);
    } catch (err) {
      appendLog(`[file] save failed: ${err}\n`);
    }
  });
  $("#file-preview-saveas")?.addEventListener("click", () => {
    if (!state.filePreview.canEdit) return;
    openSaveAsModal(state.filePreview.path || "", "preview");
  });
  $("#saveas-confirm")?.addEventListener("click", async () => {
    const filenameInput = $("#saveas-filename");
    const rel = state.saveAs.path;
    const filename = filenameInput?.value?.trim();
    if (!filename) return;
    const target = rel ? `${rel}/${filename}` : filename;
    try {
      const mode = state.saveAs.mode || "preview";
      if (mode === "prompt") {
        const content = $("#federlicht-prompt")?.value || "";
        await savePromptContent(target, content);
        const promptField = $("#federlicht-prompt-file");
        if (promptField) promptField.value = target;
        promptFileTouched = true;
        appendLog(`[prompt] saved as ${target}\n`);
      } else {
        await saveFilePreview(target);
        if (saveAsInput) saveAsInput.value = target;
        appendLog(`[file] saved as ${target}\n`);
      }
      closeSaveAsModal();
    } catch (err) {
      appendLog(`[file] save-as failed: ${err}\n`);
    }
  });
  $("#saveas-up")?.addEventListener("click", () => {
    const current = state.saveAs.path || "";
    const parent = current.replace(/\/[^/]*$/, "");
    loadSaveAsDir(parent);
  });
  document.querySelectorAll("[data-saveas-close]").forEach((btn) =>
    btn.addEventListener("click", closeSaveAsModal)
  );
}

function handleFeatherInstructionPicker() {
  const openBtn = $("#feather-pick-instruction");
  const saveBtn = $("#feather-save-instruction");
  const saveAsInlineBtn = $("#feather-saveas-instruction");
  const modal = $("#instruction-modal");
  const search = $("#instruction-search");
  const saveAsBtn = $("#instruction-saveas-btn");
  const useSelectedBtn = $("#instruction-use-selected");
  const importInput = $("#instruction-import");
  const saveAsInput = $("#instruction-saveas");

  const applySelection = async (pathRel) => {
    if (!pathRel) return;
    $("#feather-input").value = pathRel;
    featherInputTouched = true;
    await loadFeatherInstructionContent(pathRel).catch((err) => {
      appendLog(`[instruction] failed to load content: ${err}\n`);
    });
  };

  const refreshModal = async () => {
    await loadInstructionModalItems();
  };

  const filterModal = () => {
    const query = search?.value?.trim().toLowerCase() || "";
    if (!query) {
      state.instructionModal.filtered = [];
    } else {
      state.instructionModal.filtered = state.instructionModal.items.filter((item) => {
        return (
          item.name?.toLowerCase().includes(query) ||
          item.path?.toLowerCase().includes(query)
        );
      });
    }
    renderInstructionModalList();
  };

  openBtn?.addEventListener("click", async () => {
    openInstructionModal("feather");
    await refreshModal();
  });

  modal?.querySelectorAll("[data-modal-close]")?.forEach((el) => {
    el.addEventListener("click", () => {
      closeInstructionModal();
    });
  });

  search?.addEventListener("input", filterModal);

  useSelectedBtn?.addEventListener("click", async () => {
    const mode = state.instructionModal.mode || "feather";
    const pathRel =
      state.instructionModal.selectedPath || saveAsInput?.value?.trim() || "";
    if (!pathRel) return;
    if (mode === "prompt") {
      const promptField = $("#federlicht-prompt-file");
      if (promptField) promptField.value = pathRel;
      promptFileTouched = true;
      syncPromptFromFile(true).catch((err) => {
        if (!isMissingFileError(err)) {
          appendLog(`[prompt] failed to load: ${err}\n`);
        }
      });
      closeInstructionModal();
      return;
    }
    await applySelection(pathRel);
    closeInstructionModal();
  });

  saveAsBtn?.addEventListener("click", async () => {
    const mode = state.instructionModal.mode || "feather";
    const rawPath = saveAsInput?.value || $("#feather-input")?.value;
    const runRel = state.instructionModal.runRel;
    const normalized =
      mode === "prompt"
        ? normalizeInstructionPath(runRel, rawPath || "")
        : normalizeFeatherInstructionPath(rawPath);
    if (!normalized) return;
    if (mode === "prompt") {
      const promptField = $("#federlicht-prompt-file");
      if (promptField) promptField.value = normalized;
      promptFileTouched = true;
      syncPromptFromFile(true).catch((err) => {
        if (!isMissingFileError(err)) {
          appendLog(`[prompt] failed to load: ${err}\n`);
        }
      });
      closeInstructionModal();
      return;
    }
    const content = $("#feather-query")?.value || "";
    await saveInstructionContent(normalized, content).catch((err) => {
      appendLog(`[instruction] save-as failed: ${err}\n`);
    });
    $("#feather-input").value = normalized;
    featherInputTouched = true;
    await applySelection(normalized);
    closeInstructionModal();
    await loadRuns().catch(() => {});
  });

  saveBtn?.addEventListener("click", async () => {
    const rawPath = $("#feather-input")?.value;
    const normalized = normalizeFeatherInstructionPath(rawPath);
    const content = $("#feather-query")?.value || "";
    const editor = $("#feather-query");
    const loadedPath = editor?.dataset.path || "";
    const isDirty = isFeatherInstructionDirty();
    if (!rawPath || !rawPath.trim()) {
      openInstructionModal("feather");
      await refreshModal();
      if (saveAsInput) saveAsInput.focus();
      return;
    }
    if (normalized !== loadedPath && normalized.trim()) {
      await saveInstructionContent(normalized, content).catch((err) => {
        appendLog(`[instruction] save failed: ${err}\n`);
      });
      $("#feather-input").value = normalized;
      featherInputTouched = true;
      setFeatherInstructionSnapshot(normalized, content);
      await loadRuns().catch(() => {});
      return;
    }
    if (isDirty) {
      const ok = window.confirm(
        "This instruction was loaded from an existing file. Save a new copy to avoid overwriting?",
      );
      if (!ok) return;
      openInstructionModal("feather");
      await refreshModal();
      if (saveAsInput) {
        saveAsInput.value = normalizeFeatherInstructionPath(normalized);
        saveAsInput.focus();
        saveAsInput.select();
      }
      return;
    }
    await saveInstructionContent(normalized, content).catch((err) => {
      appendLog(`[instruction] save failed: ${err}\n`);
    });
    $("#feather-input").value = normalized;
    featherInputTouched = true;
    setFeatherInstructionSnapshot(normalized, content);
    await loadRuns().catch(() => {});
  });

  saveAsInlineBtn?.addEventListener("click", async () => {
    const rawPath = $("#feather-input")?.value;
    openInstructionModal("feather");
    await refreshModal();
    if (saveAsInput) {
      saveAsInput.value = normalizeFeatherInstructionPath(rawPath);
      saveAsInput.focus();
      saveAsInput.select();
    }
  });

  importInput?.addEventListener("change", async () => {
    const file = importInput.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const content = reader.result ? String(reader.result) : "";
      const editor = $("#feather-query");
      if (editor) editor.value = content;
      openInstructionModal("feather");
      await refreshModal();
      if (saveAsInput && !saveAsInput.value.trim()) {
        saveAsInput.value = normalizeFeatherInstructionPath(
          $("#feather-input")?.value || "",
        );
      }
    };
    reader.readAsText(file);
    importInput.value = "";
  });
}

function handleCanvasModal() {
  const modal = $("#canvas-modal");
  if (!modal) return;
  modal.querySelectorAll("[data-canvas-close]").forEach((el) => {
    el.addEventListener("click", () => closeCanvasModal());
  });
  $("#canvas-use-selection")?.addEventListener("click", () => {
    syncCanvasSelection();
  });
  $("#canvas-clear-selection")?.addEventListener("click", () => {
    state.canvas.selection = "";
    updateCanvasFields();
  });
  $("#canvas-output-path")?.addEventListener("input", (event) => {
    const value = event.target?.value || "";
    state.canvas.outputPath = value;
  });
  $("#canvas-run")?.addEventListener("click", () => {
    runCanvasUpdate().catch((err) => {
      appendLog(`[canvas] update failed: ${err}\n`);
    });
  });
}

function handleUploadDrop() {
  const target = document.body;
  if (!target) return;
  const onDragOver = (ev) => {
    if (!isFeatherTab()) return;
    ev.preventDefault();
  };
  const onDrop = async (ev) => {
    if (!isFeatherTab()) return;
    ev.preventDefault();
    const file = ev.dataTransfer?.files?.[0];
    if (!file) return;
    try {
      const res = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      const payload = await res.json();
      if (!res.ok || payload?.error) {
        throw new Error(payload?.error || res.statusText);
      }
      const absPath = payload.abs_path || payload.path;
      const line = `file: "${absPath}" | title="${file.name}"`;
      const query = $("#feather-query");
      if (query) {
        const current = query.value || "";
        query.value = current ? `${current.trim()}\n${line}\n` : `${line}\n`;
      }
      const featherInput = $("#feather-input");
      if (featherInput) featherInput.value = "";
      appendLog(`[upload] added ${file.name} -> ${absPath}\n`);
    } catch (err) {
      appendLog(`[upload] failed: ${err}\n`);
    }
  };
  target.addEventListener("dragover", onDragOver);
  target.addEventListener("drop", onDrop);
}

function handleFederlichtPromptPicker() {
  const pickBtn = $("#federlicht-prompt-pick");
  const genBtn = $("#federlicht-prompt-generate");
  pickBtn?.addEventListener("click", async () => {
    openInstructionModal("prompt");
    await loadInstructionModalItems();
  });
  genBtn?.addEventListener("click", async () => {
    try {
      const payload = buildPromptPayloadFromFederlicht();
      promptFileTouched = true;
      await startJob("/api/federlicht/generate_prompt", payload, {
        kind: "prompt",
        onSuccess: () => {
          if (payload.output) {
            const field = $("#federlicht-prompt-file");
            if (field) field.value = payload.output;
            syncPromptFromFile(true).catch((err) => {
              if (!isMissingFileError(err)) {
                appendLog(`[prompt] failed to load: ${err}\n`);
              }
            });
            appendLog(`[prompt] ready: ${payload.output}\n`);
          }
        },
      });
    } catch (err) {
      appendLog(`[prompt] ${err}\n`);
    }
  });
}

function handleFederlichtPromptEditor() {
  const saveBtn = $("#federlicht-save-prompt");
  const saveAsBtn = $("#federlicht-saveas-prompt");
  saveBtn?.addEventListener("click", async () => {
    const editor = $("#federlicht-prompt");
    const promptField = $("#federlicht-prompt-file");
    const rawPath = promptField?.value?.trim();
    const normalized = normalizePromptPath(rawPath);
    const content = editor?.value || "";
    const loadedPath = editor?.dataset.path || "";
    const isDirty = isPromptDirty();
    if (!rawPath) {
      openSaveAsModal(normalized, "prompt");
      const filenameInput = $("#saveas-filename");
      if (filenameInput && normalized) {
        filenameInput.value = normalized.split("/").pop() || "";
      }
      return;
    }
    if (normalized && normalized !== loadedPath) {
      try {
        await savePromptContent(normalized, content);
        if (promptField) promptField.value = normalized;
        promptFileTouched = true;
      } catch (err) {
        appendLog(`[prompt] save failed: ${err}\n`);
      }
      return;
    }
    if (isDirty) {
      const ok = window.confirm(
        "This prompt was loaded from an existing file. Save a new copy to avoid overwriting?",
      );
      if (!ok) return;
      openSaveAsModal(normalized, "prompt");
      const filenameInput = $("#saveas-filename");
      if (filenameInput && normalized) {
        filenameInput.value = normalized.split("/").pop() || "";
        filenameInput.focus();
        filenameInput.select();
      }
      return;
    }
    try {
      await savePromptContent(normalized, content);
      if (promptField) promptField.value = normalized;
      promptFileTouched = true;
    } catch (err) {
      appendLog(`[prompt] save failed: ${err}\n`);
    }
  });

  saveAsBtn?.addEventListener("click", () => {
    const promptField = $("#federlicht-prompt-file");
    const rawPath = promptField?.value?.trim();
    const normalized = normalizePromptPath(rawPath);
    openSaveAsModal(normalized, "prompt");
    const filenameInput = $("#saveas-filename");
    if (filenameInput && normalized) {
      filenameInput.value = normalized.split("/").pop() || "";
      filenameInput.focus();
      filenameInput.select();
    }
  });
}

function handleRunPicker() {
  const modal = $("#run-picker-modal");
  const search = $("#run-picker-search");
  const useBtn = $("#run-picker-use");
  modal?.querySelectorAll("[data-runpicker-close]")?.forEach((el) => {
    el.addEventListener("click", () => closeRunPickerModal());
  });
  search?.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    if (!query) {
      state.runPicker.filtered = [];
    } else {
      state.runPicker.filtered = state.runPicker.items.filter((item) => {
        const rel = (item.run_rel || "").toLowerCase();
        const name = (item.run_name || "").toLowerCase();
        return rel.includes(query) || name.includes(query);
      });
    }
    renderRunPickerList();
  });
  useBtn?.addEventListener("click", async () => {
    const runRel = state.runPicker.selected;
    if (!runRel) return;
    const runSelect = $("#run-select");
    if (runSelect) runSelect.value = runRel;
    applyRunFolderSelection(runRel);
    refreshRunDependentFields();
    await updateRunStudio(runRel).catch((err) => {
      appendLog(`[studio] failed to refresh run studio: ${err}\n`);
    });
    closeRunPickerModal();
  });
}

function handleJobsModal() {
  const modal = $("#jobs-modal");
  const openBtn = $("#jobs-open");
  const card = $("#hero-card-recent");
  openBtn?.addEventListener("click", (ev) => {
    ev.stopPropagation();
    openJobsModal();
  });
  card?.addEventListener("click", (ev) => {
    if (ev.target.closest("button")) return;
    openJobsModal();
  });
  modal?.querySelectorAll("[data-jobs-close]")?.forEach((el) => {
    el.addEventListener("click", () => closeJobsModal());
  });
}

function handleReloadRuns() {
  $("#reload-runs")?.addEventListener("click", async () => {
    try {
      await loadRuns();
    } catch (err) {
      appendLog(`[runs] reload failed: ${err}\n`);
    }
  });
}

function bindTemplateModalClose() {
  const modal = $("#template-modal");
  if (!modal) return;
  modal.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", () => closeTemplateModal());
  });
}

function bindHelpModal() {
  const modal = $("#help-modal");
  $("#help-button")?.addEventListener("click", () => openHelpModal());
  $("#pipeline-help")?.addEventListener("click", () => openHelpModal());
  modal?.querySelectorAll("[data-help-close]")?.forEach((el) => {
    el.addEventListener("click", () => closeHelpModal());
  });
}

function handleLogControls() {
  const saved = localStorage.getItem("federnett-logs-collapsed");
  if (saved === "true" || saved === "false") {
    setLogsCollapsed(saved === "true");
  } else {
    setLogsCollapsed(false);
  }
  $("#log-toggle")?.addEventListener("click", () => {
    setLogsCollapsed(!state.logsCollapsed);
  });
  $("#log-clear")?.addEventListener("click", () => {
    clearLogs();
  });
  $("#job-kill")?.addEventListener("click", async () => {
    const jobId = state.activeJobId;
    if (!jobId) return;
    try {
      appendLog(`[kill] ${shortId(jobId)}\n`);
      await fetchJSON(`/api/jobs/${jobId}/kill`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } catch (err) {
      appendLog(`[kill] failed: ${err}\n`);
    }
  });
}

function handleTemplateSync() {
  $("#template-select")?.addEventListener("change", () => {
    if ($("#prompt-template-select")) {
      $("#prompt-template-select").value = $("#template-select").value;
    }
    renderTemplatesPanel();
  });
}

function handleTemplateEditor() {
  $("#template-editor-name")?.addEventListener("input", updateTemplateEditorPath);
  $("#template-store-site")?.addEventListener("change", () => {
    updateTemplateEditorPath();
  });
  $("#template-editor-base")?.addEventListener("change", () => {
    const nameInput = $("#template-editor-name");
    if (nameInput && !nameInput.value) {
      const raw = $("#template-editor-base").value;
      const baseName = raw.includes("/") ? raw.split("/").pop()?.replace(/\\.md$/, "") : raw;
      nameInput.value = normalizeTemplateName(baseName || raw);
    }
    updateTemplateEditorPath();
  });
  $("#template-style-select")?.addEventListener("change", () => {
    const select = $("#template-style-select");
    if (select) state.templateBuilder.css = select.value || "";
    refreshTemplatePreview();
  });
  $("#template-section-add")?.addEventListener("click", () => {
    const rows = [...document.querySelectorAll(".template-section-row")].map((el) => ({
      name: el.querySelector("[data-section-name]")?.value || "",
      guide: el.querySelector("[data-section-guide]")?.value || "",
    }));
    rows.push({ name: "", guide: "" });
    renderTemplateSections(rows);
  });
  $("#template-apply-frontmatter")?.addEventListener("click", () => {
    applyBuilderToEditor();
  });
  $("#template-preview-refresh")?.addEventListener("click", () => {
    refreshTemplatePreview();
  });
  $("#template-editor-load")?.addEventListener("click", () => {
    loadTemplateEditorBase();
  });
  $("#template-editor-save")?.addEventListener("click", () => {
    saveTemplateEditor();
  });
}

function handleTemplateGenerator() {
  $("#template-generate")?.addEventListener("click", async () => {
    const button = $("#template-generate");
    const prompt = $("#template-gen-prompt")?.value?.trim();
    if (!prompt) {
      appendLog("[template-generator] prompt is required.\n");
      return;
    }
    const nameInput = $("#template-editor-name");
    let normalized = normalizeTemplateName(nameInput?.value || "");
    if (!normalized) {
      const fallback = slugifyLabel(prompt).slice(0, 24) || "custom_template";
      normalized = normalizeTemplateName(fallback);
      if (nameInput) nameInput.value = normalized;
    }
    if (nameInput) nameInput.value = normalized;
    updateTemplateEditorPath();
    const runRel = $("#run-select")?.value;
    const store = templateStoreChoice();
    if (store === "run" && !runRel) {
      appendLog("[template-generator] run folder is required for run storage.\n");
      return;
    }
    state.templateGen.log = "";
    appendTemplateGenLog("Generating template...\n");
    if (button) {
      button.disabled = true;
      button.textContent = "Generating...";
    }
    const payload = {
      prompt,
      name: normalized,
      run: runRel,
      store,
      model: $("#template-gen-model")?.value,
      lang: $("#federlicht-lang")?.value || "ko",
      site_output: state.info?.site_root || "site",
    };
    const targetPath = templateEditorTargetPath(normalized);
    await startJob("/api/templates/generate", payload, {
      kind: "template",
      onSuccess: async () => {
        await loadTemplates();
        const baseSelect = $("#template-editor-base");
        if (baseSelect) baseSelect.value = targetPath;
        await loadTemplateEditorBase();
        appendTemplateGenLog("\nDone.\n");
        if (button) {
          button.disabled = false;
          button.textContent = "Generate Base";
        }
      },
      onDone: () => {
        if (button) {
          button.disabled = false;
          button.textContent = "Generate Base";
        }
      },
    });
  });
}

function setAgentStatus(message) {
  const el = $("#agent-status");
  if (el) {
    el.textContent = message || "";
  }
}

function normalizeApplyTo(value) {
  if (Array.isArray(value)) {
    return value.map((v) => String(v).trim()).filter(Boolean);
  }
  if (!value) return [];
  return String(value)
    .split(/[,\\n]/)
    .map((v) => v.trim())
    .filter(Boolean);
}

function renderAgentList() {
  const listEl = $("#agent-list");
  if (!listEl) return;
  const items = state.agentProfiles.list || [];
  listEl.innerHTML = items
    .map((profile) => {
      const id = escapeHtml(profile.id);
      const name = escapeHtml(profile.name || profile.id);
      const tagline = escapeHtml(profile.tagline || "");
      const applyTo = escapeHtml((profile.apply_to || []).join(", "));
      const active =
        state.agentProfiles.activeId === profile.id &&
        state.agentProfiles.activeSource === profile.source;
      return `
        <button class="agent-item ${active ? "active" : ""}" data-id="${id}" data-source="${profile.source}">
          <div>
            <strong>${name}</strong>
            <div class="agent-meta">${id}${applyTo ? ` · ${applyTo}` : ""}</div>
            ${tagline ? `<div class="agent-meta">${tagline}</div>` : ""}
          </div>
          <span class="agent-source">${escapeHtml(profile.source)}</span>
        </button>
      `;
    })
    .join("");
  [...listEl.querySelectorAll(".agent-item")].forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      const source = btn.dataset.source;
      if (id && source) {
        openAgentProfile(id, source);
      }
    });
  });
}

function renderAgentProfileSelect() {
  const select = $("#federlicht-agent-profile");
  if (!select) return;
  const items = state.agentProfiles.list || [];
  select.innerHTML = items
    .map((profile) => {
      const label = profile.name || profile.id;
      const source = profile.source || "builtin";
      const suffix = source === "site" ? "site" : "builtin";
      return `<option value="${escapeHtml(profile.id)}" data-source="${escapeHtml(
        source,
      )}">${escapeHtml(label)} (${suffix})</option>`;
    })
    .join("");
  if (state.agentProfiles.activeId) {
    const opt = Array.from(select.options).find(
      (o) => o.value === state.agentProfiles.activeId,
    );
    if (opt) {
      select.value = opt.value;
    }
  }
}

function fillAgentForm(profile, memoryText, source, readOnly) {
  const memoryHook = profile?.memory_hook || {};
  $("#agent-id").value = profile?.id || "";
  $("#agent-name").value = profile?.name || "";
  $("#agent-tagline").value = profile?.tagline || "";
  $("#agent-apply-to").value = (profile?.apply_to || []).join(", ");
  $("#agent-system-prompt").value = profile?.system_prompt || "";
  $("#agent-memory-desc").value = memoryHook?.description || "";
  $("#agent-memory-path").value = memoryHook?.path || "";
  $("#agent-memory-text").value = memoryText || "";
  const storeCheck = $("#agent-store-site");
  if (storeCheck) {
    storeCheck.checked = true;
    storeCheck.disabled = true;
  }
  const meta = $("#agent-editor-meta");
  if (meta) {
    meta.textContent = readOnly
      ? `Read-only built-in profile · ${source}`
      : `Editable profile · ${source}`;
  }
}

async function openAgentProfile(id, source) {
  try {
    const detail = await fetchJSON(`/api/agent-profiles/${encodeURIComponent(id)}?source=${encodeURIComponent(source)}`);
    state.agentProfiles.activeId = id;
    state.agentProfiles.activeSource = source;
    state.agentProfiles.activeProfile = detail.profile;
    state.agentProfiles.memoryText = detail.memory_text || "";
    state.agentProfiles.readOnly = Boolean(detail.read_only);
    fillAgentForm(detail.profile, detail.memory_text, source, detail.read_only);
    renderAgentList();
    renderAgentProfileSelect();
    setAgentStatus("Profile loaded.");
  } catch (err) {
    setAgentStatus(`Failed to load profile: ${err}`);
  }
}

function newAgentProfile() {
  state.agentProfiles.activeId = "";
  state.agentProfiles.activeSource = "site";
  state.agentProfiles.activeProfile = {
    id: "",
    name: "",
    tagline: "",
    apply_to: [],
    system_prompt: "",
    memory_hook: {},
  };
  state.agentProfiles.memoryText = "";
  state.agentProfiles.readOnly = false;
  fillAgentForm(state.agentProfiles.activeProfile, "", "site", false);
  renderAgentList();
  setAgentStatus("New profile (site) ready.");
}

function readAgentForm() {
  const id = $("#agent-id").value.trim();
  const name = $("#agent-name").value.trim();
  const tagline = $("#agent-tagline").value.trim();
  const applyTo = normalizeApplyTo($("#agent-apply-to").value);
  const systemPrompt = $("#agent-system-prompt").value;
  const memoryDesc = $("#agent-memory-desc").value.trim();
  const memoryPath = $("#agent-memory-path").value.trim();
  const memoryText = $("#agent-memory-text").value;
  const profile = {
    id,
    name,
    tagline,
    apply_to: applyTo,
    system_prompt: systemPrompt,
  };
  if (memoryDesc || memoryPath) {
    profile.memory_hook = {
      description: memoryDesc,
      path: memoryPath || undefined,
    };
  }
  return { profile, memoryText };
}

async function saveAgentProfile() {
  try {
    const { profile, memoryText } = readAgentForm();
    if (!profile.id) {
      setAgentStatus("Profile ID is required.");
      return;
    }
    if (state.agentProfiles.readOnly && profile.id === state.agentProfiles.activeId) {
      setAgentStatus("Built-in profiles are read-only. Clone and save with a new ID.");
      return;
    }
    setAgentStatus("Saving profile...");
    await fetchJSON("/api/agent-profiles/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile,
        memory_text: memoryText,
        store: "site",
      }),
    });
    await loadAgentProfiles(profile.id, "site");
    setAgentStatus("Profile saved.");
  } catch (err) {
    setAgentStatus(`Save failed: ${err}`);
  }
}

async function deleteAgentProfile() {
  try {
    if (state.agentProfiles.readOnly) {
      setAgentStatus("Built-in profiles cannot be deleted.");
      return;
    }
    const id = $("#agent-id").value.trim();
    if (!id) {
      setAgentStatus("Profile ID is required.");
      return;
    }
    setAgentStatus("Deleting profile...");
    await fetchJSON("/api/agent-profiles/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await loadAgentProfiles();
    newAgentProfile();
    setAgentStatus("Profile deleted.");
  } catch (err) {
    setAgentStatus(`Delete failed: ${err}`);
  }
}

function cloneAgentProfile() {
  const { profile, memoryText } = readAgentForm();
  const base = profile.id || "profile";
  profile.id = `${base}_copy`;
  $("#agent-id").value = profile.id;
  state.agentProfiles.readOnly = false;
  setAgentStatus("Cloned. Update the ID and save.");
}

async function loadAgentProfiles(selectId, selectSource) {
  try {
    const payload = await fetchJSON("/api/agent-profiles");
    state.agentProfiles.list = payload.profiles || [];
    renderAgentList();
    renderAgentProfileSelect();
    if (selectId && selectSource) {
      await openAgentProfile(selectId, selectSource);
      return;
    }
    if (!state.agentProfiles.activeId && state.agentProfiles.list.length) {
      const first = state.agentProfiles.list[0];
      await openAgentProfile(first.id, first.source);
    }
  } catch (err) {
    setAgentStatus(`Failed to load profiles: ${err}`);
  }
}

function handleAgentPanelToggle() {
  const panel = $("#agent-panel");
  const button = $("#agent-panel-toggle");
  if (!panel || !button) return;
  const stored = localStorage.getItem("federnett-agent-panel-collapsed");
  if (stored === "true") {
    panel.classList.add("collapsed");
    button.textContent = "Show panel";
  }
  button.addEventListener("click", () => {
    const collapsed = panel.classList.toggle("collapsed");
    button.textContent = collapsed ? "Show panel" : "Hide panel";
    localStorage.setItem("federnett-agent-panel-collapsed", collapsed ? "true" : "false");
  });
}

function handleAgentProfiles() {
  $("#agent-new")?.addEventListener("click", () => newAgentProfile());
  $("#agent-save")?.addEventListener("click", () => saveAgentProfile());
  $("#agent-delete")?.addEventListener("click", () => deleteAgentProfile());
  $("#agent-clone")?.addEventListener("click", () => cloneAgentProfile());
}

function handleLayoutSplitter() {
  const splitter = $("#layout-splitter");
  const layout = $(".layout");
  if (!splitter || !layout) return;
  const rootStyle = document.documentElement.style;
  const saved = localStorage.getItem("federnett-telemetry-width");
  if (saved) {
    rootStyle.setProperty("--telemetry-width", saved);
  }
  let dragging = false;
  const onMove = (event) => {
    if (!dragging) return;
    const rect = layout.getBoundingClientRect();
    const minWidth = 280;
    const maxWidth = Math.max(minWidth, rect.width - 420);
    const next = Math.min(Math.max(rect.right - event.clientX, minWidth), maxWidth);
    rootStyle.setProperty("--telemetry-width", `${Math.round(next)}px`);
  };
  const stopDrag = () => {
    if (!dragging) return;
    dragging = false;
    layout.classList.remove("resizing");
    localStorage.setItem(
      "federnett-telemetry-width",
      rootStyle.getPropertyValue("--telemetry-width"),
    );
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", stopDrag);
  };
  splitter.addEventListener("pointerdown", (event) => {
    dragging = true;
    layout.classList.add("resizing");
    splitter.setPointerCapture(event.pointerId);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", stopDrag);
  });
}

function handleTelemetrySplitter() {
  const splitter = $("#telemetry-splitter");
  const wrap = $("#logs-wrap");
  if (!splitter || !wrap) return;
  const rootStyle = document.documentElement.style;
  const saved = localStorage.getItem("federnett-log-height");
  if (saved) {
    const parsed = Number.parseFloat(saved);
    if (Number.isFinite(parsed)) {
      const clamped = Math.max(220, parsed);
      rootStyle.setProperty("--telemetry-log-height", `${Math.round(clamped)}px`);
    }
  }
  let dragging = false;
  const onMove = (event) => {
    if (!dragging) return;
    const rect = wrap.getBoundingClientRect();
    const minHeight = 220;
    const maxHeight = Math.max(minHeight, rect.height - 220);
    const next = Math.min(Math.max(event.clientY - rect.top, minHeight), maxHeight);
    rootStyle.setProperty("--telemetry-log-height", `${Math.round(next)}px`);
  };
  const stopDrag = () => {
    if (!dragging) return;
    dragging = false;
    localStorage.setItem(
      "federnett-log-height",
      rootStyle.getPropertyValue("--telemetry-log-height"),
    );
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", stopDrag);
  };
  splitter.addEventListener("pointerdown", (event) => {
    dragging = true;
    splitter.setPointerCapture(event.pointerId);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", stopDrag);
  });
}

function bindForms() {
  $("#feather-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const payload = buildFeatherPayload();
      const runRel = payload.output;
      const runName = $("#feather-run-name")?.value?.trim();
      const outputPath = normalizePathString(payload.output);
      const inputPath = normalizePathString(payload.input);
      const outputIsRunFolder =
        outputPath &&
        ((runName && outputPath.endsWith(`/${runName}`)) ||
          outputPath.includes("/runs/"));
      const inputInsideOutput =
        inputPath && outputPath && inputPath.startsWith(`${outputPath}/`);
      if (outputIsRunFolder && inputInsideOutput) {
        const derivedName = runName || outputPath.split("/").pop() || "run";
        const outputRoot = parentPath(outputPath) || ".";
        const instructionPath = `${outputPath}/instruction/${derivedName}.txt`;
        payload.output = outputRoot;
        payload.input = instructionPath;
        $("#feather-input").value = instructionPath;
        const content = $("#feather-query")?.value || "";
        if (content.trim()) {
          await saveInstructionContent(instructionPath, content);
          setFeatherInstructionSnapshot(instructionPath, content);
        }
        appendLog(
          `[feather] output looks like a run folder, using output root ${outputRoot} and instruction ${instructionPath}\n`,
        );
      } else if (payload.input) {
        const normalized = normalizeFeatherInstructionPath(payload.input);
        payload.input = normalized;
        const content = $("#feather-query")?.value || "";
        if (content.trim()) {
          await saveInstructionContent(normalized, content);
          setFeatherInstructionSnapshot(normalized, content);
        }
      }
      await startJob("/api/feather/start", payload, {
        kind: "feather",
        onSuccess: async () => {
          await loadRuns().catch(() => {});
          if (runRel && $("#run-select")) {
            $("#run-select").value = runRel;
            if ($("#prompt-run-select")) $("#prompt-run-select").value = runRel;
            if ($("#instruction-run-select")) $("#instruction-run-select").value = runRel;
            refreshRunDependentFields();
            await updateRunStudio(runRel).catch(() => {});
          }
        },
      });
    } catch (err) {
      appendLog(`[feather] ${err}\n`);
    }
  });

  $("#federlicht-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const payload = buildFederlichtPayload();
      const runRel = payload.run;
      await startJob("/api/federlicht/start", payload, {
        kind: "federlicht",
        onSuccess: async () => {
          await loadRuns().catch(() => {});
          if (runRel && $("#run-select")) {
            $("#run-select").value = runRel;
            if ($("#instruction-run-select")) $("#instruction-run-select").value = runRel;
            refreshRunDependentFields();
            await updateRunStudio(runRel).catch(() => {});
          }
        },
      });
    } catch (err) {
      appendLog(`[federlicht] ${err}\n`);
    }
  });

  $("#prompt-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const payload = buildPromptPayload();
      const outputPath = payload.output;
      await startJob("/api/federlicht/generate_prompt", payload, {
        kind: "prompt",
        onSuccess: () => {
          if (outputPath) {
            $("#federlicht-prompt-file").value = outputPath;
            syncPromptFromFile(true).catch((err) => {
              if (!isMissingFileError(err)) {
                appendLog(`[prompt] failed to load: ${err}\n`);
              }
            });
            appendLog(`[prompt] ready: ${outputPath}\n`);
          }
        },
      });
    } catch (err) {
      appendLog(`[prompt] ${err}\n`);
    }
  });
}

function handleTemplatesPanelToggle() {
  const panel = $("#templates-panel");
  const button = $("#templates-toggle");
  if (!panel || !button) return;
  const stored = localStorage.getItem("federnett-templates-collapsed");
  if (stored === "true") {
    panel.classList.add("collapsed");
    button.textContent = "Show cards";
  }
  button.addEventListener("click", () => {
    const collapsed = panel.classList.toggle("collapsed");
    button.textContent = collapsed ? "Show cards" : "Hide cards";
    localStorage.setItem("federnett-templates-collapsed", collapsed ? "true" : "false");
  });
}

async function loadModelOptions() {
  const datalist = $("#model-options");
  if (!datalist) return;
  try {
    const models = await fetchJSON("/api/models");
    if (Array.isArray(models)) {
      datalist.innerHTML = models.map((m) => `<option value="${escapeHtml(m)}"></option>`).join("");
    }
  } catch (err) {
    appendLog(`[models] ${err}\n`);
  }
}

async function bootstrap() {
  initTheme();
  handleTabs();
  handleFeatherRunName();
  handleRunOutputTouch();
  handlePipelineInputs();
  handleRunChanges();
  handleRunOpen();
  handleInstructionEditor();
  handleFilePreviewControls();
  handleFeatherInstructionPicker();
  handleUploadDrop();
  handleFederlichtPromptPicker();
  handleFederlichtPromptEditor();
  handleRunPicker();
  handleJobsModal();
  handleReloadRuns();
  handleLogControls();
  handleTemplateSync();
  handleTemplateEditor();
  handleTemplateGenerator();
  handleTemplatesPanelToggle();
  handleAgentProfiles();
  handleAgentPanelToggle();
  bindTemplateModalClose();
  bindHelpModal();
  handleLayoutSplitter();
  handleTelemetrySplitter();
  bindForms();
  setFederlichtRunEnabled(true);
  renderJobs();

  try {
    await loadInfo();
    bindHeroCards();
    initPipelineFromInputs();
    await Promise.all([loadTemplates(), loadRuns(), loadModelOptions(), loadAgentProfiles()]);
  } catch (err) {
    appendLog(`[init] ${err}\n`);
  }
}

bootstrap();
