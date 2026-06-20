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
let _historyItems = [];  // 历史数据缓存
let _gallerySelectedIds = new Set();  // 画廊勾选的图片 ID
let _compareMode = null;  // 'sync' | 'split' | 'single' | null
let _compareItems = [];  // 对比模式的图片列表
let _compareZoomSync = false;  // 对比模式缩放同步
let _lightboxItems = [];  // 单图模式的图片列表（用于导航）
let _lightboxIndex = 0;  // 单图模式当前索引
let _suppressRouteUpdate = false;  // 批量操作时抑制中间路由更新
let _promptPage = 1;      // 当前页码
let _promptPageSize = 50;  // 每页条数
let _promptTotal = 0;      // 总条数
let _gallerySort = "newest";       // 画廊排序
let _galleryFilter = "all";        // 画廊筛选：all / favorite
let _gallerySearch = "";           // 画廊搜索关键词

// -------------------------------------------------------------------
// 通用防抖锁：防止异步操作重复触发
// -------------------------------------------------------------------
const _locks = new Map();  // key -> Promise (进行中)

async function withLock(key, fn) {
  if (_locks.has(key)) {
    // 已有同名操作在进行中，等待它完成（不重复触发）
    return _locks.get(key);
  }
  const promise = (async () => {
    try {
      return await fn();
    } finally {
      _locks.delete(key);
    }
  })();
  _locks.set(key, promise);
  return promise;
}

// 对按钮元素包装：点击后禁用，异步完成后恢复
function disableBtnWhilePending(btn, fn) {
  return async (...args) => {
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    try {
      return await fn(...args);
    } finally {
      btn.disabled = false;
    }
  };
}

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

  // 初始化路由
  handleRoute(window.location.pathname);

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

  // 恢复灯箱状态（如刷新前正在查看图片）
  restoreLightboxState();
});

// -------------------------------------------------------------------
// 前端路由（纯手动 History API，无第三方依赖）
// -------------------------------------------------------------------

// 路由处理函数
function routeGallery() { switchTabByRoute('galleryTab'); }

function routePrompt(params) {
  // 抑制 switchTab 的 pushState，只由 selectPrompt 推最终 URL
  _suppressRouteUpdate = true;
  switchTabByRoute('promptTab');
  _suppressRouteUpdate = false;
  if (params && params.id) {
    const promptId = parseInt(params.id);
    if (promptId && allPrompts.some(p => p.id === promptId)) {
      selectPrompt(promptId, true, false, false, true);
    }
  }
}

function routeHistory(params) {
  // 灯箱是模态覆盖层，不需要切换 Tab
  if (params && params.id) {
    const historyId = parseInt(params.id);
    const checkAndOpen = () => {
      const item = _historyItems.find(it => it.id === historyId);
      if (item) {
        _lightboxItems = _historyItems;
        _lightboxIndex = _historyItems.findIndex(it => it.id === historyId);
        _compareMode = 'single';
        openUnifiedImageModal();
      } else if (_historyItems.length === 0) {
        setTimeout(checkAndOpen, 500);
      }
    };
    checkAndOpen();
  }
}

// 手动路由解析器
function handleRoute(path) {
  // 非灯箱路由时，确保灯箱已关闭
  if (_compareMode === 'single' && !path.startsWith('/history/')) {
    closeCompareModal();
  }
  
  if (path === '/' || path === '/gallery') {
    routeGallery();
  } else if (path.startsWith('/history/')) {
    const match = path.match(/\/history\/(\d+)/);
    if (match) routeHistory({ id: parseInt(match[1]) });
  } else if (path.startsWith('/prompt/')) {
    const match = path.match(/\/prompt\/(\d+)/);
    routePrompt(match ? { id: parseInt(match[1]) } : {});
  } else if (path === '/prompt') {
    routePrompt({});
  } else {
    routeGallery(); // 兜底
  }
}

// 监听浏览器后退/前进按钮
window.addEventListener('popstate', () => {
  _suppressRouteUpdate = true;
  handleRoute(window.location.pathname);
  _suppressRouteUpdate = false;
});

function switchTabByRoute(tabId) {
  const tabBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  if (tabBtn) {
    switchTab(tabId, tabBtn);
  }
}

function updateRoute() {
  let url = '/gallery';  // 默认
  
  // 根据当前状态生成 URL
  if (_compareMode === 'single') {
    // 灯箱打开时：/history/123
    const item = _lightboxItems[_lightboxIndex];
    if (item) {
      url = `/history/${item.id}`;
    }
  } else if (UiState.get('activeTab', 'galleryTab') === 'promptTab' && selectedId) {
    // 提示词详情：/prompt/123
    url = `/prompt/${selectedId}`;
  } else if (UiState.get('activeTab', 'galleryTab') === 'promptTab') {
    // 提示词列表：/prompt
    url = '/prompt';
  }
  // 否则：/gallery
  
  // 使用原生 History API 更新 URL
  if (window.location.pathname !== url && !_suppressRouteUpdate) {
    console.log(`[路由] pushState: ${url}  ←  ${window.location.pathname}`);
    history.pushState(null, '', url);
  }
}

function applyUiState() {
  document.getElementById("searchInput").value = UiState.get("search", "");
  document.getElementById("qualitySelect").value = UiState.get("quality", "4K");
  currentOrientation = UiState.get("orientation", "portrait");
  document.getElementById("orientBtn").textContent = currentOrientation === "portrait" ? "📱" : "🖥️";
  workflowSort = UiState.get("workflowSort", "mtime");
  document.getElementById("wfSortBtn").textContent = workflowSort === "mtime" ? "最近" : "名称";
  const sw = UiState.get("sidebarWidth", "");
  if (sw) document.getElementById("sidebar").style.width = sw;

  // 恢复排序选择
  const savedSort = UiState.get("sortFilter", "newest");
  const sortEl = document.getElementById("sortFilter");
  if (sortEl && [...sortEl.options].some(o => o.value === savedSort)) {
    sortEl.value = savedSort;
  }

  selectedIds = new Set(UiState.get("selectedIds", []));
  selectedId = UiState.get("selectedId", null) || null;
  lastClickedId = selectedId;

  const activeTab = UiState.get("activeTab", "promptTab");
  if (activeTab === "galleryTab") {
    const btn = document.querySelector('.tab-btn[data-tab="galleryTab"]');
    if (btn) switchTab("galleryTab", btn);
  }
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

async function loadPrompts(page) {
  return withLock("loadPrompts", async () => {
    if (page) _promptPage = page;
    const search = document.getElementById("searchInput").value;
    const tag = document.getElementById("tagFilter").value;
    const sort = document.getElementById("sortFilter").value;
    try {
      const params = new URLSearchParams({
        search, tag, sort,
        page: _promptPage,
        page_size: _promptPageSize,
      });
      const data = await api(`/api/prompts?${params.toString()}`);
      allPrompts = data.prompts || [];
      _promptTotal = data.total || 0;
      renderList(allPrompts);
      renderPagination();
      const totalEl = document.getElementById("countBadge");
      if (totalEl) totalEl.textContent = _promptTotal;
    } catch (e) {
      showToast("加载提示词失败: " + e.message, "error");
    }
  });
}

function onSortChange() {
  _promptPage = 1;
  loadPrompts();
  UiState.set("sortFilter", document.getElementById("sortFilter").value);
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
    div.innerHTML = `<div class="item-row"><label class="check-wrap" onclick="event.stopPropagation()"><input type="checkbox" class="item-check" data-id="${p.id}"${checked} onchange="toggleItemSelect(${p.id},this.checked)"></label><div class="item-body">${bodyHtml}</div></div>`;
    div.onclick = (e) => {
      if (e.target.closest(".check-wrap")) return;
      selectPrompt(p.id, true, e.shiftKey, e.ctrlKey || e.metaKey);
    };
    list.appendChild(div);
  });
}

