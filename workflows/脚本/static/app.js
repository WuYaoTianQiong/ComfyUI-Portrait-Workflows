const API = "";
const LS_UI = "promptBrowserUiState_v3";
const LS_CUSTOM_WF = "promptBrowserCustomWorkflow_v3";
const LS_HIDDEN_WF = "promptBrowserHiddenWorkflows";

let allPrompts = [];
let selectedId = null;
let lastClickedId = null;
let comfyStatus = "offline";
let workflowList = [];
let workflowSort = "mtime";
let hiddenWorkflows = [];
let selectedIds = new Set();
let currentOrientation = "portrait";
let activeJobId = null;
let jobPollTimer = null;
let activeJobs = new Set();
let _currentPromptData = null;
let _customWorkflow = null;
let _wfPopoverOpen = false;

const UiState = {
  data: {},
  load() {
    try { this.data = JSON.parse(localStorage.getItem(LS_UI) || "{}"); } catch (_) { this.data = {}; }
  },
  save() {
    try { localStorage.setItem(LS_UI, JSON.stringify(this.data)); } catch (_) {}
  },
  set(k, v) { this.data[k] = v; this.save(); },
  get(k, def) { return this.data[k] !== undefined ? this.data[k] : def; }
};

// -------------------------------------------------------------------
// 初始化
// -------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  UiState.load();
  loadCustomWorkflow();
  hiddenWorkflows = getHiddenWorkflows();
  applyUiState();
  setupResize();
  setupWorkflowPopover();
  setupKeyboard();
  setupUnloadGuard();

  loadTags();
  loadWorkflows();
  loadPrompts().then(() => {
    if (selectedId) {
      const exists = allPrompts.some(p => p.id === selectedId);
      if (exists) selectPrompt(selectedId, true, false, false, true);
      else selectedId = null;
    }
    updateRunBtn();
    updateSelectionBar();
  });
  loadHistory(true);
  loadActiveJobs();

  checkStatus();
  setInterval(checkStatus, 5000);
  setInterval(() => loadHistory(false), 30000);
});

function applyUiState() {
  document.getElementById("searchInput").value = UiState.get("search", "");
  document.getElementById("qualitySelect").value = UiState.get("quality", "4K");
  currentOrientation = UiState.get("orientation", "portrait");
  document.getElementById("orientBtn").textContent = currentOrientation === "portrait" ? "📱" : "🖥️";
  workflowSort = UiState.get("workflowSort", "mtime");
  document.getElementById("wfSortBtn").textContent = workflowSort === "mtime" ? "最近" : "名称";
  const sw = UiState.get("sidebarWidth", "");
  if (sw) document.getElementById("sidebar").style.width = sw;

  selectedIds = new Set(UiState.get("selectedIds", []));
  selectedId = UiState.get("selectedId", null) || null;
  lastClickedId = selectedId;
}


function setupResize() {
  const handle = document.getElementById("resizeHandle");
  const sidebar = document.getElementById("sidebar");
  let dragging = false;
  handle.addEventListener("mousedown", () => {
    dragging = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const w = Math.max(260, Math.min(620, e.clientX - 2));
    sidebar.style.width = w + "px";
  });
  document.addEventListener("mouseup", () => {
    if (dragging) {
      dragging = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      UiState.set("sidebarWidth", sidebar.style.width);
    }
  });
}

function setupWorkflowPopover() {
  const trigger = document.getElementById("wfTrigger");
  const popover = document.getElementById("wfPopover");
  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    _wfPopoverOpen = !popover.classList.contains("show");
    popover.classList.toggle("show");
  });
  document.addEventListener("click", (e) => {
    if (!popover.contains(e.target) && !trigger.contains(e.target)) {
      popover.classList.remove("show");
      _wfPopoverOpen = false;
    }
  });
}

function closeWorkflowPopover() {
  document.getElementById("wfPopover").classList.remove("show");
  _wfPopoverOpen = false;
}

function setupKeyboard() {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeLightbox();
      closeModal();
      closeVarModal();
      closeWorkflowPopover();
    }
    if (e.ctrlKey && e.key === "Enter" && selectedId && comfyStatus === "online") {
      e.preventDefault();
      runPrompt();
    }
    if (e.ctrlKey && e.key === "s") {
      if (document.getElementById("modalOverlay").classList.contains("active")) {
        e.preventDefault();
        savePrompt();
      }
    }
  });
}

function setupUnloadGuard() {
  window.addEventListener("beforeunload", (e) => {
    if (activeJobs.size) {
      e.preventDefault();
      e.returnValue = "有生成任务正在运行，刷新页面将丢失实时进度（但会尝试续跑）。";
    }
  });
}

