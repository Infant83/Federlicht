const $ = (sel) => document.querySelector(sel);

const state = {
  info: null,
  runRel: "",
  reportRel: "",
  baseRel: "",
  outputRel: "",
  updateRel: "",
  reportText: "",
  reportMeta: {},
  summary: null,
  logBuffer: [],
  logVisible: true,
  activeJobId: null,
  messages: [],
};

const LOG_LIMIT = 800;

async function fetchJSON(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${text}`.trim());
  }
  return res.json();
}

function normalizePathString(value) {
  return String(value || "")
    .trim()
    .replaceAll("\\", "/")
    .replace(/^\.\//, "")
    .replace(/\/+/g, "/");
}

function rawFileUrl(relPath) {
  const cleaned = normalizePathString(relPath);
  if (!cleaned) return "";
  const encoded = cleaned
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `/raw/${encoded}`;
}

function setStatus(text, running = false) {
  const el = $("#canvas-status");
  if (el) el.textContent = text || "";
  const pill = $("#canvas-job-pill");
  if (pill) {
    pill.textContent = running ? "Running" : "Idle";
    pill.style.opacity = running ? "1" : "0.7";
  }
}

function renderChat() {
  const host = $("#canvas-chat");
  if (!host) return;
  host.innerHTML = state.messages
    .map((msg) => {
      const role = msg.role || "assistant";
      const meta = msg.meta ? `<div class="meta">${msg.meta}</div>` : "";
      const body = msg.html ? msg.content : escapeMultiline(msg.content);
      return `<div class="chat-message ${role}">${meta}<div>${body}</div></div>`;
    })
    .join("");
  host.scrollTop = host.scrollHeight;
}

function addMessage(role, content, meta = "", html = false) {
  state.messages.push({ role, content, meta, html });
  renderChat();
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeMultiline(value) {
  return escapeHtml(value).replace(/\n/g, "<br>");
}

function updateLogView() {
  const log = $("#canvas-log");
  if (!log) return;
  log.textContent = state.logBuffer.join("");
  log.scrollTop = log.scrollHeight;
}

function appendLog(text) {
  if (!text) return;
  state.logBuffer.push(text);
  if (state.logBuffer.length > LOG_LIMIT) {
    state.logBuffer.splice(0, state.logBuffer.length - LOG_LIMIT);
  }
  updateLogView();
}

function extractTextFromHtml(html) {
  const doc = new DOMParser().parseFromString(html || "", "text/html");
  doc.querySelectorAll("script,style,noscript").forEach((el) => el.remove());
  const text = doc.body?.textContent || "";
  return text.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

function inferRunRel(reportRel, runRoots = []) {
  const cleaned = normalizePathString(reportRel);
  for (const root of runRoots) {
    const prefix = normalizePathString(root);
    if (!prefix) continue;
    if (cleaned.startsWith(`${prefix}/`)) {
      const rest = cleaned.slice(prefix.length + 1);
      const head = rest.split("/")[0];
      if (head) return `${prefix}/${head}`;
    }
  }
  const parts = cleaned.split("/").filter(Boolean);
  if (parts.length >= 2) return parts.slice(0, 2).join("/");
  return cleaned;
}

function stripRunPrefix(pathValue, runRel) {
  const cleaned = normalizePathString(pathValue);
  const runPath = normalizePathString(runRel);
  if (runPath && cleaned.startsWith(`${runPath}/`)) {
    return cleaned.slice(runPath.length + 1);
  }
  return cleaned;
}

function nextReportPathFromSummary(summary) {
  const files = summary?.report_files || [];
  let maxIndex = -1;
  let hasBase = false;
  files.forEach((rel) => {
    const name = (rel.split("/").pop() || "").trim();
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
  if (!hasBase && maxIndex < 0) return `${summary?.run_rel}/report_full.html`;
  return `${summary?.run_rel}/report_full_${maxIndex + 1}.html`;
}

async function nextUpdateRequestPath(runRel) {
  if (!runRel) return "";
  const now = new Date();
  const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(
    now.getDate(),
  ).padStart(2, "0")}`;
  const dir = `${runRel}/report_notes`;
  let entries = [];
  try {
    const listing = await fetchJSON(`/api/fs?path=${encodeURIComponent(dir)}`);
    entries = (listing.entries || []).map((entry) => entry.name);
  } catch (err) {
    entries = [];
  }
  let name = `update_request_${stamp}.txt`;
  if (entries.includes(name)) {
    let idx = 1;
    while (entries.includes(`update_request_${stamp}_${idx}.txt`)) idx += 1;
    name = `update_request_${stamp}_${idx}.txt`;
  }
  return `${dir}/${name}`;
}