function renderPagination() {
  const totalPages = Math.max(1, Math.ceil(_promptTotal / _promptPageSize));
  const el = document.getElementById("promptPagination");
  if (!el) return;
  if (totalPages <= 1) { el.innerHTML = ""; return; }

  let html = `<span class="page-info">第 ${_promptPage}/${totalPages} 页，共 ${_promptTotal} 条</span>`;
  html += `<button class="page-btn" ${_promptPage <= 1 ? "disabled" : ""} onclick="loadPrompts(1)">«</button>`;
  html += `<button class="page-btn" ${_promptPage <= 1 ? "disabled" : ""} onclick="loadPrompts(${_promptPage - 1})">‹</button>`;

  // 最多显示 5 个页码
  let start = Math.max(1, _promptPage - 2);
  let end = Math.min(totalPages, start + 4);
  start = Math.max(1, end - 4);
  for (let i = start; i <= end; i++) {
    html += `<button class="page-btn${i === _promptPage ? " active" : ""}" onclick="loadPrompts(${i})">${i}</button>`;
  }

  html += `<button class="page-btn" ${_promptPage >= totalPages ? "disabled" : ""} onclick="loadPrompts(${_promptPage + 1})">›</button>`;
  html += `<button class="page-btn" ${_promptPage >= totalPages ? "disabled" : ""} onclick="loadPrompts(${totalPages})">»</button>`;
  el.innerHTML = html;
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
      loadPromptHistory(id);
    } catch (e) {
      showToast("加载详情失败: " + e.message, "error");
    }
    return;
  }
  // 点提示词体只做单选查看，多选仅通过左上角复选框/Ctrl/Shift 触发
  // 不再清空已有多选集合，避免查看详情时丢失批量选择
  selectedId = id;
  lastClickedId = id;
  renderList(allPrompts);
  updateRunBtn();
  updateSelectionBar();
  UiState.set("selectedId", id);
  updateRoute();  // 更新路由
  if (!fetchDetail) return;
  try {
    const p = await api(`/api/prompts/${id}`);
    _currentPromptData = p;
    renderDetail(p);
    loadPromptHistory(id);
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
    `<div class="section prompt-history-section"><h3>🖼️ 生成历史</h3><div class="prompt-history-grid" id="promptHistoryGrid"><div class="empty-tip" style="font-size:12px">加载中...</div></div></div>` +
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
  _promptPage = 1;
  UiState.set("tag", document.getElementById("tagFilter").value);
  loadPrompts();
}

let searchTimer;
function debounceSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    _promptPage = 1;
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
  return withLock("savePrompt", async () => {
    const saveBtn = document.getElementById("modalSaveBtn");
    if (saveBtn) saveBtn.disabled = true;
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
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  });
}

async function deletePrompt(id) {
  if (!confirm("确定删除提示词 #" + id + " 吗？")) return;
  return withLock("deletePrompt", async () => {
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
  });
}

// -------------------------------------------------------------------
// 工作流
// -------------------------------------------------------------------

async function loadWorkflows() {
  return withLock("loadWorkflows", async () => {
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
  });
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
  return withLock("runPrompt", async () => {
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
  });
}

async function batchRun() {
  return withLock("batchRun", async () => {
    if (!selectedIds.size) return;
    const workflowPath = currentWorkflowPath();
    if (!workflowPath) { showToast("请先选择工作流", "error"); return; }
    const btn = document.getElementById("runBtn");
    if (btn) btn.disabled = true;
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
    } finally {
      if (btn) btn.disabled = false;
    }
  });
}

function openVariationDialog() { document.getElementById("varModalOverlay").classList.add("active"); }
function closeVarModal() { document.getElementById("varModalOverlay").classList.remove("active"); }

async function startVariationRun() {
  return withLock("startVariationRun", async () => {
    if (!selectedId) return;
    const workflowPath = currentWorkflowPath();
    if (!workflowPath) { showToast("请先选择工作流", "error"); return; }
    const confirmBtn = document.getElementById("varConfirmBtn");
    if (confirmBtn) confirmBtn.disabled = true;
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
    } finally {
      if (confirmBtn) confirmBtn.disabled = false;
    }
  });
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
  return withLock("batchStop", async () => {
    if (!activeJobId) return;
    try {
      await api(`/api/jobs/${activeJobId}/cancel`, { method: "POST" });
      showToast("已停止", "info");
      pollJob(activeJobId);
    } catch (e) {
      showToast("停止失败: " + e.message, "error");
    }
  });
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
    let url;
    if (sync) {
      url = "/api/history_sync";
    } else {
      url = "/api/history?";
      const params = [];
      if (_galleryFilter === "favorite") params.push("favorite=1");
      if (_gallerySort) params.push(`sort=${_gallerySort}`);
      if (_gallerySearch) params.push(`search=${encodeURIComponent(_gallerySearch)}`);
      url += params.join("&");
    }
    const data = await api(url);
    _historyItems = data.items || [];
    renderGallery(_historyItems);
    updateGalleryBadge();
  } catch (e) {
    console.error("loadHistory", e);
  }
}

function renderHistory(items) {
  // 底部历史条已移除，此函数保留但不再渲染
  // 历史数据现在通过 renderGallery 在画廊 Tab 中展示
}

