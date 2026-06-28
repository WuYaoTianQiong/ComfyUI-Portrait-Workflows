// ui.js - UI通用模块
// 依赖：utils.js

const LS_UI = "promptBrowserUiState_v3";

window.UiState = {
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
// UI 设置函数
// -------------------------------------------------------------------

window.setupResize = function() {
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
      window.UiState.set("sidebarWidth", sidebar.style.width);
    }
  });
};

window.setupWorkflowPopover = function() {
  const trigger = document.getElementById("wfTrigger");
  const popover = document.getElementById("wfPopover");
  
  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    // 互斥：统一由 openDropdown 管理
    window.openDropdown("wfPopover");
    window._wfPopoverOpen = popover.classList.contains("show");
  });
  
  document.addEventListener("click", (e) => {
    if (!popover.contains(e.target) && !trigger.contains(e.target)) {
      popover.classList.remove("show");
      window._wfPopoverOpen = false;
    }
  });
  
  // 捕获阶段拦截 wheel 事件，阻止下拉框滚动穿透到外部
  document.addEventListener("wheel", (e) => {
    if (!popover.classList.contains("show")) return;
    if (!popover.contains(e.target)) return;
    
    // 找到实际滚动的元素（popover 或 popover-list）
    const scrollable = e.target.closest(".wf-popover, .wf-popover-list");
    if (!scrollable) return;
    
    const atTop = scrollable.scrollTop <= 0;
    const atBottom = scrollable.scrollTop + scrollable.clientHeight >= scrollable.scrollHeight - 1;
    
    // 滚动到边界时允许传递，否则拦截
    if ((e.deltaY < 0 && atTop) || (e.deltaY > 0 && atBottom)) return;
    
    e.preventDefault();
    scrollable.scrollTop += e.deltaY;
  }, { passive: false, capture: true });
};

window.closeWorkflowPopover = function() {
  document.getElementById("wfPopover").classList.remove("show");
  window._wfPopoverOpen = false;
};

window.setupKeyboard = function() {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      window.closeModal();
      window.closeVarModal();
      window.closeWorkflowPopover();
      window.closeCompareModal(true);
    }
    if (e.ctrlKey && e.key === "Enter" && window.selectedId && window.comfyStatus === "online") {
      e.preventDefault();
      window.runPrompt();
    }
    if (e.ctrlKey && e.key === "s") {
      if (document.getElementById("modalOverlay").classList.contains("active")) {
        e.preventDefault();
        window.savePrompt();
      }
    }
  });
};

window.setupUnloadGuard = function() {
  window.addEventListener("beforeunload", (e) => {
    if (window.activeJobs && window.activeJobs.size) {
      e.preventDefault();
      e.returnValue = "有生成任务正在运行，刷新页面将丢失实时进度（但会尝试续跑）。";
    }
  });
};

// -------------------------------------------------------------------
// 应用 UI 状态
// -------------------------------------------------------------------

window.applyUiState = function() {
  document.getElementById("searchInput").value = window.UiState.get("search", "");
  document.getElementById("qualitySelect").value = window.UiState.get("quality", "4K");
  window.currentOrientation = window.UiState.get("orientation", "portrait");
  document.getElementById("orientBtn").textContent = window.currentOrientation === "portrait" ? "📱" : "🖥️";
  window.workflowSort = window.UiState.get("workflowSort", "mtime");
  document.getElementById("wfSortBtn").textContent = window.workflowSort === "mtime" ? "最近" : "名称";
  const sw = window.UiState.get("sidebarWidth", "");
  if (sw) document.getElementById("sidebar").style.width = sw;

  const savedSort = window.UiState.get("sortFilter", "newest");
  const sortEl = document.getElementById("sortFilter");
  if (sortEl && [...sortEl.options].some(o => o.value === savedSort)) {
    sortEl.value = savedSort;
  }

  // 恢复上次的分类筛选（含模板特殊值）
  window._pendingCategoryFilter = window.UiState.get("categoryFilter", "");

  window.selectedIds = new Set(window.UiState.get("selectedIds", []));
  window.selectedId = window.UiState.get("selectedId", null) || null;
  window.lastClickedId = window.selectedId;

  const activeTab = window.UiState.get("activeTab", "promptTab");
  if (activeTab === "galleryTab") {
    const btn = document.querySelector('.tab-btn[data-tab="galleryTab"]');
    if (btn) window.switchTab("galleryTab", btn);
  } else if (activeTab === "composerTab") {
    const btn = document.querySelector('.tab-btn[data-tab="composerTab"]');
    if (btn) window.switchTab("composerTab", btn);
  }
};

// -------------------------------------------------------------------
// Tab 切换
// -------------------------------------------------------------------

window.switchTab = function(tabId, btn) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  
  document.getElementById(tabId).classList.add('active');
  btn.classList.add('active');

  window.UiState.set("activeTab", tabId);

  const isNotPrompt = (tabId !== 'promptTab');
  ['qualitySelect', 'orientBtn', 'runBtn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = isNotPrompt ? 'none' : '';
  });

  if (tabId === 'galleryTab') {
    window.loadHistory(false);
  }

  if (tabId === 'composerTab') {
    window.initComposer();
    window.refreshComposer();
  }

  if (tabId !== 'galleryTab') {
    const btn = document.getElementById('compareBtn');
    if (btn) btn.style.display = 'none';
  }

  window.updateRoute();
};