function buildUpdatePromptContent(updateText, secondPrompt, baseRel, selection) {
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

function setSelection(value) {
  const box = $("#canvas-selection");
  if (box) box.value = value || "";
  highlightSelectionInText(value || "");
}

function highlightSelectionInText(selection) {
  if (!selection) return;
  const textArea = $("#canvas-report-text");
  if (!textArea) return;
  const idx = textArea.value.indexOf(selection);
  if (idx < 0) return;
  textArea.focus();
  textArea.setSelectionRange(idx, idx + selection.length);
}

function renderOutputs(summary, activeRel) {
  const list = $("#canvas-report-list");
  if (!list) return;
  const reports = summary?.report_files || [];
  if (!reports.length) {
    list.innerHTML = `<div class="muted">No reports found.</div>`;
    return;
  }
  list.innerHTML = reports
    .slice()
    .reverse()
    .map((rel) => {
      const name = rel.split("/").pop() || rel;
      const isActive = activeRel === rel;
      return `<div class="output-item ${isActive ? "active" : ""}" data-rel="${rel}">
        <span>${escapeHtml(name)}</span>
        <span class="muted">${isActive ? "active" : ""}</span>
      </div>`;
    })
    .join("");
  list.querySelectorAll("[data-rel]").forEach((item) => {
    item.addEventListener("click", () => {
      const rel = item.getAttribute("data-rel");
      if (rel) selectReport(rel);
    });
  });
}

async function loadUpdateHistory(runRel) {
  const historyPath = `${runRel}/report_notes/update_history.jsonl`;
  try {
    const data = await fetchJSON(`/api/files?path=${encodeURIComponent(historyPath)}`);
    const lines = (data.content || "").split("\n").filter(Boolean);
    lines.forEach((line) => {
      try {
        const entry = JSON.parse(line);
        if (entry.update_notes) {
          addMessage("user", entry.update_notes, "previous update");
        }
        if (entry.output_path) {
          const rel = normalizePathString(entry.output_path.replace(/^\.\//, ""));
          addMessage(
            "assistant",
            `Updated report: <a href="${rawFileUrl(rel)}" target="_blank" rel="noreferrer">${escapeHtml(rel)}</a>`,
            "completed",
            true
          );
        }
      } catch (err) {
        // ignore parse errors
      }
    });
  } catch (err) {
    // no history
  }
}

async function selectReport(reportRel) {
  state.reportRel = reportRel;
  state.baseRel = stripRunPrefix(reportRel, state.runRel);
  $("#canvas-base-rel").textContent = `base: ${state.baseRel}`;
  const frame = $("#canvas-preview-frame");
  if (frame) frame.src = rawFileUrl(reportRel);
  try {
    const data = await fetchJSON(`/api/files?path=${encodeURIComponent(reportRel)}`);
    state.reportText = extractTextFromHtml(data.content || "");
    $("#canvas-report-text").value = state.reportText;
  } catch (err) {
    appendLog(`[preview] failed to load report text: ${err}\n`);
  }
  renderOutputs(state.summary, reportRel);
}

function attachLogStream(jobId, onDone) {
  if (!jobId) return;
  if (state.activeJobId && state.activeJobId !== jobId) {
    state.activeJobId = jobId;
  }
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  source.addEventListener("log", (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload?.text) appendLog(`${payload.text}\n`);
    } catch (err) {
      // ignore
    }
  });
  source.addEventListener("done", () => {
    source.close();
    state.activeJobId = null;
    setStatus("Ready", false);
    if (onDone) onDone();
  });
}

async function startUpdate() {
  const updateText = $("#canvas-update")?.value?.trim();
  if (!updateText) {
    setStatus("Update instructions are required.", false);
    return;
  }
  const secondPrompt = $("#canvas-second")?.value?.trim();
  const selection = $("#canvas-selection")?.value?.trim();
  const outputRel = $("#canvas-output-path")?.value?.trim() || state.outputRel;
  const updateRel = $("#canvas-update-path")?.value?.trim() || state.updateRel;

  addMessage("user", updateText, "new update");
  if (selection) addMessage("system", `Selection locked (${selection.length} chars).`, "selection");

  const content = buildUpdatePromptContent(updateText, secondPrompt, state.baseRel, selection);
  setStatus("Saving update prompt...", true);
  await fetchJSON("/api/files", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: updateRel, content }),
  });

  setStatus("Running update...", true);
  const payload = {
    run: state.runRel,
    output: outputRel,
    prompt_file: updateRel,
  };
  const freeFormat = !!state.reportMeta?.free_format;
  if (freeFormat) {
    payload.free_format = true;
  } else if (state.reportMeta?.template) {
    payload.template = state.reportMeta.template;
  }
  if (state.reportMeta?.language) payload.lang = state.reportMeta.language;
  if (state.reportMeta?.model) payload.model = state.reportMeta.model;
  if (state.reportMeta?.quality_model) payload.check_model = state.reportMeta.quality_model;
  if (state.reportMeta?.model_vision) payload.model_vision = state.reportMeta.model_vision;

  const result = await fetchJSON("/api/federlicht/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (result?.job_id) {
    addMessage("assistant", "Update started. Streaming logs below.", "assistant");
    attachLogStream(result.job_id, async () => {
      try {
        const refreshed = await fetchJSON(
          `/api/run-summary?run=${encodeURIComponent(state.runRel)}`,
        );
        state.summary = refreshed;
        const latest = refreshed?.latest_report_rel || state.reportRel;
        renderOutputs(refreshed, latest);
        if (latest) {
          await selectReport(latest);
          addMessage(
            "assistant",
            `Updated report: <a href="${rawFileUrl(latest)}" target="_blank" rel="noreferrer">${escapeHtml(latest)}</a>`,
            "completed",
            true,
          );
        }
      } catch (err) {
        appendLog(`[update] refresh failed: ${err}\n`);
      }
    });
  }

  state.outputRel = outputRel;
  $("#canvas-output-path").value = state.outputRel;
}

