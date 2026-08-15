const $ = (id) => document.getElementById(id);

const els = {
  apiKey: $("apiKey"),
  model: $("model"),
  baseUrl: $("baseUrl"),
  temperature: $("temperature"),
  maxAttempts: $("maxAttempts"),
  instructions: $("instructions"),
  generate: $("generate"),
  stop: $("stop"),
  clearLog: $("clearLog"),
  log: $("log"),
  kind: $("kind"),
  rootElement: $("rootElement"),
  example: $("example"),
  schemaFile: $("schemaFile"),
  schema: $("schema"),
  data: $("data"),
  issues: $("issues"),
  verdict: $("verdict"),
  validate: $("validate"),
  format: $("format"),
  download: $("download"),
  connection: $("connection"),
};

const SETTINGS_KEY = "schema-data-forge.settings";
let examples = [];
let controller = null;

// ----------------------------------------------------------------- utilities

function setStatus(text, tone = "idle") {
  els.connection.textContent = text;
  els.connection.className = `pill pill-${tone}`;
}

function log(message, tone = "info") {
  const item = document.createElement("li");
  item.className = tone;
  item.textContent = message;
  els.log.appendChild(item);
  els.log.scrollTop = els.log.scrollHeight;
}

async function api(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function saveSettings() {
  localStorage.setItem(
    SETTINGS_KEY,
    JSON.stringify({
      apiKey: els.apiKey.value,
      model: els.model.value,
      baseUrl: els.baseUrl.value,
      temperature: els.temperature.value,
      maxAttempts: els.maxAttempts.value,
    }),
  );
}

function restoreSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    for (const [key, value] of Object.entries(stored)) {
      if (value && els[key]) els[key].value = value;
    }
  } catch {
    /* ignore corrupted settings */
  }
}

// ---------------------------------------------------------------- validation

function renderReport(report) {
  els.issues.innerHTML = "";
  const rows = [];

  if (report.schemaError) {
    els.verdict.textContent = "Schema 无法编译";
    els.verdict.className = "verdict err";
    rows.push({ location: "<schema>", line: "", message: report.schemaError });
  } else if (report.parseError) {
    els.verdict.textContent = `文档解析失败（${kindLabel()}）`;
    els.verdict.className = "verdict err";
    rows.push({ location: "<document>", line: "", message: report.parseError });
  } else if (report.valid) {
    els.verdict.textContent = "校验通过：0 个错误";
    els.verdict.className = "verdict ok";
  } else {
    els.verdict.textContent = `校验失败：${report.issues.length} 个错误`;
    els.verdict.className = "verdict err";
    for (const issue of report.issues) {
      rows.push({
        location: issue.location || "<document>",
        line: issue.line ?? "",
        message: issue.message,
      });
    }
  }

  if (rows.length === 0) {
    const empty = document.createElement("tr");
    empty.className = "empty";
    empty.innerHTML = "<td colspan='3'>暂无校验错误</td>";
    els.issues.appendChild(empty);
    return;
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const value of [row.location, row.line, row.message]) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    if (row.line) tr.addEventListener("click", () => jumpToLine(Number(row.line)));
    els.issues.appendChild(tr);
  }
}

function jumpToLine(line) {
  const lines = els.data.value.split("\n");
  const offset = lines.slice(0, Math.max(0, line - 1)).reduce((n, l) => n + l.length + 1, 0);
  els.data.focus();
  els.data.setSelectionRange(offset, offset + (lines[line - 1] || "").length);
  const ratio = (line - 1) / Math.max(1, lines.length);
  els.data.scrollTop = ratio * els.data.scrollHeight;
}

function kindLabel() {
  return els.kind.value === "xml-schema" ? "XML" : "JSON";
}

// -------------------------------------------------------------------- schema

async function refreshRootElements() {
  const isXsd = els.kind.value === "xml-schema";
  els.rootElement.disabled = !isXsd;
  els.rootElement.innerHTML = "";
  if (!isXsd) {
    els.rootElement.appendChild(new Option("（JSON Schema 无需根元素）", ""));
    return;
  }
  let names = [];
  try {
    names = await api("/api/root-elements", { schemaText: els.schema.value });
  } catch {
    names = [];
  }
  if (names.length === 0) {
    els.rootElement.appendChild(new Option("（无法解析 XSD 根元素）", ""));
    return;
  }
  for (const name of names) els.rootElement.appendChild(new Option(name, name));
}

function applyExample(example) {
  els.kind.value = example.kind;
  els.schema.value = example.schemaText;
  els.instructions.value = example.instructions;
  refreshRootElements().then(() => {
    if (example.rootElement) els.rootElement.value = example.rootElement;
  });
}

async function loadExamples() {
  const response = await fetch("/api/examples");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  examples = await response.json();
  els.example.innerHTML = "";
  examples.forEach((example, index) => {
    els.example.appendChild(new Option(example.title, String(index)));
  });
  if (examples.length > 0) applyExample(examples[0]);
}