// -------------------------------------------------------------------
// 网络
// -------------------------------------------------------------------

async function api(path, opts = {}) {
  const resp = await fetch(API + path, opts);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status} ${resp.statusText}${text ? ": " + text : ""}`);
  }
  return resp.json();
}

// -------------------------------------------------------------------
// 提示词
// -------------------------------------------------------------------

async function loadPrompts() {
  const search = document.getElementById("searchInput").value;
  const tag = document.getElementById("tagFilter").value;
  try {
    const data = await api(`/api/prompts?search=${encodeURIComponent(search)}&tag=${encodeURIComponent(tag)}`);
    allPrompts = data.prompts || [];
    renderList(allPrompts);
    document.getElementById("countBadge").textContent = allPrompts.length;
  } catch (e) {
    showToast("加载提示词失败: " + e.message, "error");
  }
}

function renderList(prompts) {
  const list = document.getElementById("promptList");
  list.innerHTML = "";
  if (!prompts.length) {
    list.innerHTML = '<div class="empty-tip">暂无匹配的提示词</div>';
    return;
  }
  prompts.forEach(p => {
    const div = document.createElement("div");
    div.className = "prompt-item" + (p.id === selectedId ? " active" : "");
    div.dataset.id = p.id;
    const tags = (p.tags || "").split(",").filter(Boolean);
    const tagsHtml = tags.map(t => `<span class="tag">${escHtml(t.trim())}</span>`).join("");
    const preview = escHtml(p.prompt_preview) + (p.prompt_preview.length >= 60 ? "..." : "");
    const nameLine = p.name ? `<div class="prompt-name">${escHtml(p.name)}</div>` : "";
    const bodyHtml = nameLine +
      `<div class="prompt-preview">${preview}</div>` +
      `<div class="prompt-meta">${p.steps ? `<span class="badge">${p.steps}步</span>` : ""}${p.sampler ? `<span style="color:#888">${escHtml(p.sampler)}</span>` : ""}${tagsHtml}</div>`;
    const checked = selectedIds.has(p.id) ? " checked" : "";
    div.innerHTML = `<div class="item-row"><input type="checkbox" class="item-check" data-id="${p.id}"${checked} onclick="event.stopPropagation();toggleItemSelect(${p.id},this.checked)"><div class="item-body">${bodyHtml}</div></div>`;
    div.onclick = (e) => {
      if (e.target.classList.contains("item-check")) return;
      selectPrompt(p.id, true, e.shiftKey, e.ctrlKey || e.metaKey);
    };
    list.appendChild(div);
  });
}

async function selectPrompt(id, fetchDetail = true, shiftKey = false, ctrlKey = false, isRestore = false) {
  if (shiftKey && lastClickedId !== null) {
    const ids = allPrompts.map(p => p.id);
    const start = ids.indexOf(lastClickedId);
    const end = ids.indexOf(id);
    if (start !== -1 && end !== -1) {
      const [a, b] = start < end ? [start, end] : [end, start];
      for (let i = a; i <= b; i++) selectedIds.add(ids[i]);
      UiState.set("selectedIds", Array.from(selectedIds));
    }
    lastClickedId = id;
    renderList(allPrompts);
    updateRunBtn();
    updateSelectionBar();
    return;
  }
  if (ctrlKey) {
    if (selectedIds.has(id)) selectedIds.delete(id); else selectedIds.add(id);
    lastClickedId = id;
    UiState.set("selectedIds", Array.from(selectedIds));
    renderList(allPrompts);
    updateRunBtn();
    updateSelectionBar();
    return;
  }
  // 初始化恢复状态时，只恢复展示项，不触发勾选/取消逻辑
  if (isRestore) {
    selectedId = id;
    lastClickedId = id;
    renderList(allPrompts);
    updateRunBtn();
    updateSelectionBar();
    if (!fetchDetail) return;
    try {
      const p = await api(`/api/prompts/${id}`);
      _currentPromptData = p;
      renderDetail(p);
    } catch (e) {
      showToast("加载详情失败: " + e.message, "error");
    }
    return;
  }
  // 新增逻辑：当已有勾选项时，点击提示词项的行为
  if (selectedIds.size > 0) {
    // 先切换到该项展示
    selectedId = id;
    UiState.set("selectedId", id);
    // 如果点击的是已勾选项，则取消勾选
    if (selectedIds.has(id)) {
      selectedIds.delete(id);
    } else {
      // 如果点击的是未勾选项，则勾选
      selectedIds.add(id);
    }
    lastClickedId = id;
    UiState.set("selectedIds", Array.from(selectedIds));
    renderList(allPrompts);
    updateRunBtn();
    updateSelectionBar();
    // 加载详情
    if (fetchDetail) {
      try {
        const p = await api(`/api/prompts/${id}`);
        _currentPromptData = p;
        renderDetail(p);
      } catch (e) {
        showToast("加载详情失败: " + e.message, "error");
      }
    }
    return;
  }
  // 原有逻辑：没有勾选项时，只切换展示
  selectedId = id;
  lastClickedId = id;
  selectedIds.clear();
  UiState.set("selectedIds", []);
  renderList(allPrompts);
  updateRunBtn();
  updateSelectionBar();
  UiState.set("selectedId", id);
  if (!fetchDetail) return;
  try {
    const p = await api(`/api/prompts/${id}`);
    _currentPromptData = p;
    renderDetail(p);
  } catch (e) {
    showToast("加载详情失败: " + e.message, "error");
  }
}

function renderDetail(p) {
  const panel = document.getElementById("detailPanel");
  const tags = (p.tags || "").split(",").filter(Boolean);
  const tagHtml = tags.map(t => `<span class="tag">${escHtml(t.trim())}</span>`).join("");
  panel.innerHTML =
    (p.name ? `<div class="detail-header"><div class="detail-name">${escHtml(p.name)}</div><div class="detail-actions">` +
      `<button class="btn btn-sm btn-warning" onclick="openVariationDialog()">🎲 变体</button>` +
      `<button class="btn btn-sm btn-warning" onclick="openEditModal(${p.id})">✏️ 编辑</button>` +
      `<button class="btn btn-sm btn-danger" onclick="deletePrompt(${p.id})">🗑️ 删除</button>` +
    `</div></div>` : "") +
    `<div class="section"><h3>📝 正面提示词 <button class="copy-btn" onclick="copyPromptText(this,0)">复制</button></h3><div class="content pos">${escHtml(p.prompt)}</div></div>` +
    `<div class="section"><h3>🚫 负面提示词 <button class="copy-btn" onclick="copyPromptText(this,1)">复制</button></h3><div class="content neg">${escHtml(p.negative_prompt || "(空)")}</div></div>` +
    `<div class="section"><h3>⚙️ 参数</h3><div class="params">` +
      `<div class="param-item"><div class="label">步数</div><div class="value">${p.steps || "-"}</div></div>` +
      `<div class="param-item"><div class="label">CFG</div><div class="value">${p.cfg_scale || "-"}</div></div>` +
      `<div class="param-item"><div class="label">采样器</div><div class="value">${escHtml(p.sampler || "-")}</div></div>` +
      `<div class="param-item"><div class="label">种子</div><div class="value">${p.seed ?? "-"}</div></div>` +
      `<div class="param-item"><div class="label">分辨率</div><div class="value">${p.width ? p.width + "×" + p.height : "-"}</div></div>` +
      `<div class="param-item"><div class="label">模型</div><div class="value" style="font-size:11px" title="${escHtml(p.model || "-")}">${escHtml(p.model || "-")}</div></div>` +
    `</div></div>` +
    (p.note ? `<div class="section"><h3>📌 备注</h3><div class="note-box">${escHtml(p.note)}</div></div>` : "") +
    `<div class="section"><h3>🏷️ 标签</h3><div>${tagHtml || '<span style="color:#666;font-size:13px">无标签</span>'}</div></div>` +
    `<div style="color:#555;font-size:11px;margin-top:16px">创建: ${p.created_at || "未知"}${p.updated_at && p.updated_at !== p.created_at ? " · 更新: " + p.updated_at : ""}</div>`;
}

async function loadTags() {
  try {
    const data = await api("/api/tags");
    const sel = document.getElementById("tagFilter");
    const cur = sel.value;
    sel.innerHTML = '<option value="">全部标签</option>';
    (data.tags || []).forEach(t => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });
    sel.value = cur || UiState.get("tag", "");
  } catch (_) {}
}

function onTagChange() {
  UiState.set("tag", document.getElementById("tagFilter").value);
  loadPrompts();
}

let searchTimer;
function debounceSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    UiState.set("search", document.getElementById("searchInput").value);
    loadPrompts();
  }, 300);
}

function copyPromptText(btn, type) {
  if (!_currentPromptData) return;
  const text = type === 0 ? (_currentPromptData.prompt || "") : (_currentPromptData.negative_prompt || "");
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "已复制";
    setTimeout(() => btn.textContent = "复制", 1500);
  }, () => showToast("复制失败", "error"));
}

// -------------------------------------------------------------------
// CRUD 弹窗
// -------------------------------------------------------------------

function openCreateModal() {
  document.getElementById("modalTitle").textContent = "新建提示词";
  document.getElementById("f_id").value = "";
  ["f_name","f_prompt","f_neg","f_steps","f_cfg","f_sampler","f_seed","f_model","f_tags","f_note"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("modalOverlay").classList.add("active");
}

async function openEditModal(id) {
  document.getElementById("modalTitle").textContent = "编辑提示词 #" + id;
  document.getElementById("f_id").value = id;
  try {
    const p = await api(`/api/prompts/${id}`);
    document.getElementById("f_name").value = p.name || "";
    document.getElementById("f_prompt").value = p.prompt || "";
    document.getElementById("f_neg").value = p.negative_prompt || "";
    document.getElementById("f_steps").value = p.steps || "";
    document.getElementById("f_cfg").value = p.cfg_scale || "";
    document.getElementById("f_sampler").value = p.sampler || "";
    document.getElementById("f_seed").value = p.seed || "";
    document.getElementById("f_model").value = p.model || "";
    document.getElementById("f_tags").value = p.tags || "";
    document.getElementById("f_note").value = p.note || "";
    document.getElementById("modalOverlay").classList.add("active");
  } catch (e) {
    showToast("加载失败: " + e.message, "error");
  }
}

function closeModal() { document.getElementById("modalOverlay").classList.remove("active"); }

async function savePrompt() {
  const data = {
    name: document.getElementById("f_name").value,
    prompt: document.getElementById("f_prompt").value,
    negative_prompt: document.getElementById("f_neg").value,
    steps: parseInt(document.getElementById("f_steps").value) || null,
    cfg_scale: parseFloat(document.getElementById("f_cfg").value) || null,
    sampler: document.getElementById("f_sampler").value,
    seed: parseInt(document.getElementById("f_seed").value) || null,
    model: document.getElementById("f_model").value,
    tags: document.getElementById("f_tags").value,
    note: document.getElementById("f_note").value,
  };
  const id = document.getElementById("f_id").value;
  const isEdit = !!id;
  try {
    const resp = isEdit
      ? await api(`/api/prompts/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
      : await api("/api/prompts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    if (resp.success) {
      showToast(isEdit ? "已更新" : "已创建", "success");
      closeModal();
      loadTags();
      loadPrompts();
      if (isEdit) selectPrompt(parseInt(id));
    } else {
      showToast(resp.error || "失败", "error");
    }
  } catch (e) {
    showToast("保存失败: " + e.message, "error");
  }
}