function buildImageMeta(item) {
  const parts = [];
  if (item.width && item.height) parts.push(item.width + "×" + item.height);
  if (item.file_size) parts.push(formatFileSize(item.file_size));
  return parts.join(" · ");
}

function jumpToPrompt(promptId) {
  // 先关闭对比弹窗（否则会遮住跳转后的内容）
  closeCompareModal();
  
  // 批量操作，抑制中间的路由更新，避免历史栈被重复 push 污染
  _suppressRouteUpdate = true;
  const tabBtn = document.querySelector('.tab-btn[data-tab="promptTab"]');
  if (tabBtn) switchTab("promptTab", tabBtn);
  selectPrompt(promptId, true, false, false, false);
  _suppressRouteUpdate = false;
  
  // 统一推一次最终的 URL
  updateRoute();
}

let _promptHistoryItems = [];  // 当前提示词的生成历史（供灯箱使用）

async function loadPromptHistory(promptId) {
  const grid = document.getElementById("promptHistoryGrid");
  if (!grid) return;
  grid.innerHTML = '<div class="empty-tip" style="font-size:12px">加载中...</div>';
  try {
    const data = await api(`/api/prompts/${promptId}/history`);
    const items = data.items || [];
    _promptHistoryItems = items;
    if (!items.length) {
      grid.innerHTML = '<div class="empty-tip" style="font-size:12px">暂无生成历史</div>';
      return;
    }
    grid.innerHTML = "";
    items.forEach((item, idx) => {
      const img = document.createElement("img");
      img.className = "prompt-history-thumb";
      img.src = `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || "")}&type=${encodeURIComponent(item.img_type || "output")}&size=120`;
      img.alt = item.filename;
      img.title = item.filename + (item.created_at ? "\n" + item.created_at : "");
      img.onclick = () => openPromptHistoryLightbox(idx);
      grid.appendChild(img);
    });
  } catch (e) {
    grid.innerHTML = '<div class="empty-tip" style="font-size:12px;color:var(--danger)">加载失败</div>';
  }
}

