// app.js - 主入口文件
// 职责：初始化、全局变量声明、事件绑定
// 依赖：utils.js, ui.js, router.js, prompt.js, workflow.js, generator.js, job.js, history.js, gallery.js, imageViewer.js

// -------------------------------------------------------------------
// 全局变量声明
// -------------------------------------------------------------------

window.allPrompts = [];
window.selectedId = null;
window.lastClickedId = null;
window.comfyStatus = "offline";
window.selectedIds = new Set();
window.currentOrientation = "portrait";
window.activeJobId = null;
window.jobPollTimer = null;
window.activeJobs = new Set();
window._currentPromptData = null;
window._promptPage = 1;
window._promptPageSize = 50;
window._promptTotal = 0;
window._gallerySort = "newest";
window._galleryFilter = "all";
window._gallerySearch = "";
window.searchTimer = null;

// -------------------------------------------------------------------
// 初始化
// -------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  // Phase 2: 检测 HTMX 模式（URL 参数 ?htmx=1 或 localStorage）
  const urlParams = new URLSearchParams(window.location.search);
  window._useHtmx = urlParams.get("htmx") === "1" || localStorage.getItem("htmxMode") === "1";
  if (window._useHtmx) {
    document.body.dataset.htmxActive = "1";
    // 移除 `hx-trigger` 上的 `load` 以防止初始化时重复请求
  }

  // HTMX 事件监听：在提示词列表加载完成后触发自定义事件
  document.body.addEventListener("htmx:afterSwap", (event) => {
    // 检查是否是提示词列表容器的交换
    const container = document.getElementById("promptListContainer");
    if (container && container.contains(event.detail.elt)) {
      document.body.dispatchEvent(new CustomEvent("promptListLoaded"));
    }
  });

  window.UiState.load();
  window.loadCustomWorkflow();
  window.hiddenWorkflows = window.getHiddenWorkflows();
  window.applyUiState();
  window.setupResize();
  window.setupWorkflowPopover();
  window.setupKeyboard();
  window.setupUnloadGuard();

  // 初始化路由
  window.handleRoute(window.location.pathname);

  // 加载分类和标签
  window.loadCategories();
  window.loadTags();

  window.loadWorkflows();
  window.loadPrompts().then(() => {
    // 应用保留的分类筛选（如 📦 组合模板）
    if (window._pendingCategoryFilter === "__templates__") {
      setTimeout(() => {
        const sel = document.getElementById("categorySelect");
        if (sel) { sel.value = "__templates__"; onCategoryChange(); }
      }, 100);
    }
    // 选中待选提示词（如从"另存为提示词"跳转回来）
    if (window._pendingSelectPromptId) {
      const pid = window._pendingSelectPromptId;
      window._pendingSelectPromptId = null;
      const exists = window.allPrompts.some(p => p.id === pid);
      if (exists) {
        window.selectPrompt(pid, true, false, false, true);
      }
    } else if (window.selectedId) {
      const exists = window.allPrompts.some(p => p.id === window.selectedId);
      if (exists) window.selectPrompt(window.selectedId, true, false, false, true);
      else window.selectedId = null;
    }
    window.updateRunBtn();
    window.updateSelectionBar();
  });
  window.loadHistory(true);
  window.loadActiveJobs();

  window.checkStatus();
  setInterval(window.checkStatus, 5000);
  setInterval(() => window.loadHistory(false), 30000);

  // 恢复灯箱状态
  window.restoreLightboxState();
});

// -------------------------------------------------------------------
// ComfyUI 状态检查
// -------------------------------------------------------------------

// -------------------------------------------------------------------
// 统计数据加载
// -------------------------------------------------------------------

window.loadStats = async function() {
  const el = document.getElementById("statsContent");
  if (!el) return;
  try {
    const data = await window.api("/api/stats");
    const tagsHtml = (data.top_tags || []).map(t =>
      `<span class="tag" style="background:${t.color}22;color:${t.color};border-color:${t.color}44">${t.name} (${t.count})</span>`
    ).join(" ");
    el.innerHTML = `
      <h2 style="margin-bottom:16px">📊 数据统计</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:20px">
        <div class="stat-card"><div class="stat-number">${data.prompt_count}</div><div class="stat-label">📝 提示词</div></div>
        <div class="stat-card"><div class="stat-number">${data.history_count}</div><div class="stat-label">🖼️ 生成历史</div></div>
        <div class="stat-card"><div class="stat-number">${data.job_count}</div><div class="stat-label">⚙️ 跑图任务</div></div>
        <div class="stat-card"><div class="stat-number">${data.fragment_count}</div><div class="stat-label">🧩 碎片</div></div>
      </div>
      <h3 style="margin-bottom:8px">🏷️ 热门标签</h3>
      <div style="line-height:2">${tagsHtml || '(暂无)'}</div>
    `;
  } catch (e) {
    el.innerHTML = `<div class="empty-tip">加载统计失败: ${e.message}</div>`;
  }
};

window.checkStatus = async function() {
  const dot = document.getElementById("statusDot");
  const text = document.getElementById("statusText");
  try {
    const s = await window.api("/api/status");
    window.comfyStatus = s.comfyui;
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
    window.comfyStatus = "offline";
  }
  window.updateRunBtn();
  window.updateSelectionBar();
};