async function deletePrompt(id) {
  if (!confirm("确定删除提示词 #" + id + " 吗？")) return;
  try {
    const r = await api(`/api/prompts/${id}`, { method: "DELETE" });
    if (r.success) {
      showToast("已删除", "success");
      if (selectedId === id) {
        selectedId = null;
        UiState.set("selectedId", null);
        document.getElementById("detailPanel").innerHTML = '<div class="placeholder">← 从左侧选择一个提示词</div>';
      }
      loadTags();
      loadPrompts();
      updateRunBtn();
    } else {
      showToast(r.error || "删除失败", "error");
    }
  } catch (e) {
    showToast("删除失败: " + e.message, "error");
  }
}

// -------------------------------------------------------------------
// 工作流
// -------------------------------------------------------------------

async function loadWorkflows() {
  try {
    const data = await api(`/api/workflows?sort=${workflowSort}`);
    workflowList = data.workflows || [];
    if (_customWorkflow) {
      workflowList.unshift({ path: "__custom__" + _customWorkflow.name, name: "📁 " + _customWorkflow.name });
    }
    hiddenWorkflows = getHiddenWorkflows();
    renderWorkflows();
    const savedPath = UiState.get("workflowPath", "") || data.default || "";
    selectWorkflowByPath(savedPath);
  } catch (e) {
    console.error("loadWorkflows", e);
  }
}