function openPromptHistoryLightbox(clickedIdx) {
  if (!_promptHistoryItems.length) return;
  _lightboxItems = _promptHistoryItems.map(item => ({
    ...item,
    view_url: item.view_url || `/api/image?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || "")}&type=${encodeURIComponent(item.img_type || "output")}`
  }));
  _lightboxIndex = clickedIdx >= 0 ? clickedIdx : 0;
  _compareMode = 'single';
  openUnifiedImageModal();
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

async function deleteHistoryItem(id) {
  return withLock("deleteHistoryItem_" + id, async () => {
    try {
      await api(`/api/history/${id}`, { method: "DELETE" });
      loadHistory(false);
    } catch (e) {
      showToast("删除失败: " + e.message, "error");
    }
  });
}

async function clearHistory() {
  if (!confirm("确定清空全部历史吗？")) return;
  return withLock("clearHistory", async () => {
    try {
      await api("/api/history", { method: "DELETE" });
      loadHistory(false);
    } catch (e) {
      showToast("清空失败: " + e.message, "error");
    }
  });
}

// -------------------------------------------------------------------
// 画廊：收藏 / 删除 / 下载 / 重新生成
// -------------------------------------------------------------------

async function toggleFavorite(id, btn) {
  try {
    const r = await api(`/api/history/${id}/favorite`, { method: "POST" });
    if (r.success) {
      // 同步更新 _historyItems
      const item = _historyItems.find(it => it.id === id);
      if (item) item.favorite = r.favorite;
      // 同步更新 _lightboxItems
      const lbItem = _lightboxItems.find(it => it && it.id === id);
      if (lbItem) lbItem.favorite = r.favorite;
      // 更新传入的按钮（卡片或灯箱）
      if (btn) {
        btn.classList.toggle('active', r.favorite);
        btn.textContent = r.favorite ? '★' : '☆';
      }
      // 若灯箱打开且当前图片匹配，同步更新灯箱头部按钮
      if (_compareMode === 'single') {
        const favBtn = document.getElementById('lightboxFavBtn');
        if (favBtn && _lightboxItems[_lightboxIndex] && _lightboxItems[_lightboxIndex].id === id) {
          favBtn.classList.toggle('active', r.favorite);
          favBtn.textContent = r.favorite ? '★' : '☆';
        }
      }
      showToast(r.favorite ? '已收藏' : '已取消收藏', 'info');
    }
  } catch (e) {
    showToast("操作失败: " + e.message, "error");
  }
}

// 灯箱：切换收藏（复用 toggleFavorite，仅负责触发）
function toggleFavoriteFromLightbox() {
  const item = _lightboxItems[_lightboxIndex];
  if (!item) return;
  toggleFavorite(item.id, document.getElementById('lightboxFavBtn'));
}

async function batchDeleteHistory() {
  const ids = Array.from(_gallerySelectedIds);
  if (!ids.length) return;
  if (!confirm(`确定删除选中的 ${ids.length} 张图片吗？`)) return;
  try {
    const r = await api('/api/history/batch_delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    showToast(`已删除 ${r.deleted} 项`, 'success');
    _gallerySelectedIds.clear();
    loadHistory(false);
  } catch (e) {
    showToast('批量删除失败: ' + e.message, 'error');
  }
}

async function downloadHistoryItem(id) {
  const a = document.createElement('a');
  a.href = `/api/history/${id}/download`;
  a.target = '_blank';
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function batchDownloadHistory() {
  const ids = Array.from(_gallerySelectedIds);
  if (!ids.length) return;
  showToast(`正在下载 ${ids.length} 张图片...`, 'info');
  for (const id of ids) {
    await downloadHistoryItem(id);
    await new Promise(r => setTimeout(r, 500));
  }
  showToast('下载完成', 'success');
}

async function regenerateFromHistory(promptId) {
  if (!promptId) {
    showToast('该图片没有关联的提示词，无法重新生成', 'error');
    return;
  }
  const workflowPath = currentWorkflowPath();
  if (!workflowPath) {
    showToast('请先选择工作流', 'error');
    return;
  }
  if (comfyStatus !== 'online') {
    showToast('ComfyUI 离线，无法生成', 'error');
    return;
  }
  try {
    const body = {
      id: promptId,
      workflow_path: workflowPath,
      orientation: currentOrientation,
      quality: getQuality(),
    };
    const data = await api('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    showToast(`已重新生成 (job ${data.job_id})`, 'success');
    if (data.job_id) trackJob(data.job_id);
  } catch (e) {
    showToast('重新生成失败: ' + e.message, 'error');
  }
}

// -------------------------------------------------------------------
// 画廊：搜索 / 排序 / 筛选
// -------------------------------------------------------------------

let _gallerySearchTimer = null;

function onGallerySearch() {
  clearTimeout(_gallerySearchTimer);
  _gallerySearchTimer = setTimeout(() => {
    _gallerySearch = document.getElementById('gallerySearch').value;
    loadHistory(false);
  }, 300);
}

function onGallerySortChange() {
  _gallerySort = document.getElementById('gallerySort').value;
  loadHistory(false);
}

function onGalleryFilterChange() {
  _galleryFilter = document.getElementById('galleryFilter').value;
  loadHistory(false);
}

function updateGalleryActionButtons() {
  const count = _gallerySelectedIds.size;
  const batchDel = document.getElementById('galleryBatchDel');
  const batchDl = document.getElementById('galleryBatchDl');
  if (batchDel) batchDel.style.display = count >= 1 ? 'inline-flex' : 'none';
  if (batchDl) batchDl.style.display = count >= 1 ? 'inline-flex' : 'none';
  updateCompareButton();
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
// Tab 切换
// -------------------------------------------------------------------

function switchTab(tabId, btn) {
  // 隐藏所有 Tab 内容
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  // 取消所有按钮激活状态
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  
  // 显示选中的 Tab
  document.getElementById(tabId).classList.add('active');
  btn.classList.add('active');

  UiState.set("activeTab", tabId);

  // 根据页签控制 header-right 元素
  const isGallery = (tabId === 'galleryTab');
  ['qualitySelect', 'orientBtn', 'runBtn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = isGallery ? 'none' : '';
  });

  // 切换到画廊时刷新数据
  if (tabId === 'galleryTab') {
    loadHistory(false);
  }

  // 强制刷新对比按钮状态（非画廊 tab 强制隐藏）
  if (tabId !== 'galleryTab') {
    const btn = document.getElementById('compareBtn');
    if (btn) btn.style.display = 'none';
  }

  // 更新路由
  updateRoute();
}

// -------------------------------------------------------------------
// 历史画廊
// -------------------------------------------------------------------

function renderGallery(items) {
  const grid = document.getElementById('galleryGrid');
  const countEl = document.getElementById('galleryCount');

  if (!items || !items.length) {
    grid.innerHTML = '<div class="empty-tip">暂无历史图片</div>';
    countEl.textContent = '0';
    return;
  }

  countEl.textContent = items.length;
  grid.innerHTML = '';

  items.forEach((item, idx) => {
    const div = document.createElement('div');
    div.className = 'gallery-item';
    div.dataset.id = item.id;
    div.dataset.index = idx;

    // 缩略图 URL
    const thumbUrl = `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}&size=300`;

    // 元数据
    const meta = buildImageMeta(item);

    const favClass = item.favorite ? 'active' : '';
    const favChar = item.favorite ? '★' : '☆';
    const hasPrompt = item.prompt_id != null;

    div.innerHTML = `
      <img src="${thumbUrl}" alt=""
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
      <div class="gallery-item-placeholder" style="display:none;width:100%;aspect-ratio:1;background:var(--panel-2);align-items:center;justify-content:center;color:var(--muted);font-size:32px">🖼️</div>
      <button class="gallery-item-fav ${favClass}" onclick="event.stopPropagation();toggleFavorite(${item.id},this)" title="收藏">${favChar}</button>
      ${item.prompt_name ? `<div class="gallery-item-prompt" onclick="event.stopPropagation();jumpToPrompt(${item.prompt_id})">📝 ${escHtml(item.prompt_name)}</div>` : ""}
      <div class="gallery-item-check" data-id="${item.id}"></div>
      <div class="gallery-item-actions">
        ${hasPrompt ? `<button class="gallery-item-regen" onclick="event.stopPropagation();regenerateFromHistory(${item.prompt_id})" title="重新生成">🔄</button>` : ""}
        <button class="gallery-item-dl" onclick="event.stopPropagation();downloadHistoryItem(${item.id})" title="下载">⬇️</button>
      </div>
      <div class="gallery-item-meta">${meta}</div>
    `;

    // 点击勾选框
    const checkEl = div.querySelector('.gallery-item-check');
    checkEl.onclick = (e) => {
      e.stopPropagation();
      toggleGalleryItem(item.id, checkEl);
    };

    // 点击图片打开灯箱
    div.onclick = () => {
      if (_gallerySelectedIds.size > 0) {
        toggleGalleryItem(item.id, checkEl);
      } else {
        openLightbox(item.view_url, meta, null, idx);
      }
    };

    // 恢复勾选状态
    if (_gallerySelectedIds.has(item.id)) {
      checkEl.classList.add('checked');
    }

    grid.appendChild(div);
  });

  updateGalleryActionButtons();
  updateCompareButton();
}

function toggleGalleryItem(id, checkEl) {
  if (_gallerySelectedIds.has(id)) {
    _gallerySelectedIds.delete(id);
    checkEl.classList.remove('checked');
  } else {
    if (_gallerySelectedIds.size >= 4) {
      showToast('最多只能选择 4 张图片进行对比', 'error');
      return;
    }
    _gallerySelectedIds.add(id);
    checkEl.classList.add('checked');
  }
  updateCompareButton();
  updateGalleryActionButtons();
}

function updateCompareButton() {
  const btn = document.getElementById('compareBtn');
  const countEl = document.getElementById('compareCount');
  const count = _gallerySelectedIds.size;
  
  if (count >= 2) {
    btn.style.display = 'inline-flex';
    countEl.textContent = count;
  } else {
    btn.style.display = 'none';
  }
}

function enterCompareMode() {
  if (_gallerySelectedIds.size < 2) {
    showToast('至少选择 2 张图片才能对比', 'error');
    return;
  }
  
  // 收集选中的图片数据
  _compareItems = _historyItems.filter(item => _gallerySelectedIds.has(item.id));
  _compareMode = 'sync';
  
  // 不再使用旧工具栏，改为直接打开自定义弹窗
  document.getElementById('compareToolbar').classList.remove('show');
  
  // 打开统一图片查看弹窗（多图模式）
  openUnifiedImageModal();
}

function exitCompareMode() {
  _compareMode = null;
  _compareItems = [];
  document.getElementById('compareToolbar').classList.remove('show');
  
  // 关闭灯箱
  if (pswpLightbox) {
    pswpLightbox.destroy();
    pswpLightbox = null;
  }
}

function setCompareMode(mode) {
  _compareMode = mode;
  // 更新弹窗内的按钮状态
  const btn1 = document.getElementById('compareSyncBtn2');
  const btn2 = document.getElementById('compareSplitBtn2');
  if (btn1) btn1.classList.toggle('active', mode === 'sync');
  if (btn2) btn2.classList.toggle('active', mode === 'split');
  // 同时更新旧工具栏按钮（若可见）
  const oBtn1 = document.getElementById('compareSyncBtn');
  const oBtn2 = document.getElementById('compareSplitBtn');
  if (oBtn1) oBtn1.classList.toggle('active', mode === 'sync');
  if (oBtn2) oBtn2.classList.toggle('active', mode === 'split');

  // sync/split 只是交互行为差异，布局相同，不重建 DOM（保留缩放/位置状态）
}

function openCompareLightbox() {
  if (!_compareItems.length) return;

  // 使用自定义对比弹窗，而非 PhotoSwipe（PhotoSwipe 只支持单图浏览）
  openCompareModal();
}

/* ========== 统一图片查看弹窗（单图+多图共用） ========== */
function openUnifiedImageModal() {
  let overlay = document.getElementById('compareModal');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'compareModal';
    overlay.className = 'compare-modal-overlay';
    overlay.tabIndex = -1;
    overlay.innerHTML = `
      <div class="compare-modal-header">
        <div class="compare-modal-title" id="imageModalTitle" style="display:flex;align-items:center;gap:8px">
          <span id="imageModalTitleText">图片查看（<span id="compareModalCount">0</span> 张）</span>
          <span id="compareZoomDisplay" class="compare-zoom-display">100%</span>
          <span id="lightboxHeaderPrompt" class="lightbox-header-prompt"></span>
        </div>
        <div class="compare-modal-actions" id="compareModalActions">
          <!-- 对比模式按钮 -->
          <button id="compareSyncBtn2" class="active" onclick="setCompareMode('sync')">同步</button>
          <button id="compareSplitBtn2" onclick="setCompareMode('split')">分屏</button>
          <!-- 单图模式按钮 -->
          <button id="lightboxFavBtn" class="lightbox-action-btn" style="display:none" onclick="toggleFavoriteFromLightbox()">☆</button>
          <button id="lightboxDlBtn" class="lightbox-action-btn" style="display:none" onclick="downloadFromLightbox()">⬇️</button>
          <button id="lightboxRegenBtn" class="lightbox-action-btn" style="display:none" onclick="regenFromLightbox()">🔄</button>
          <!-- 共用 -->
          <button id="compareResetBtn" onclick="resetImageZoom()">重置</button>
          <button onclick="closeCompareModal(true)">✕ 退出</button>
        </div>
      </div>
      <div class="compare-modal-body" id="compareModalBody"></div>
    `;
    document.body.appendChild(overlay);

    // ESC 关闭
    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeCompareModal(true);
    });
  }

  // 根据模式显示/隐藏按钮
  const syncBtn = document.getElementById('compareSyncBtn2');
  const splitBtn = document.getElementById('compareSplitBtn2');
  const resetBtn = document.getElementById('compareResetBtn');
  const titleText = document.getElementById('imageModalTitleText');
  const zoomDisplay = document.getElementById('compareZoomDisplay');
  const favBtn = document.getElementById('lightboxFavBtn');
  const dlBtn = document.getElementById('lightboxDlBtn');
  const regenBtn = document.getElementById('lightboxRegenBtn');

  if (_compareMode === 'single') {
    // 单图模式：隐藏同步/分屏，显示灯箱操作按钮
    syncBtn.style.display = 'none';
    splitBtn.style.display = 'none';
    favBtn.style.display = '';
    dlBtn.style.display = '';
    regenBtn.style.display = '';
    resetBtn.style.display = '';
    titleText.textContent = `图片查看（${_lightboxIndex + 1} / ${_lightboxItems.length}）`;
  } else {
    // 多图模式：显示同步/分屏，隐藏灯箱操作按钮
    syncBtn.style.display = '';
    splitBtn.style.display = '';
    favBtn.style.display = 'none';
    dlBtn.style.display = 'none';
    regenBtn.style.display = 'none';
    resetBtn.style.display = '';
    titleText.innerHTML = `对比模式（<span id="compareModalCount">0</span> 张）`;
  }

  // 重置缩放显示
  if (zoomDisplay) zoomDisplay.textContent = '100%';

  overlay.classList.add('active');
  overlay.focus();
  document.body.style.overflow = 'hidden';

  // 保存状态到 localStorage
  saveLightboxState();

  // 渲染图片（renderUnifiedImageGrid 内部会调用 _bindCompareInteractions）
  renderUnifiedImageGrid();
}

function closeCompareModal(navigateBack = false) {
  const overlay = document.getElementById('compareModal');
  if (overlay) overlay.classList.remove('active');
  document.body.style.overflow = '';

  // 销毁所有图片状态
  _destroyAllViewers();

  // 根据模式清理状态
  if (_compareMode === 'single') {
    _lightboxItems = [];
    _lightboxIndex = 0;
  } else {
    _compareItems = [];
  }

  _compareMode = null;
  const toolbar = document.getElementById('compareToolbar');
  if (toolbar) toolbar.classList.remove('show');

  // 清除持久化状态
  clearLightboxState();

  // 关闭灯箱后恢复路由
  // navigateBack=true（用户点击 X/ESC）：回退到上一页
  // navigateBack=false（由 jumpToPrompt 调用）：不操作 URL，由调用方负责
  if (navigateBack) {
    history.back();
  }
}

/* ========== 对比模式：手搓轻量缩放拖拽（动画驱动版） ========== */
// 每个图片的状态：{scale, x, y, targetScale, targetX, targetY, anchorX, anchorY, rafId}
let _imageStates = [];

function _initImageState(img, wrap) {
  const nW = img.naturalWidth, nH = img.naturalHeight;
  const cW = wrap.clientWidth, cH = wrap.clientHeight;
  if (!nW || !nH || !cW || !cH) return null;

  const fitScale = Math.min(cW / nW, cH / nH);
  const x = (cW - nW * fitScale) / 2;
  const y = (cH - nH * fitScale) / 2;

  return {
    scale: fitScale, x, y,
    targetScale: fitScale, targetX: x, targetY: y,
    anchorX: 0, anchorY: 0, rafId: null
  };
}

function _applyTransform(img, state) {
  img.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
  img.style.transformOrigin = '0 0';
}

// 弹性边界：统一用 min(图片, 容器) 的 15% 作为必须可见量，20px 保底
// 大图放大后几乎可拖到边缘（hold cW*15%），小图缩小后也不至于完全丢失（hold imgW*15%）
function _constrain(state, wrap, img) {
  const imgW = img.naturalWidth * state.scale;
  const imgH = img.naturalHeight * state.scale;
  const cW = wrap.clientWidth;
  const cH = wrap.clientHeight;

  const RATIO = 0.15;
  const keepW = Math.max(Math.min(imgW, cW) * RATIO, 20);
  const keepH = Math.max(Math.min(imgH, cH) * RATIO, 20);

  state.x = Math.max(keepW - imgW, Math.min(cW - keepW, state.x));
  state.y = Math.max(keepH - imgH, Math.min(cH - keepH, state.y));
}

function _updateZoomDisplay() {
  const zd = document.getElementById('compareZoomDisplay');
  if (!zd) return;
  for (let i = 0; i < _imageStates.length; i++) {
    if (_imageStates[i]) {
      zd.textContent = Math.round(_imageStates[i].scale * 100) + '%';
      return;
    }
  }
  zd.textContent = '100%';
}

function _cancelAllAnimations() {
  _imageStates.forEach(s => {
    if (s && s.rafId) { cancelAnimationFrame(s.rafId); s.rafId = null; }
  });
}

function _destroyAllViewers() {
  _cancelAllAnimations();
  _imageStates = [];
  document.querySelectorAll('#compareModalBody .compare-img').forEach(img => {
    img.style.transform = '';
    img.style.transformOrigin = '';
  });
}

// —— 动画循环：每帧平滑逼近 targetScale/targetX/targetY ——
function _startZoomAnim(idx, img, wrap) {
  const state = _imageStates[idx];
  if (!state) return;

  // 如果已有动画在跑，不重复启动
  if (state.rafId) return;

  const LERP = 0.35;  // 每帧趋近系数（值越大越跟手，越小越平滑）

  function tick() {
    state.rafId = null;

    // 趋近目标值
    const ds = state.targetScale - state.scale;
    const dx = state.targetX - state.x;
    const dy = state.targetY - state.y;

    if (Math.abs(ds) < 0.0001 && Math.abs(dx) < 0.1 && Math.abs(dy) < 0.1) {
      // 已到达目标
      state.scale = state.targetScale;
      state.x = state.targetX;
      state.y = state.targetY;
      _constrain(state, wrap, img);
      _applyTransform(img, state);
      _updateZoomDisplay();
      return;
    }

    // 逐帧插值
    state.scale += ds * LERP;
    state.x += dx * LERP;
    state.y += dy * LERP;
    _constrain(state, wrap, img);
    _applyTransform(img, state);

    // 继续动画
    state.rafId = requestAnimationFrame(tick);
  }

  state.rafId = requestAnimationFrame(tick);
}

// —— 计算以鼠标为中心的目标位置 ——
function _calcZoomTarget(state, wrap, img, targetScale, mouseX, mouseY) {
  // 鼠标在图片坐标系中的位置（缩放前，单位：原始图片像素）
  const imgX = (mouseX - state.x) / state.scale;
  const imgY = (mouseY - state.y) / state.scale;

  // 缩放后，保持该点在鼠标位置不变
  const targetX = mouseX - imgX * targetScale;
  const targetY = mouseY - imgY * targetScale;

  // 先用未约束的值做边界约束预览
  const preview = { x: targetX, y: targetY, scale: targetScale };
  _constrain(preview, wrap, img);

  return { targetX: preview.x, targetY: preview.y };
}

function _bindCompareInteractions(body) {
  _destroyAllViewers();

  const wraps = body.querySelectorAll('.compare-item-wrap');
  wraps.forEach((wrap, idx) => {
    const img = wrap.querySelector('.compare-img');
    if (!img) return;

    // —— 初始化 ——
    const initState = () => {
      const s = _initImageState(img, wrap);
      if (!s) return;
      while (_imageStates.length <= idx) _imageStates.push(null);
      _imageStates[idx] = s;
      _applyTransform(img, s);
      _updateZoomDisplay();
    };
    if (img.complete && img.naturalWidth > 0) {
      initState();
    } else {
      img.addEventListener('load', initState);
    }

    // —— 滚轮缩放：只设置目标值，触发平滑动画 ——
    wrap.addEventListener('wheel', (e) => {
      e.preventDefault();
      const state = _imageStates[idx];
      if (!state) return;

      // 用当前 scale 计算 targetScale（不是 targetScale，因为动画进行中）
      const curScale = state.scale;
      const zoomDelta = -e.deltaY * 0.002;       // 对数增量
      const targetScale = Math.max(0.05, Math.min(20, curScale * Math.exp(zoomDelta)));

      // 以鼠标为中心计算目标位置
      const rect = wrap.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const { targetX, targetY } = _calcZoomTarget(state, wrap, img, targetScale, mx, my);

      state.targetScale = targetScale;
      state.targetX = targetX;
      state.targetY = targetY;
      state.anchorX = mx;
      state.anchorY = my;

      _startZoomAnim(idx, img, wrap);

      // 同步模式
      if (_compareMode === 'sync') {
        _syncTargetZoom(idx, targetScale, wrap, img, mx, my);
      }
    }, { passive: false });

    // —— 拖拽 ——
    let isDragging = false;
    let dragStartX, dragStartY, dragStateX, dragStateY;
    let dragOtherSnap = null;

    // 拖拽逻辑（提取为命名函数以便绑定到 document）
    const onDragMove = (e) => {
      if (!isDragging) return;
      const state = _imageStates[idx];
      if (!state) return;
      const deltaX = (e.clientX - dragStartX);
      const deltaY = (e.clientY - dragStartY);
      state.x = dragStateX + deltaX;
      state.y = dragStateY + deltaY;
      state.targetX = state.x;
      state.targetY = state.y;
      _constrain(state, wrap, img);
      _applyTransform(img, state);

      // 同步模式：其他图片 = 初始位置 + 累计偏移（SET 不是 +=）
      if (_compareMode === 'sync' && dragOtherSnap) {
        _imageStates.forEach((otherState, otherIdx) => {
          if (otherIdx === idx || !otherState || !dragOtherSnap[otherIdx]) return;
          const otherImg = document.querySelectorAll('#compareModalBody .compare-img')[otherIdx];
          const otherWrap = otherImg ? otherImg.closest('.compare-item-wrap') : null;
          if (!otherImg || !otherWrap) return;
          otherState.x = dragOtherSnap[otherIdx].x + deltaX;
          otherState.y = dragOtherSnap[otherIdx].y + deltaY;
          otherState.targetX = otherState.x;
          otherState.targetY = otherState.y;
          _constrain(otherState, otherWrap, otherImg);
          _applyTransform(otherImg, otherState);
        });
      }
    };

    const onDragEnd = () => {
      if (!isDragging) return;
      isDragging = false;
      wrap.style.cursor = 'grab';
      document.removeEventListener('mousemove', onDragMove);
      document.removeEventListener('mouseup', onDragEnd);
    };

    wrap.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      const state = _imageStates[idx];
      if (!state) return;
      isDragging = true;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      dragStateX = state.x;
      dragStateY = state.y;
      _cancelAllAnimations();
      dragOtherSnap = {};
      if (_compareMode === 'sync') {
        _imageStates.forEach((os, oi) => {
          if (oi !== idx && os) dragOtherSnap[oi] = { x: os.x, y: os.y };
        });
      }
      wrap.style.cursor = 'grabbing';
      document.addEventListener('mousemove', onDragMove);
      document.addEventListener('mouseup', onDragEnd);
      e.preventDefault();
    });

    wrap.style.cursor = 'grab';
  });
}

