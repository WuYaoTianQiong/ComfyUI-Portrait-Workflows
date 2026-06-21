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
    if (window.selectedId) {
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