function renderWorkflows() {
  const list = document.getElementById("wfPopoverList");
  list.innerHTML = "";
  const filtered = workflowList.filter(w => !hiddenWorkflows.includes(w.path));
  document.getElementById("wfRestoreBtn").style.display = hiddenWorkflows.length ? "" : "none";
  const selPath = document.getElementById("wfTrigger").dataset.path || "";
  if (!filtered.length) {
    list.innerHTML = '<div class="empty-tip" style="padding:20px">无可用工作流</div>';
    return;
  }
  filtered.forEach(w => {
    const div = document.createElement("div");
    div.className = "wf-item" + (w.path === selPath ? " active" : "");

    const nameSpan = document.createElement("span");
    nameSpan.className = "wf-item-name";
    nameSpan.title = w.path;
    nameSpan.textContent = w.name;

    const hideBtn = document.createElement("button");
    hideBtn.className = "wf-item-hide";
    hideBtn.title = "隐藏";
    hideBtn.textContent = "✕";
    hideBtn.onclick = (e) => { e.stopPropagation(); hideWorkflow(w.path); };

    div.appendChild(nameSpan);
    div.appendChild(hideBtn);
    div.onclick = () => { selectWorkflowByPath(w.path); closeWorkflowPopover(); };
    list.appendChild(div);
  });
}