async function bootstrap() {
  $("#canvas-back")?.addEventListener("click", () => {
    window.location.href = "./index.html";
  });

  $("#canvas-open-hub")?.addEventListener("click", () => {
    window.open("../index.html", "_blank", "noopener");
  });

  $("#canvas-open-report")?.addEventListener("click", () => {
    if (state.reportRel) window.open(rawFileUrl(state.reportRel), "_blank", "noopener");
  });

  $("#canvas-log-toggle")?.addEventListener("click", () => {
    state.logVisible = !state.logVisible;
    const log = $("#canvas-log");
    if (log) log.style.display = state.logVisible ? "block" : "none";
    $("#canvas-log-toggle").textContent = state.logVisible ? "Hide" : "Show";
  });

  $("#canvas-use-selection")?.addEventListener("click", () => {
    const textArea = $("#canvas-report-text");
    if (!textArea) return;
    const start = textArea.selectionStart || 0;
    const end = textArea.selectionEnd || 0;
    if (start === end) return;
    const sel = textArea.value.slice(start, end).trim();
    if (sel) setSelection(sel);
  });

  $("#canvas-clear-selection")?.addEventListener("click", () => setSelection(""));

  $("#canvas-report-text")?.addEventListener("mouseup", () => {
    const textArea = $("#canvas-report-text");
    if (!textArea) return;
    const start = textArea.selectionStart || 0;
    const end = textArea.selectionEnd || 0;
    if (start === end) return;
    const sel = textArea.value.slice(start, end).trim();
    if (sel) setSelection(sel);
  });

  const params = new URLSearchParams(window.location.search);
  const report = normalizePathString(params.get("report"));
  if (!report) {
    setStatus("No report selected.", false);
    return;
  }

  setStatus("Loading...", true);
  state.info = await fetchJSON("/api/info");
  state.reportRel = report;
  state.runRel = inferRunRel(report, state.info?.run_roots || []);
  state.baseRel = stripRunPrefix(report, state.runRel);
  $("#canvas-run-rel").textContent = `run: ${state.runRel || "-"}`;
  $("#canvas-base-rel").textContent = `base: ${state.baseRel || "-"}`;

  const summary = await fetchJSON(`/api/run-summary?run=${encodeURIComponent(state.runRel)}`);
  state.summary = summary;
  state.reportMeta = summary?.report_meta || {};
  renderOutputs(summary, report);
  state.outputRel = nextReportPathFromSummary(summary);
  $("#canvas-output-path").value = state.outputRel;
  state.updateRel = await nextUpdateRequestPath(state.runRel);
  $("#canvas-update-path").value = state.updateRel;

  await selectReport(report);
  await loadUpdateHistory(state.runRel);

  const frame = $("#canvas-preview-frame");
  if (frame) {
    frame.addEventListener("load", () => {
      try {
        const doc = frame.contentDocument;
        if (!doc) return;
        doc.addEventListener("mouseup", () => {
          const selection = doc.getSelection()?.toString().trim();
          if (selection) setSelection(selection);
        });
      } catch (err) {
        // ignore selection errors
      }
    });
  }

  $("#canvas-run")?.addEventListener("click", () => startUpdate());

  setStatus("Ready", false);
}

bootstrap().catch((err) => {
  setStatus(`Failed to load: ${err}`, false);
});