function _syncTargetZoom(sourceIdx, targetScale, sourceWrap, sourceImg, mx, my) {
  _imageStates.forEach((state, idx) => {
    if (idx === sourceIdx || !state) return;

    const img = document.querySelectorAll('#compareModalBody .compare-img')[idx];
    const wrap = img ? img.closest('.compare-item-wrap') : null;
    if (!img || !wrap) return;

    state.targetScale = targetScale;
    state.anchorX = mx;
    state.anchorY = my;

    // 其他图片也以各自容器中的同样比例为锚点
    const wrapRect = wrap.getBoundingClientRect();
    const sourceRect = sourceWrap.getBoundingClientRect();
    const relX = sourceRect.width > 0 ? (mx / sourceRect.width) : 0.5;
    const relY = sourceRect.height > 0 ? (my / sourceRect.height) : 0.5;
    const localX = wrapRect.width * relX;
    const localY = wrapRect.height * relY;

    const { targetX, targetY } = _calcZoomTarget(state, wrap, img, targetScale, localX, localY);
    state.targetX = targetX;
    state.targetY = targetY;

    _startZoomAnim(idx, img, wrap);
  });
}

function renderUnifiedImageGrid() {
  const body = document.getElementById('compareModalBody');
  const countEl = document.getElementById('compareModalCount');
  if (!body) return;

  // 销毁旧状态
  _destroyAllViewers();
  body.innerHTML = '';

  let items = [];
  if (_compareMode === 'single') {
    items = [_lightboxItems[_lightboxIndex]];
    body.className = 'compare-modal-body compare-grid-1';
  } else {
    items = _compareItems;
    if (countEl) countEl.textContent = items.length;
    body.className = 'compare-modal-body compare-grid-' + items.length;
  }

  items.forEach((item, idx) => {
    const wrap = document.createElement('div');
    wrap.className = 'compare-item-wrap';
    wrap.dataset.idx = idx;

    const img = document.createElement('img');
    img.className = 'compare-img';
    img.src = item.view_url;
    img.alt = item.filename;
    img.draggable = false;
    wrap.appendChild(img);

    // 构建 label
    const label = document.createElement('div');
    label.className = 'compare-item-label';
    let labelHTML = '';

    if (_compareMode === 'single') {
      // === 单图模式：详细说明（label: value 格式） ===
      const rows = [];
      // 首行：时间
      if (item.created_at) rows.push(`<div class="label-param-row"><span class="label-param-key">时间：</span><span class="label-param-val">${item.created_at}</span></div>`);
      // 出图参数
      const p = item.prompt_params || {};
      if (p.steps) rows.push(`<div class="label-param-row"><span class="label-param-key">步数：</span><span class="label-param-val">${p.steps}</span></div>`);
      if (p.cfg_scale) rows.push(`<div class="label-param-row"><span class="label-param-key">CFG：</span><span class="label-param-val">${p.cfg_scale}</span></div>`);
      if (p.sampler) rows.push(`<div class="label-param-row"><span class="label-param-key">采样器：</span><span class="label-param-val">${escHtml(p.sampler)}</span></div>`);
      if (p.seed != null) rows.push(`<div class="label-param-row"><span class="label-param-key">种子：</span><span class="label-param-val">${p.seed}</span></div>`);
      if (p.model) rows.push(`<div class="label-param-row"><span class="label-param-key">模型：</span><span class="label-param-val">${escHtml(p.model)}</span></div>`);
      if (item.width && item.height) rows.push(`<div class="label-param-row"><span class="label-param-key">分辨率：</span><span class="label-param-val">${item.width}×${item.height}</span></div>`);
      if (item.file_size) rows.push(`<div class="label-param-row"><span class="label-param-key">文件大小：</span><span class="label-param-val">${formatFileSize(item.file_size)}</span></div>`);
      labelHTML = rows.length ? rows.join('') : buildImageMeta(item);
    } else {
      // === 多图对比模式：保持简洁 ===
      let parts = [];
      if (item.prompt_name && item.prompt_id) {
        parts.push(`<span class="lightbox-prompt-link" onclick="jumpToPrompt(${item.prompt_id})">📝 ${escHtml(item.prompt_name)}</span>`);
      }
      if (item.created_at) parts.push(item.created_at);
      labelHTML = parts.join(' · ') || buildImageMeta(item);
    }

    label.innerHTML = labelHTML;
    label.addEventListener('mousedown', (e) => e.stopPropagation());
    wrap.appendChild(label);

    body.appendChild(wrap);
  });

  // 设置顶部提示词名称（单图模式显示，多图模式清空）
  const headerPrompt = document.getElementById('lightboxHeaderPrompt');
  if (headerPrompt) {
    if (_compareMode === 'single' && _lightboxItems.length > 0) {
      const item = _lightboxItems[_lightboxIndex];
      // 获取提示词名称（按优先级：item.prompt_name -> allPrompts查找 -> API查询）
      let promptName = item.prompt_name || '';
      
      // 如果prompt_name为空，尝试从allPrompts查找
      if (!promptName && item.prompt_id) {
        const found = allPrompts.find(p => p.id === item.prompt_id);
        promptName = found ? found.name : '';
      }
      
      // 如果还是为空，显示默认文本（但不显示"图片 XXX"）
      if (!promptName) {
        promptName = item.prompt_id ? `提示词 #${item.prompt_id}` : `图片 #${item.id}`;
      }
      
      // 确保有内容才显示
      if (promptName && promptName !== `图片 #${item.id}`) {
        if (item.prompt_id) {
          headerPrompt.innerHTML = `<span class="lightbox-prompt-link" onclick="jumpToPrompt(${item.prompt_id})">📝 ${escHtml(promptName)}</span>`;
        } else {
          headerPrompt.textContent = `📝 ${promptName}`;
        }
        headerPrompt.title = promptName;
      } else if (promptName === `图片 #${item.id}`) {
        // 如果是默认文本，不显示提示词名称
        headerPrompt.innerHTML = '';
      } else {
        headerPrompt.innerHTML = '';
      }
    } else {
      headerPrompt.innerHTML = '';
    }
  }

  // 单图模式：键盘导航、操作按钮、路由
  if (_compareMode === 'single') {
    setupImageModalKeyboardNav();
    updateLightboxActions();
    updateRoute();
  }

  // 绑定缩放拖拽交互
  _bindCompareInteractions(body);
}

