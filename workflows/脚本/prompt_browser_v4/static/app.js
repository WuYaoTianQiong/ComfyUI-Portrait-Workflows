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
window._galleryPage = 1;
window._galleryPageSize = 50;
window._galleryAllItems = [];
window.searchTimer = null;

// 提前从存储加载 UI 状态：UiState.get 读取的是内存中的 data，
// 必须在读取前调用 load()（原代码在 DOMContentLoaded 里才 load，导致这里的恢复读到的是空 data）。
window.UiState.load();

// 从存储恢复每页条数
window._promptPageSize = window.UiState.get("promptPageSize", 50);
window._galleryPageSize = window.UiState.get("galleryPageSize", 50);

// 从存储恢复分页/筛选状态（刷新后保持页码、排序、分类、标签等）
window._promptPage = window.UiState.get("promptPage", 1);
window._galleryPage = window.UiState.get("galleryPage", 1);
window._gallerySort = window.UiState.get("gallerySort", "newest");
window._galleryFilter = window.UiState.get("galleryFilter", "all");
window._gallerySearch = window.UiState.get("gallerySearch", "");
// 分类与标签筛选也需要恢复，否则刷新后侧栏已选标签会被重置为空
window._galleryCategoryId = window.UiState.get("galleryCategoryId", "") || "";
window._galleryTagIds = (function () {
  const raw = window.UiState.get("galleryTagIds", "");
  return (typeof raw === "string" && raw) ? raw.split(",").filter(Boolean).map(Number) : [];
})();
// 同步画廊筛选控件，使 HTMX 初始请求的 hx-vals 能读到已恢复的值
const _gsEl = document.getElementById("gallerySort");
if (_gsEl) _gsEl.value = window._gallerySort;
const _gfEl = document.getElementById("galleryFilter");
if (_gfEl) _gfEl.value = window._galleryFilter;
const _gseEl = document.getElementById("gallerySearch");
if (_gseEl) _gseEl.value = window._gallerySearch;
// 让提示词列表初始 HTMX 请求也使用已恢复的页码（避免被写死的 page=1 覆盖）
const _plc = document.getElementById("promptListContainer");
if (_plc) _plc.setAttribute("hx-get", `/api/prompts/html?search=&sort=default&page=${window._promptPage || 1}`);

// -------------------------------------------------------------------
// HTMX 模式检测 —— 必须在 DOMContentLoaded 之前执行，否则 HTMX 库的
// 内部 handler 会抢先处理 hx-trigger="load" → 发出一次 HTML 端请求，
// 与我们 JS 端 loadHistory 的 JSON 请求形成竞态（HTMX 的 outerHTML swap
// 会销毁 JS 已渲染好的过滤结果，导致"过滤图闪现后被全部图片覆盖"）。
// -------------------------------------------------------------------
{
  const _urlParams = new URLSearchParams(window.location.search);
  window._useHtmx = _urlParams.get("htmx") === "1" || localStorage.getItem("htmxMode") === "1";
  if (window._useHtmx) {
    document.body.dataset.htmxActive = "1";
  } else {
    // 非 HTMX 模式：立即移除所有 hx-* 属性，HTMX 库在 DOMContentLoaded
    // 时将看不到任何 hx-trigger → 不会发出额外请求
    document.querySelectorAll('[hx-get]').forEach(el => {
      ['hx-get', 'hx-trigger', 'hx-target', 'hx-swap', 'hx-vals', 'hx-swap-oob'].forEach(a => el.removeAttribute(a));
    });
  }
}

// -------------------------------------------------------------------
// 初始化
// -------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {

  // HTMX 事件监听：在提示词列表加载完成后触发自定义事件
  document.body.addEventListener("htmx:afterSwap", (event) => {
    // 检查是否是提示词列表容器的交换
    const container = document.getElementById("promptListContainer");
    if (container && container.contains(event.detail.elt)) {
      document.body.dispatchEvent(new CustomEvent("promptListLoaded"));
    }
    // 画廊 HTMX 交换后恢复选中状态和全选复选框
    if (event.detail.elt.id === 'galleryGridInner' || event.detail.elt.id === 'galleryContainer' || event.detail.elt.querySelector('#galleryGrid')) {
      // 恢复每个 gallery-item 的选中状态
      window._gallerySelectedIds.forEach(id => {
        const checkEl = document.querySelector(`.gallery-item-check[data-id="${id}"]`);
        if (checkEl) checkEl.classList.add('checked');
      });
      window.updateGalleryActionButtons();
      window.updateCompareButton();
      window.updateGallerySelectAllCheck();
    }
  });

  // 画廊刷新时同步更新侧栏标签/分类计数；非 HTMX 模式下同时手动触发画廊内容刷新
  document.body.addEventListener("galleryRefresh", () => {
    window.loadGallerySidebar?.();
    if (document.body.dataset.htmxActive !== "1") {
      window.loadHistory?.(false);
    }
  });

  // 持久化画廊/提示词的分页与筛选状态（HTMX 模式下翻页/筛选请求都带参数）
  document.body.addEventListener("htmx:beforeRequest", (event) => {
    const cfg = event.detail && event.detail.requestConfig;
    if (!cfg || !cfg.url) return;
    const u = cfg.url;
    if (u.indexOf("/api/history/html") !== -1) {
      const params = new URLSearchParams(u.split("?")[1] || "");
      const p = params.get("page"); if (p) window._galleryPage = parseInt(p, 10) || 1;
      const s = params.get("sort"); if (s) window._gallerySort = s;
      window._galleryFilter = params.get("favorite") === "1" ? "favorite" : "all";
      window._gallerySearch = params.get("search") || "";
      window._persistGalleryState();
    } else if (u.indexOf("/api/prompts/html") !== -1) {
      const params = new URLSearchParams(u.split("?")[1] || "");
      const p = params.get("page");
      if (p) { window._promptPage = parseInt(p, 10) || 1; window.UiState.set("promptPage", window._promptPage); }
    }
  });

  window.loadCustomWorkflow();
  window.hiddenWorkflows = window.getHiddenWorkflows();
  window.applyUiState();
  window.setupResize();
  window.setupKeyboard();

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
  // 页面加载时不触发 sync（后台 job_monitor_loop 每 30s 已自动同步），
  // 避免每次 F5 都扫描 ComfyUI 全量历史 + 逐图读元数据（实测 ~5s）
  window.loadHistory(false, false);
  window.loadActiveJobs();

  window.checkStatus();
  setInterval(window.checkStatus, 5000);
  // 每 30 秒先同步后台新图片（/api/history_sync），再重新读取当前页（resetPage=false 保留页码）
  // 避免前端刷新与后端同步两个 30 秒循环时钟不同步导致的新图延迟（最差 60s → 最差 30s）
  setInterval(async () => {
    try {
      await window.api('/api/history_sync?page_size=1'); // 后台同步，body 小忽略
    } catch (_) {}
    window.loadHistory(false, false); // 刷新当前页
  }, 30000);

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