function selectWorkflowByPath(path) {
  const w = workflowList.find(x => x.path === path);
  const trigger = document.getElementById("wfTrigger");
  const label = document.getElementById("wfLabel");
  if (w) {
    trigger.dataset.path = w.path;
    label.textContent = w.name;
    label.title = w.path;
  } else if (workflowList.length) {
    selectWorkflowByPath(workflowList[0].path);
    return;
  } else {
    trigger.dataset.path = "";
    label.textContent = "选择工作流";
  }
  renderWorkflows();
  UiState.set("workflowPath", trigger.dataset.path || "");
  updateRunBtn();
}

function getHiddenWorkflows() {
  try { return JSON.parse(localStorage.getItem(LS_HIDDEN_WF) || "[]"); } catch (_) { return []; }
}
function setHiddenWorkflows(list) {
  try { localStorage.setItem(LS_HIDDEN_WF, JSON.stringify(list)); } catch (_) {}
}
function hideWorkflow(path) {
  const list = getHiddenWorkflows();
  if (!list.includes(path)) list.push(path);
  setHiddenWorkflows(list);
  hiddenWorkflows = list;
  if (document.getElementById("wfTrigger").dataset.path === path && workflowList.length) {
    const next = workflowList.find(w => w.path !== path && !list.includes(w.path));
    if (next) selectWorkflowByPath(next.path);
  }
  renderWorkflows();
  showToast("已隐藏工作流", "info");
}
function restoreHiddenWorkflows() {
  setHiddenWorkflows([]);
  hiddenWorkflows = [];
  renderWorkflows();
  showToast("已恢复所有隐藏工作流", "success");
}
function toggleWorkflowSort() {
  workflowSort = workflowSort === "mtime" ? "name" : "mtime";
  document.getElementById("wfSortBtn").textContent = workflowSort === "mtime" ? "最近" : "名称";
  UiState.set("workflowSort", workflowSort);
  loadWorkflows();
}

function pickWorkflowFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const content = e.target.result;
    try {
      const wf = JSON.parse(content);
      const hasClip = wf.nodes && Array.isArray(wf.nodes)
        ? wf.nodes.some(n => n && n.type === "CLIPTextEncode")
        : Object.values(wf).some(v => v && v.class_type === "CLIPTextEncode");
      if (!hasClip) { showToast("所选文件没有 CLIPTextEncode 节点", "error"); return; }
    } catch (_) {
      showToast("无效的 JSON 文件", "error"); return;
    }
    _customWorkflow = { name: file.name, content };
    try { localStorage.setItem(LS_CUSTOM_WF, JSON.stringify(_customWorkflow)); } catch (_) {}
    showToast("已加载自定义工作流: " + file.name, "success");
    loadWorkflows();
    selectWorkflowByPath("__custom__" + file.name);
  };
  reader.readAsText(file);
  event.target.value = "";
}
function loadCustomWorkflow() {
  try {
    const raw = localStorage.getItem(LS_CUSTOM_WF);
    if (raw) _customWorkflow = JSON.parse(raw);
  } catch (_) {}
}

function currentWorkflowPath() {
  return document.getElementById("wfTrigger").dataset.path || "";
}
function workflowExtraBody() {
  const path = currentWorkflowPath();
  return path.startsWith("__custom__") ? { workflow_content: _customWorkflow?.content || "" } : {};
}

// -------------------------------------------------------------------
// 生成控制
// -------------------------------------------------------------------