// 更新灯箱头部操作按钮状态（单图模式调用）
function updateLightboxActions() {
  const item = _lightboxItems[_lightboxIndex];
  if (!item) return;
  const favBtn = document.getElementById('lightboxFavBtn');
  const regenBtn = document.getElementById('lightboxRegenBtn');
  if (favBtn) {
    favBtn.textContent = item.favorite ? '★' : '☆';
    favBtn.title = item.favorite ? '取消收藏' : '收藏';
  }
  if (regenBtn) {
    regenBtn.style.display = item.prompt_id ? '' : 'none';
  }
}


// 灯箱：下载
function downloadFromLightbox() {
  const item = _lightboxItems[_lightboxIndex];
  if (!item) return;
  downloadHistoryItem(item.id);
}

// 灯箱：重新生成
function regenFromLightbox() {
  const item = _lightboxItems[_lightboxIndex];
  if (!item || !item.prompt_id) {
    showToast('该图片没有关联的提示词，无法重新生成', 'error');
    return;
  }
  regenerateFromHistory(item.prompt_id);
}

function setupCompareModalZoom() {
  // 已废弃：现在所有模式统一在 _bindCompareInteractions 处理
  // 保留空函数以防其他地方调用
}

function resetImageZoom() {
  _cancelAllAnimations();

  const wraps = document.querySelectorAll('#compareModalBody .compare-item-wrap');
  wraps.forEach((wrap, idx) => {
    const img = wrap.querySelector('.compare-img');
    if (!img) return;

    const doReset = () => {
      const s = _initImageState(img, wrap);
      if (!s) return;
      while (_imageStates.length <= idx) _imageStates.push(null);
      _imageStates[idx] = s;
      _applyTransform(img, s);
    };

    if (img.complete && img.naturalWidth > 0) {
      doReset();
    } else {
      img.removeEventListener('load', img._resetHandler);
      img._resetHandler = doReset;
      img.addEventListener('load', doReset);
    }
  });
  _updateZoomDisplay();
}