// ---------------------------------------------------------------- generation

function setRunning(running) {
  els.generate.disabled = running;
  els.stop.disabled = !running;
  els.validate.disabled = running;
}

function handleEvent(event, payload) {
  if (event === "start") {
    log(`开始生成（${payload.kind === "xml-schema" ? "XML" : "JSON"}，最多 ${payload.maxAttempts} 次尝试）`);
    return;
  }
  if (event === "attempt") {
    if (payload.document) els.data.value = payload.document;
    renderReport(payload.report);
    const report = payload.report;
    if (report.valid) {
      log(`第 ${payload.index} 次尝试：校验通过`, "ok");
    } else if (report.schemaError) {
      log(`第 ${payload.index} 次尝试：schema 无法编译 — ${report.schemaError}`, "err");
    } else if (report.parseError) {
      log(`第 ${payload.index} 次尝试：文档无法解析 — ${report.parseError}`, "err");
    } else {
      const detail = report.issues
        .slice(0, 8)
        .map((issue) => `  - ${issue.location || "<document>"}: ${issue.message}`)
        .join("\n");
      log(`第 ${payload.index} 次尝试：${report.issues.length} 个校验错误\n${detail}`, "err");
    }
    return;
  }
  if (event === "done") {
    if (payload.succeeded) {
      log(`完成：第 ${payload.attempts} 次尝试后通过校验`, "ok");
      setStatus("生成完成，已通过校验", "ok");
    } else {
      log("完成：仍未通过校验（可提高最大尝试次数或补充生成要求后重试）", "err");
      setStatus("未通过校验", "err");
    }
    return;
  }
  if (event === "error") {
    log(`错误：${payload.message}`, "err");
    setStatus("生成失败", "err");
  }
}

async function generate() {
  if (!els.schema.value.trim()) {
    log("请先填入 JSON Schema 或 XSD", "err");
    return;
  }
  saveSettings();
  setRunning(true);
  setStatus("生成中…", "busy");
  controller = new AbortController();

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        schemaText: els.schema.value,
        kind: els.kind.value,
        instructions: els.instructions.value,
        rootElement: els.rootElement.disabled ? "" : els.rootElement.value,
        maxAttempts: Number(els.maxAttempts.value),
        apiKey: els.apiKey.value,
        model: els.model.value,
        baseUrl: els.baseUrl.value,
        temperature: Number(els.temperature.value),
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const eventLine = chunk.split("\n").find((line) => line.startsWith("event: "));
        const dataLine = chunk.split("\n").find((line) => line.startsWith("data: "));
        if (!eventLine || !dataLine) continue;
        handleEvent(eventLine.slice(7).trim(), JSON.parse(dataLine.slice(6)));
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      log("已停止本次生成", "info");
      setStatus("已停止", "idle");
    } else {
      log(`错误：${error.message}`, "err");
      setStatus("生成失败", "err");
    }
  } finally {
    controller = null;
    setRunning(false);
  }
}

// ------------------------------------------------------------------- wiring

els.generate.addEventListener("click", generate);
els.stop.addEventListener("click", () => controller?.abort());
els.clearLog.addEventListener("click", () => (els.log.innerHTML = ""));

els.validate.addEventListener("click", async () => {
  if (!els.data.value.trim()) {
    log("没有可校验的数据", "err");
    return;
  }
  try {
    const report = await api("/api/validate", {
      document: els.data.value,
      schemaText: els.schema.value,
      kind: els.kind.value,
    });
    renderReport(report);
    log(report.valid ? "手动校验：通过" : "手动校验：未通过", report.valid ? "ok" : "err");
  } catch (error) {
    log(`校验失败：${error.message}`, "err");
  }
});

els.format.addEventListener("click", async () => {
  if (!els.data.value.trim()) return;
  const { document: formatted } = await api("/api/format", {
    document: els.data.value,
    kind: els.kind.value,
  });
  els.data.value = formatted;
});

els.download.addEventListener("click", () => {
  const isXml = els.kind.value === "xml-schema";
  const blob = new Blob([els.data.value], {
    type: isXml ? "application/xml" : "application/json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = isXml ? "sample.xml" : "sample.json";
  link.click();
  URL.revokeObjectURL(link.href);
});

els.kind.addEventListener("change", refreshRootElements);
els.example.addEventListener("change", () => applyExample(examples[Number(els.example.value)]));
els.schema.addEventListener("change", refreshRootElements);

els.schemaFile.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  const text = await file.text();
  els.schema.value = text;
  els.kind.value = text.trimStart().startsWith("<") ? "xml-schema" : "json-schema";
  await refreshRootElements();
  log(`已载入 ${file.name}`);
});

for (const input of [els.apiKey, els.model, els.baseUrl, els.temperature, els.maxAttempts]) {
  input.addEventListener("change", saveSettings);
}

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    if (!els.generate.disabled) generate();
  }
});

restoreSettings();
loadExamples().catch((error) => log(`加载示例失败：${error.message}`, "err"));