async function runPrompt(id) {
  id = id || selectedId;
  if (!id) return;
  const workflowPath = currentWorkflowPath();
  if (!workflowPath) { showToast("请先选择工作流", "error"); return; }
  const btn = document.getElementById("runBtn");
  btn.disabled = true; btn.textContent = "发送中...";
  try {
    const body = Object.assign({
      id,
      workflow_path: workflowPath,
      orientation: currentOrientation,
      quality: getQuality()
    }, workflowExtraBody());
    const data = await api("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    showToast(`已推送 ${data.dimensions || ""} (job ${data.job_id})`, "success");
    trackJob(data.job_id);
  } catch (e) {
    showToast("跑图失败: " + e.message, "error");
  } finally {
    btn.textContent = "🚀 跑图";
    updateRunBtn();
  }
}

async function batchRun() {
  if (!selectedIds.size) return;
  const workflowPath = currentWorkflowPath();
  if (!workflowPath) { showToast("请先选择工作流", "error"); return; }
  const ids = Array.from(selectedIds);
  const items = ids.map(id => ({ prompt_id: id, seed: 0 }));
  try {
    const body = Object.assign({
      items,
      workflow_path: workflowPath,
      orientation: currentOrientation,
      quality: getQuality(),
      title: `批量跑图 (${items.length} 张)`
    }, workflowExtraBody());
    const data = await api("/api/batch_generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (data.errors && data.errors.length) {
      showToast(`${data.errors.length} 个任务提交失败`, "error");
    }
    trackJob(data.job_id);
  } catch (e) {
    showToast("批量提交失败: " + e.message, "error");
  }
}

function openVariationDialog() { document.getElementById("varModalOverlay").classList.add("active"); }
function closeVarModal() { document.getElementById("varModalOverlay").classList.remove("active"); }

async function startVariationRun() {
  if (!selectedId) return;
  const workflowPath = currentWorkflowPath();
  if (!workflowPath) { showToast("请先选择工作流", "error"); return; }
  const count = parseInt(document.getElementById("varCount").value) || 4;
  const startSeed = document.getElementById("varStartSeed").value;
  closeVarModal();
  const items = [];
  for (let i = 0; i < count; i++) {
    const seed = startSeed ? parseInt(startSeed) + i : Math.floor(Math.random() * 999999999999999);
    items.push({ prompt_id: selectedId, seed });
  }
  try {
    const body = Object.assign({
      items,
      workflow_path: workflowPath,
      orientation: currentOrientation,
      quality: getQuality(),
      title: `变体生成 (${items.length} 张)`
    }, workflowExtraBody());
    const data = await api("/api/batch_generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    trackJob(data.job_id);
  } catch (e) {
    showToast("变体生成失败: " + e.message, "error");
  }
}

function onMainAction() {
  if (selectedIds.size >= 2) return batchRun();
  if (selectedIds.size === 1) {
    const id = selectedIds.values().next().value;
    return runPrompt(id);
  }
  if (selectedId) return runPrompt(selectedId);
}

function toggleItemSelect(id, checked) {
  if (checked) selectedIds.add(id); else selectedIds.delete(id);
  lastClickedId = id;
  UiState.set("selectedIds", Array.from(selectedIds));
  updateRunBtn();
  updateSelectionBar();
}

function toggleSelectAll(checked) {
  if (checked) allPrompts.forEach(p => selectedIds.add(p.id));
  else selectedIds.clear();
  renderList(allPrompts);
  updateRunBtn();
  updateSelectionBar();
  UiState.set("selectedIds", Array.from(selectedIds));
}

function updateSelectionBar() {
  const bar = document.getElementById("selectionBar");
  const info = document.getElementById("selectionInfo");
  const allCheck = document.getElementById("selectAllCheck");
  const count = selectedIds.size;
  bar.classList.toggle("show", count > 0);
  info.textContent = `已选 ${count} 项`;
  allCheck.checked = count > 0 && allPrompts.length > 0 && allPrompts.every(p => selectedIds.has(p.id));
}

function clearSelection() {
  selectedIds.clear();
  renderList(allPrompts);
  updateRunBtn();
  updateSelectionBar();
  UiState.set("selectedIds", []);
}

function updateRunBtn() {
  const wf = currentWorkflowPath();
  const online = comfyStatus === "online" && wf;
  const btn = document.getElementById("runBtn");
  if (selectedIds.size >= 2) {
    btn.textContent = `🚀 批量跑图 (${selectedIds.size})`;
    btn.disabled = !online;
  } else if (selectedIds.size === 1) {
    btn.textContent = "🚀 跑图";
    btn.disabled = !online;
  } else if (selectedId) {
    btn.textContent = "🚀 跑图";
    btn.disabled = !online;
  } else {
    btn.textContent = "🚀 跑图";
    btn.disabled = true;
  }
}


function toggleOrientation() {
  currentOrientation = currentOrientation === "portrait" ? "landscape" : "portrait";
  document.getElementById("orientBtn").textContent = currentOrientation === "portrait" ? "📱" : "🖥️";
  document.getElementById("orientBtn").title = currentOrientation === "portrait" ? "竖屏" : "横屏";
  UiState.set("orientation", currentOrientation);
}
function getQuality() { return document.getElementById("qualitySelect").value; }
function onQualityChange() { UiState.set("quality", getQuality()); }

// -------------------------------------------------------------------
// 任务追踪 / 续跑
// -------------------------------------------------------------------

function trackJob(jobId) {
  activeJobId = jobId;
  activeJobs.add(jobId);
  if (jobPollTimer) clearInterval(jobPollTimer);
  jobPollTimer = setInterval(() => pollJob(jobId), 1000);
  pollJob(jobId);
}

async function loadActiveJobs() {
  try {
    const data = await api("/api/jobs?active=1");
    (data.jobs || []).forEach(job => {
      if (!activeJobs.has(job.id)) trackJob(job.id);
    });
  } catch (_) {}
}

async function pollJob(jobId) {
  try {
    const job = await api(`/api/jobs/${jobId}`);
    if (job.job_type === "batch") renderBatchJob(job);
    else renderSingleJob(job);
    if (["done", "error", "stopped"].includes(job.status)) {
      clearInterval(jobPollTimer);
      jobPollTimer = null;
      activeJobs.delete(jobId);
      loadHistory(false);
    }
  } catch (e) {
    console.error("pollJob", e);
  }
}

function renderSingleJob(job) {
  const area = document.getElementById("outputArea");
  area.classList.add("show");
  const item = job.items[0] || {};
  const title = document.getElementById("outputTitle");
  const fill = document.getElementById("progressFill");
  const info = document.getElementById("progressInfo");
  const body = document.getElementById("outputBody");
  if (item.status === "pending") {
    fill.style.width = "0%";
    info.textContent = "排队中...";
    title.textContent = "生成中";
  } else if (item.status === "running") {
    const prog = item.progress || {};
    const pct = prog.max > 0 ? Math.round(prog.progress / prog.max * 100) : -1;
    fill.style.width = pct >= 0 ? pct + "%" : "30%";
    info.textContent = pct >= 0 ? `${pct}% ${prog.current_node || ""}`.trim() : "模型加载中...";
    title.textContent = pct >= 0 ? `生成中 ${pct}%` : "生成中";
  } else if (item.status === "done") {
    fill.style.width = "100%";
    info.textContent = "完成";
    title.textContent = "生成结果";
    body.innerHTML = "";
    if (item.images && item.images.length) {
      const grid = item.images.length > 1;
      body.className = grid ? "output-body img-grid" : "output-body";
      item.images.forEach(img => body.appendChild(createImageWrap(img)));
    } else {
      body.className = "output-body";
      body.innerHTML = '<div class="empty-tip">完成但未找到输出图片</div>';
    }
  } else if (item.status === "error" || item.status === "cancelled") {
    fill.style.width = "0%";
    info.textContent = item.status === "cancelled" ? "已取消" : "失败";
    title.textContent = item.status === "cancelled" ? "已取消" : "生成失败";
    body.className = "output-body";
    body.innerHTML = `<div class="empty-tip" style="color:var(--danger)">${escHtml(item.error || "失败")}</div>`;
  }
}

function renderBatchJob(job) {
  const panel = document.getElementById("batchPanel");
  panel.classList.add("show");
  document.getElementById("batchPanelTitle").textContent = job.title || "批量任务";
  document.getElementById("batchPanelStop").style.display = ["pending", "running"].includes(job.status) ? "" : "none";
  const pct = job.total ? Math.round((job.done_count / job.total) * 100) : 0;
  document.getElementById("batchBarFill").style.width = pct + "%";
  document.getElementById("batchProgressText").textContent = `${job.done_count}/${job.total} (${job.error_count} 失败)`;
  const list = document.getElementById("batchItems");
  list.innerHTML = "";
  job.items.forEach((item, idx) => {
    const div = document.createElement("div");
    div.className = "batch-item";
    div.innerHTML = `<span class="batch-item-status ${item.status || "pending"}"></span>` +
      `<span class="batch-item-name">#${idx + 1} ${escHtml(item.prompt_preview || "提示词 " + item.prompt_id)}</span>` +
      `<span style="color:var(--muted)">${statusText(item.status)}</span>`;
    if (item.error) {
      div.innerHTML += `<span class="batch-item-error">${escHtml(item.error)}</span>`;
    }
    list.appendChild(div);
  });
  if (["done", "error", "stopped"].includes(job.status)) {
    showBatchResults(job);
  }
}

function showBatchResults(job) {
  const area = document.getElementById("outputArea");
  area.classList.add("show");
  document.getElementById("outputTitle").textContent = job.title || "批量结果";
  document.getElementById("progressFill").style.width = "100%";
  document.getElementById("progressInfo").textContent = `${job.done_count} 完成 / ${job.error_count} 失败`;
  const body = document.getElementById("outputBody");
  body.innerHTML = "";
  let images = [];
  job.items.forEach(item => { if (item.images) images = images.concat(item.images); });
  if (!images.length) {
    body.className = "output-body";
    body.innerHTML = '<div class="empty-tip">无输出图片</div>';
    return;
  }
  const grid = images.length > 1;
  body.className = grid ? "output-body img-grid" : "output-body";
  images.forEach(img => body.appendChild(createImageWrap(img)));
}

function createImageWrap(img) {
  const wrap = document.createElement("div");
  const el = document.createElement("img");
  el.src = imageUrl(img);
  el.alt = img.filename;
  el.onclick = () => openLightbox(imageUrl(img));
  wrap.appendChild(el);
  const cap = document.createElement("div");
  cap.className = "img-caption";
  cap.textContent = img.filename;
  wrap.appendChild(cap);
  return wrap;
}

function imageUrl(img) {
  return `/api/image?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || "")}&type=${encodeURIComponent(img.type || "output")}`;
}

function statusText(status) {
  const map = { pending: "排队", running: "生成中", done: "完成", error: "失败", cancelled: "已取消", unknown: "未知" };
  return map[status] || status;
}

async function batchStop() {
  if (!activeJobId) return;
  try {
    await api(`/api/jobs/${activeJobId}/cancel`, { method: "POST" });
    showToast("已停止", "info");
    pollJob(activeJobId);
  } catch (e) {
    showToast("停止失败: " + e.message, "error");
  }
}

function closeOutput() {
  document.getElementById("outputArea").classList.remove("show");
  document.getElementById("batchPanel").classList.remove("show");
  if (jobPollTimer) { clearInterval(jobPollTimer); jobPollTimer = null; }
  activeJobId = null;
}

// -------------------------------------------------------------------
// 历史
// -------------------------------------------------------------------

async function loadHistory(sync = false) {
  try {
    const data = sync ? await api("/api/history_sync") : await api("/api/history");
    renderHistory(data.items || []);
  } catch (e) {
    console.error("loadHistory", e);
  }
}

function renderHistory(items) {
  const strip = document.getElementById("historyStrip");
  const container = document.getElementById("historyItems");
  if (!items.length) {
    strip.classList.remove("show");
    return;
  }
  strip.classList.add("show");
  container.innerHTML = "";
  items.forEach(h => {
    const div = document.createElement("div");
    div.className = "hist-item";
    div.innerHTML =
      `<img src="${h.view_url}" loading="lazy" onclick="openLightbox('${escAttr(h.view_url)}')" alt="">` +
      `<div class="hist-tooltip">${escHtml(h.preview || h.filename || "")}</div>` +
      `<button class="hist-del" onclick="event.stopPropagation();deleteHistoryItem(${h.id})">×</button>`;
    container.appendChild(div);
  });
}

async function deleteHistoryItem(id) {
  try {
    await api(`/api/history/${id}`, { method: "DELETE" });
    loadHistory(false);
  } catch (e) {
    showToast("删除失败: " + e.message, "error");
  }
}

async function clearHistory() {
  if (!confirm("确定清空全部历史吗？")) return;
  try {
    await api("/api/history", { method: "DELETE" });
    loadHistory(false);
  } catch (e) {
    showToast("清空失败: " + e.message, "error");
  }
}

// -------------------------------------------------------------------
// ComfyUI 状态
// -------------------------------------------------------------------

async function checkStatus() {
  const dot = document.getElementById("statusDot");
  const text = document.getElementById("statusText");
  try {
    const s = await api("/api/status");
    comfyStatus = s.comfyui;
    if (s.comfyui === "online") {
      dot.className = "status-dot online";
      text.textContent = `ComfyUI 在线 · 运行 ${s.queue_running} / 队列 ${s.queue_pending}`;
    } else {
      dot.className = "status-dot offline";
      text.textContent = "ComfyUI 离线";
    }
  } catch (_) {
    dot.className = "status-dot offline";
    text.textContent = "ComfyUI 未响应";
    comfyStatus = "offline";
  }
  updateRunBtn();
  updateSelectionBar();
}

// -------------------------------------------------------------------
// 工具
// -------------------------------------------------------------------

function showToast(msg, type = "info") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "show " + (type || "info");
  clearTimeout(t._hide);
  t._hide = setTimeout(() => t.className = "", 3500);
}

function escHtml(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
function escAttr(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "&#10;").replace(/\r/g, "&#13;");
}

function openLightbox(src) {
  document.getElementById("lightboxImg").src = src;
  document.getElementById("lightbox").classList.add("show");
}
function closeLightbox() {
  document.getElementById("lightbox").classList.remove("show");
}