function setupImageModalKeyboardNav() {
  const overlay = document.getElementById('compareModal');
  if (!overlay) return;
  
  // 移除旧监听器
  overlay.removeEventListener('keydown', overlay._keyboardNavHandler);
  
  overlay._keyboardNavHandler = (e) => {
    if (e.key === 'ArrowLeft' && _lightboxIndex > 0) {
      // 上一张
      _lightboxIndex--;
      renderUnifiedImageGrid();
      updateImageModalTitle();
    } else if (e.key === 'ArrowRight' && _lightboxIndex < _lightboxItems.length - 1) {
      // 下一张
      _lightboxIndex++;
      renderUnifiedImageGrid();
      updateImageModalTitle();
    }
  };
  
  overlay.addEventListener('keydown', overlay._keyboardNavHandler);
}

function updateImageModalTitle() {
  const titleText = document.getElementById('imageModalTitleText');
  if (titleText && _compareMode === 'single') {
    titleText.textContent = `图片查看（${_lightboxIndex + 1} / ${_lightboxItems.length}）`;
  }
}



// 灯箱状态持久化
function saveLightboxState() {
  try {
    const state = {
      mode: _compareMode,
      lightboxIndex: _lightboxIndex,
      lightboxItems: _lightboxItems,
      compareItems: _compareItems
    };
    // sessionStorage  per-tab 隔离，多标签页互不影响
    sessionStorage.setItem('pb_lightbox_state', JSON.stringify(state));
  } catch (e) { /* 忽略存储错误 */ }
}

