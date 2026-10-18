// ui.js - UI通用模块
// 依赖：utils.js

const LS_UI = "promptBrowserUiState_v3";

window.UiState = {
  data: {},
  _storageAvailable: true,
  
  load() {
    try {
      const stored = localStorage.getItem(LS_UI);
      if (stored) {
        this.data = JSON.parse(stored);
      }
    } catch (e) {
      console.warn("[UiState] localStorage 不可用，状态将不会持久化:", e.message);
      this._storageAvailable = false;
    }
  },
  
  save() {
    if (!this._storageAvailable) return;
    try {
      localStorage.setItem(LS_UI, JSON.stringify(this.data));
    } catch (e) {
      console.warn("[UiState] 保存状态失败:", e.message);
      this._storageAvailable = false;
    }
  },
  
  set(k, v) { 
    this.data[k] = v; 
    this.save(); 
  },
  
  get(k, def) { 
    return this.data[k] !== undefined ? this.data[k] : def; 
  }
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

// 通用函数：点击弹窗背景关闭
window.closeModalOnBackdrop = function(event, closeFunc) {
  if (event.target === event.currentTarget) {
    closeFunc();
  }
};

// 通用函数：为按钮添加操作反馈效果
window.showButtonFeedback = function(btn, successText, duration) {
  if (!btn) return;
  const originalText = btn.innerHTML;
  const originalDisabled = btn.disabled;
  btn.innerHTML = successText;
  btn.disabled = true;
  setTimeout(() => {
    btn.innerHTML = originalText;
    btn.disabled = originalDisabled;
  }, duration || 1500);
};

window.setupKeyboard = function() {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      window.closeModal();
      window.closeVarModal();
      window.closeWfModal();
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

// -------------------------------------------------------------------
// 应用 UI 状态
// -------------------------------------------------------------------

window.applyUiState = function() {
  document.getElementById("searchInput").value = window.UiState.get("search", "");
  document.getElementById("qualitySelect").value = window.UiState.get("quality", "4K");
  window.currentOrientation = window.UiState.get("orientation", "portrait");
  document.getElementById("orientBtn").textContent = window.currentOrientation === "portrait" ? "📱" : "🖥️";
  window.workflowSort = window.UiState.get("workflowSort", "mtime");
  const wfSortBtn = document.getElementById("wfSortBtn");
  if (wfSortBtn) wfSortBtn.textContent = window.workflowSort === "mtime" ? "最近" : "名称";
  const sw = window.UiState.get("sidebarWidth", "");
  if (sw) document.getElementById("sidebar").style.width = sw;

  // 恢复排序状态
  window._sortField = window.UiState.get("sortField", "default");
  window._sortOrder = window.UiState.get("sortOrder", "desc");
  const sortFieldEl = document.getElementById("sortField");
  if (sortFieldEl) sortFieldEl.value = window._sortField;
  if (typeof window._updateSortOrderBtn === "function") window._updateSortOrderBtn();

  // 恢复上次的分类筛选（含模板特殊值）
  window._pendingCategoryFilter = window.UiState.get("categoryFilter", "");

  window.selectedIds = new Set(window.UiState.get("selectedIds", []));
  window.selectedId = window.UiState.get("selectedId", null) || null;
  window.lastClickedId = window.selectedId;

  const activeTab = window.UiState.get("activeTab", "promptTab");
  if (activeTab === "promptTab") {
    const btn = document.querySelector('.tab-btn[data-tab="promptTab"]');
    if (btn) window.switchTab("promptTab", btn);
  } else if (activeTab === "galleryTab") {
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

  // 画廊和统计 Tab 隐藏方向/画质/跑图控件，提示词和组合创作 Tab 保持可见。
  // 批量换脸 Tab 也隐藏：它有独立提交按钮，且画质/横竖屏对该类工作流是空转（易误导）。
  const hideControls = (tabId === 'galleryTab' || tabId === 'statsTab' || tabId === 'faceswapTab');
  ['qualitySelect', 'orientBtn', 'runBtn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = hideControls ? 'none' : '';
  });

  if (tabId === 'galleryTab') {
    if (typeof window.loadHistory === "function") {
      // 切换到画廊时触发同步，确保新生成/外部 ComfyUI 图片也出现在画廊
      window.loadHistory(true);
    }
  }

  if (tabId === 'composerTab') {
    window.initComposer();
    window.refreshComposer();
  }

  if (tabId === 'faceswapTab') {
    window.initFaceswap();
  }

  if (tabId !== 'galleryTab') {
    const btn = document.getElementById('compareBtn');
    if (btn) btn.style.display = 'none';
  }

  window.updateRoute(true);
};