function clearLightboxState() {
  try { sessionStorage.removeItem('pb_lightbox_state'); } catch (e) {}
}

function restoreLightboxState() {
  try {
    const raw = sessionStorage.getItem('pb_lightbox_state');
    if (!raw) return;
    const state = JSON.parse(raw);
    if (!state || !state.mode) return;

    _compareMode = state.mode;
    _lightboxIndex = state.lightboxIndex || 0;
    _lightboxItems = state.lightboxItems || [];
    _compareItems = state.compareItems || [];

    if (_lightboxItems.length > 0 || _compareItems.length > 0) {
      openUnifiedImageModal();
    }
  } catch (e) {
    clearLightboxState();
  }
}

function setupCompareZoom() {
  // 已废弃：对比模式改用自定义弹窗，此函数保留为空以防旧调用
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

function updateGalleryBadge() {
  const badge = document.getElementById('galleryBadge');
  const count = activeJobs.size;
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = 'inline';
  } else {
    badge.style.display = 'none';
  }
}

// 全局 PhotoSwipe 实例（已废弃，改用自定义弹窗）
let pswpLightbox = null;

function openLightbox(src, meta, event, clickedIndex) {
  // 使用自定义弹窗（与多图对比模式相同的技术）
  // 收集所有历史图片用于画廊导航
  const allItems = _historyItems.map((item) => {
    return {
      ...item,
      view_url: item.view_url || `/api/image?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}`
    };
  });
  
  // 设置当前查看的项
  _lightboxItems = allItems;
  _lightboxIndex = clickedIndex >= 0 ? clickedIndex : 0;
  _compareMode = 'single'; // 单图模式，隐藏同步/分屏按钮
  
  // 打开自定义弹窗
  openUnifiedImageModal();
}

// setupLightboxZoom 已废弃：单图现在使用自定义弹窗，复用 setupCompareModalZoom 函数
