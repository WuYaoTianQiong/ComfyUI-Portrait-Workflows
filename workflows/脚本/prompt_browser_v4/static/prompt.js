// prompt.js - 提示词模块
// 依赖：utils.js, ui.js, router.js

// -------------------------------------------------------------------
// 提示词列表和详情
// -------------------------------------------------------------------

window.loadPrompts = async function(page) {
  return window.withLock("loadPrompts", async () => {
    if (page) window._promptPage = page;
    window.UiState.set("promptPage", window._promptPage || 1);
    const search = document.getElementById("searchInput").value;
    const sortParams = window.getSortParams();

    // Phase 2: HTMX mode —— 构建 URL 参数后触发服务端渲染
    if (document.body.dataset.htmxActive === "1") {
      const p = { search, ...sortParams, page: window._promptPage || 1, page_size: window._promptPageSize };
      // 修复：只有 category_id 是有效整数时才传递
      if (window._currentCategoryId != null && String(window._currentCategoryId).match(/^\d+$/)) {
        p.category_id = window._currentCategoryId;
      }
      if (window._selectedTags && window._selectedTags.size > 0)
        p.tag_ids = Array.from(window._selectedTags).join(",");
      const qs = new URLSearchParams(p).toString();
      const container = document.getElementById("promptListContainer");
      if (container) container.setAttribute("hx-get", "/api/prompts/html?" + qs);
      
      // 返回一个 Promise，等待 HTMX 加载完成
      return new Promise((resolve) => {
        const onLoad = () => {
          document.body.removeEventListener("promptListLoaded", onLoad);
          window._composerDataStale = true;
          resolve();
        };
        document.body.addEventListener("promptListLoaded", onLoad);
        document.body.dispatchEvent(new CustomEvent("promptListRefresh"));
        
        // 超时保护（5秒）
        setTimeout(() => {
          document.body.removeEventListener("promptListLoaded", onLoad);
          resolve();
        }, 5000);
      });
    }

    const params = {
      search: search,
      ...sortParams,
      page: window._promptPage,
      page_size: window._promptPageSize,
    };

    // 修复：只有 category_id 是有效整数时才传递
    if (window._currentCategoryId != null && String(window._currentCategoryId).match(/^\d+$/)) {
      params.category_id = window._currentCategoryId;
    }

    if (window._selectedTags && window._selectedTags.size > 0) {
      params.tag_ids = Array.from(window._selectedTags).join(",");
    }

    try {
      const queryString = new URLSearchParams(params).toString();
      const data = await window.api(`/api/prompts?${queryString}`);
      window.allPrompts = data.prompts || [];
      window._promptTotal = data.total || 0;
      window.renderList(window.allPrompts);
      window.renderPagination();

      // 提示词筛选变化后，标记组合创作数据需要刷新
      window._composerDataStale = true;
    } catch (e) {
      window.showToast("加载提示词失败: " + e.message, "error");
    }
  });
};

// -------------------------------------------------------------------
// 加载组合模板（作为列表项展示）
// -------------------------------------------------------------------
window.loadTemplatesAsItems = async function () {
  return window.withLock("loadTemplates", async () => {
    try {
      const sp = window.getSortParams();
      const sortStr = sp.sort + (sp.order ? `&order=${sp.order}` : "");
      const data = await window.api(`/api/templates/as_items?sort=${sortStr}`);
      window.allPrompts = data.prompts || [];
      window._promptTotal = data.total || 0;
      window.renderList(window.allPrompts);
      window.renderPagination();
    } catch (e) {
      window.showToast("加载模板失败: " + e.message, "error");
    }
  });
};

// 点击模板列表项 → 跳转到组合创作并加载
window.selectTemplateItem = function (templateId, name) {
  // 先保存要打开的目标，再切换 tab
  window._pendingTemplateId = templateId;
  const btn = document.querySelector('.tab-btn[data-tab="composerTab"]');
  if (btn) window.switchTab("composerTab", btn);
};

// ======== 排序相关 ========
window._sortField = "default";
window._sortOrder = "desc";

window.initSortState = function() {
  window._sortField = window.UiState.get("sortField", "default");
  window._sortOrder = window.UiState.get("sortOrder", "desc");
  const fieldEl = document.getElementById("sortField");
  if (fieldEl) fieldEl.value = window._sortField;
  window._updateSortOrderBtn();
};

window._updateSortOrderBtn = function() {
  const btn = document.getElementById("sortOrderBtn");
  if (!btn) return;
  if (window._sortField === "default") {
    btn.style.display = "none";
  } else {
    btn.style.display = "";
    btn.textContent = window._sortOrder === "asc" ? "↑" : "↓";
    btn.title = window._sortOrder === "asc" ? "升序" : "降序";
  }
};

window.toggleSortOrder = function() {
  window._sortOrder = window._sortOrder === "asc" ? "desc" : "asc";
  window._updateSortOrderBtn();
  window.UiState.set("sortOrder", window._sortOrder);
  window.onSortFieldChange();
};

window.onSortFieldChange = function() {
  const fieldEl = document.getElementById("sortField");
  if (fieldEl) window._sortField = fieldEl.value;
  window._updateSortOrderBtn();
  window._promptPage = 1;
  window.UiState.set("sortField", window._sortField);
  window.UiState.set("sortOrder", window._sortOrder);
  if (window._currentCategoryId === "__templates__") {
    window.loadTemplatesAsItems();
  } else {
    window.loadPrompts();
  }
};

// 兼容旧调用
window.onSortChange = window.onSortFieldChange;

window.getSortParams = function() {
  if (window._sortField === "default") return { sort: "default" };
  return { sort: window._sortField, order: window._sortOrder };
};

// ======== 自动分类 ========
window.autoClassifyAll = async function() {
  const btn = document.querySelector('[onclick="autoClassifyAll()"]');
  if (btn) { btn.disabled = true; btn.textContent = "⏳ 分类中..."; }
  try {
    const r = await window.api("/api/categories/auto-classify", { method: "POST" });
    let msg = `已分类 ${r.classified} 条`;
    if (r.skipped) msg += `，${r.skipped} 条已有分类`;
    window.showToast(msg, "success");
    window.loadCategories();
    window.loadPrompts();
  } catch (e) {
    window.showToast("自动分类失败: " + e.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "🔄 自动分类"; }
  }
};

window.renderList = function(prompts) {
  const list = document.getElementById("promptList");
  list.innerHTML = "";
  if (!prompts.length) {
    list.innerHTML = '<div class="empty-tip">暂无匹配的提示词</div>';
    return;
  }
  prompts.forEach(p => {
    const isTemplate = p._is_template === true;
    const div = document.createElement("div");
    div.className = "prompt-item" + (p.id === window.selectedId ? " active" : "") + (isTemplate ? " template-item" : "");
    div.dataset.id = p.id;

    if (isTemplate) {
      // 模板列表项
      const syncIcon = p._has_missing
        ? '<span class="template-sync-warn" title="部分来源已删除">○</span>'
        : '<span class="template-sync-ok" title="来源正常">●</span>';
      const shortPreview = p.prompt_preview && p.prompt_preview.length > 80
        ? window.escHtml(p.prompt_preview.slice(0, 80)) + "..."
        : window.escHtml(p.prompt_preview);
      div.innerHTML = `
        <div class="item-row">
          <div class="item-body">
            <div class="prompt-name">📦 ${syncIcon} ${window.escHtml(p.name)}</div>
            <div class="prompt-preview" style="color:var(--muted);font-size:11px">${shortPreview}</div>
            <div class="prompt-meta"><span class="tag">📦 组合模板</span><span style="color:var(--muted);font-size:10px">${p.fragment_count || 0} 个碎片</span></div>
          </div>
        </div>`;
      div.onclick = () => window.selectTemplateItem(p.id, p.name);
    } else {
      // 普通提示词列表项
      const tags = (p.tags || "").split(",").filter(Boolean);
      const tagsHtml = tags.map(t => `<span class="tag">${window.escHtml(t.trim())}</span>`).join("");
      const preview = window.escHtml(p.prompt_preview) + (p.prompt_preview.length >= 60 ? "..." : "");
      const nameLine = p.name ? `<div class="prompt-name">${window.escHtml(p.name)}</div>` : "";

      const favIcon = p.is_favorite ? '★' : '☆';
      const pinIcon = p.is_pinned ? '📌' : '';
      const ratingStars = p.rating ? '⭐'.repeat(p.rating) : '';
      const usageCount = p.usage_count > 0 ? `<span class="usage-count" title="使用次数">🔄${p.usage_count}</span>` : '';

      const indicators = `
        <div class="prompt-indicators">
          <span class="indicator-fav ${p.is_favorite ? 'active' : ''}" onclick="event.stopPropagation();window.togglePromptFavorite(${p.id}, this)" title="收藏">${favIcon}</span>
          <span class="indicator-pin ${p.is_pinned ? 'active' : ''}" onclick="event.stopPropagation();window.togglePromptPin(${p.id}, this)" title="置顶">${pinIcon}</span>
          ${ratingStars ? `<span class="indicator-rating" title="评级">${ratingStars}</span>` : ''}
          ${usageCount}
        </div>
      `;

      const bodyHtml = nameLine +
        `<div class="prompt-preview">${preview}</div>` +
        `<div class="prompt-meta">${p.steps ? `<span class="badge">${p.steps}步</span>` : ""}${p.sampler ? `<span style="color:#888">${window.escHtml(p.sampler)}</span>` : ""}${tagsHtml}</div>` +
        indicators;

      const checked = window.selectedIds.has(p.id) ? " checked" : "";
      div.innerHTML = `<div class="item-row"><label class="check-wrap" onclick="event.stopPropagation()"><input type="checkbox" class="item-check" data-id="${p.id}"${checked} onchange="window.toggleItemSelect(${p.id},this.checked)"></label><div class="item-body">${bodyHtml}</div></div>`;
      div.onclick = (e) => {
        if (e.target.closest(".check-wrap")) return;
        window.selectPrompt(p.id, true, e.shiftKey, e.ctrlKey || e.metaKey);
      };
    }
    list.appendChild(div);
  });
};

/** 通用分页组件：提示词与画廊复用同一套渲染逻辑 */
window.renderPaginationCore = function(opts) {
  const total = opts.total || 0;
  const page = opts.page || 1;
  const pageSize = opts.pageSize || 50;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const el = document.getElementById(opts.containerId);
  if (!el) return;

  const pageSizeOptions = opts.pageSizeOptions || [20, 50, 100, 200, 500, 1000];
  let pageSizeHtml = `每页 <select class="page-size-select" onchange="${opts.onPageSize}(parseInt(this.value))">`;
  for (const sz of pageSizeOptions) {
    pageSizeHtml += `<option value="${sz}"${sz === pageSize ? ' selected' : ''}>${sz}</option>`;
  }
  pageSizeHtml += `</select> 条`;

  let html = `<span class="page-info">第 ${page}/${totalPages} 页，共 ${total} 条</span>`;
  html += `<span class="page-info">${pageSizeHtml}</span>`;

  // 仅当超过1页时显示翻页按钮
  if (totalPages > 1) {
    html += `<button class="page-btn" ${page <= 1 ? "disabled" : ""} onclick="${opts.onPage}(1)">«</button>`;
    html += `<button class="page-btn" ${page <= 1 ? "disabled" : ""} onclick="${opts.onPage}(${page - 1})">‹</button>`;

    let start = Math.max(1, page - 2);
    let end = Math.min(totalPages, start + 4);
    start = Math.max(1, end - 4);
    for (let i = start; i <= end; i++) {
      html += `<button class="page-btn${i === page ? " active" : ""}" onclick="${opts.onPage}(${i})">${i}</button>`;
    }

    html += `<button class="page-btn" ${page >= totalPages ? "disabled" : ""} onclick="${opts.onPage}(${page + 1})">›</button>`;
    html += `<button class="page-btn" ${page >= totalPages ? "disabled" : ""} onclick="${opts.onPage}(${totalPages})">»</button>`;
  }

  el.innerHTML = html;
};

window.renderPagination = function() {
  window.renderPaginationCore({
    containerId: "promptPagination",
    total: window._promptTotal,
    page: window._promptPage,
    pageSize: window._promptPageSize,
    onPage: "window.loadPrompts",
    onPageSize: "window.changePromptPageSize",
  });
};

/** 切换每页显示条数 */
window.changePromptPageSize = function(size) {
  if (size === window._promptPageSize) return;
  window._promptPageSize = size;
  window._promptPage = 1;
  window.UiState.set("promptPageSize", size);
  window.loadPrompts();
};

// 动态创建定位条（不依赖 index.html 结构）
window._ensureLocateBar = function() {
  if (document.getElementById("locateBar")) return;
  const sidebar = document.getElementById("sidebar");
  if (!sidebar) return;
  const bar = document.createElement("div");
  bar.id = "locateBar";
  bar.style.cssText = "display:none;padding:4px 12px;text-align:center;border-bottom:1px solid var(--border);background:rgba(99,102,241,0.06)";
  const btn = document.createElement("button");
  btn.className = "btn btn-xxs btn-ghost";
  btn.textContent = "📍 定位到已选";
  btn.title = "滚动到当前选中的提示词";
  btn.onclick = () => window.locateSelectedPrompt();
  bar.appendChild(btn);
  // 插入到 promptListContainer 之前
  const container = document.getElementById("promptListContainer");
  if (container) {
    sidebar.insertBefore(bar, container);
  } else {
    sidebar.appendChild(bar);
  }
};

window.locateSelectedPrompt = async function() {
  // 目标：优先当前激活的单条提示词；否则取最近勾选的多选项（"已选 N 项"）
  let targetId = window.selectedId;
  if (!targetId && window.selectedIds && window.selectedIds.size > 0) {
    targetId = Array.from(window.selectedIds).pop();
  }
  if (!targetId) {
    window.showToast("请先选择一条提示词", "info");
    return;
  }
  // 1) 当前页直接滚动
  let item = document.querySelector(`.prompt-item[data-id="${targetId}"]`);
  if (item) {
    item.scrollIntoView({ block: "center", behavior: "smooth" });
    return;
  }
  // 2) 跨页：向后端查询全局序号，计算页码并跳转
  try {
    const search = document.getElementById("searchInput").value;
    const sortParams = window.getSortParams();
    const p = { search, ...sortParams, prompt_id: targetId };
    if (window._currentCategoryId != null && String(window._currentCategoryId).match(/^\d+$/)) {
      p.category_id = window._currentCategoryId;
    }
    if (window._selectedTags && window._selectedTags.size > 0) {
      p.tag_ids = Array.from(window._selectedTags).join(",");
    }
    const qs = new URLSearchParams(p).toString();
    const data = await window.api(`/api/prompts/position?${qs}`);
    if (data.found) {
      const targetPage = Math.floor(data.index / window._promptPageSize) + 1;
      window._promptPage = targetPage;
      await window.loadPrompts();
      setTimeout(() => {
        const el = document.querySelector(`.prompt-item[data-id="${targetId}"]`);
        if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
        else window.showToast("已跳转到对应页，但未找到该项", "warn");
      }, 250);
    } else {
      // 当前筛选下不存在：清空筛选后重试
      const searchEl = document.getElementById("searchInput");
      if (searchEl) searchEl.value = "";
      window._currentCategoryId = null;
      window._promptPage = 1;
      await window.loadPrompts();
      setTimeout(() => {
        const el = document.querySelector(`.prompt-item[data-id="${targetId}"]`);
        if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
        else window.showToast("未找到该提示词（可能已被删除）", "warn");
      }, 250);
    }
  } catch (e) {
    window.showToast("定位失败: " + e.message, "error");
  }
};

window.selectPrompt = async function(id, fetchDetail = true, shiftKey = false, ctrlKey = false, isRestore = false) {
  // 确保定位条存在并显示
  window._ensureLocateBar();
  const locateBar = document.getElementById("locateBar");
  if (locateBar) locateBar.style.display = "flex";
  if (shiftKey && window.lastClickedId !== null) {
    const ids = window.allPrompts.map(p => p.id);
    const start = ids.indexOf(window.lastClickedId);
    const end = ids.indexOf(id);
    if (start !== -1 && end !== -1) {
      const [a, b] = start < end ? [start, end] : [end, start];
      for (let i = a; i <= b; i++) window.selectedIds.add(ids[i]);
      window.UiState.set("selectedIds", Array.from(window.selectedIds));
    }
    window.lastClickedId = id;
    window.renderList(window.allPrompts);
    window.updateRunBtn();
    window.updateSelectionBar();
    return;
  }
  if (ctrlKey) {
    if (window.selectedIds.has(id)) window.selectedIds.delete(id); else window.selectedIds.add(id);
    window.lastClickedId = id;
    window.UiState.set("selectedIds", Array.from(window.selectedIds));
    window.renderList(window.allPrompts);
    window.updateRunBtn();
    window.updateSelectionBar();
    return;
  }
  if (isRestore) {
    window.selectedId = id;
    window.lastClickedId = id;
    window.renderList(window.allPrompts);
    window.updateRunBtn();
    window.updateSelectionBar();
    if (!fetchDetail) return;
    try {
      const p = await window.api(`/api/prompts/${id}`);
      window._currentPromptData = p;
      window.renderDetail(p);
      window.loadPromptHistory(id);
    } catch (e) {
      window.showToast("加载详情失败: " + e.message, "error");
    }
    return;
  }
  window.selectedId = id;
  window.lastClickedId = id;
  window.renderList(window.allPrompts);
  window.updateRunBtn();
  window.updateSelectionBar();
  window.UiState.set("selectedId", id);
  window.updateRoute();
  if (!fetchDetail) return;
  try {
    const p = await window.api(`/api/prompts/${id}`);
    window._currentPromptData = p;
    window.renderDetail(p);
    window.loadPromptHistory(id);
  } catch (e) {
    window.showToast("加载详情失败: " + e.message, "error");
  }
};

window.renderDetail = function(p) {
  const panel = document.getElementById("detailPanel");

  const categories = p.categories || [];
  const categoryHtml = categories.length > 0 ?
    categories.map(c => `<span class="tag" style="background:${c.color}20;color:${c.color};border:1px solid ${c.color}20">${window.escHtml(c.name)}</span>`).join("") :
    '<span style="color:#666;font-size:13px">未分类</span>';

  const tagsDetail = p.tags_detail || [];
  const tags = (p.tags || "").split(",").filter(Boolean);
  let tagHtml = '';
  if (tagsDetail.length > 0) {
    tagHtml = tagsDetail.map(t => `<span class="tag" style="background:${t.color}20;color:${t.color};border:1px solid ${t.color}18">${window.escHtml(t.name)}</span>`).join("");
  } else {
    tagHtml = tags.map(t => `<span class="tag">${window.escHtml(t.trim())}</span>`).join("");
  }

  const favClass = p.is_favorite ? 'active' : '';
  const favIcon = p.is_favorite ? '★' : '☆';
  const pinClass = p.is_pinned ? 'active' : '';
  const pinIcon = p.is_pinned ? '📌' : '📌';

  let ratingHtml = '<div class="rating-control">';
  for (let i = 1; i <= 5; i++) {
    const starClass = (p.rating || 0) >= i ? 'active' : '';
    ratingHtml += `<span class="rating-star ${starClass}" onclick="window.ratePrompt(${p.id}, ${i})" title="${i}星">★</span>`;
  }
  ratingHtml += '</div>';

  const usageHtml = p.usage_count > 0 ?
    `<div class="usage-stat">使用次数: ${p.usage_count}${p.last_used_at ? ` · 最后使用: ${p.last_used_at}` : ''}</div>` :
    '';

  panel.innerHTML =
    (p.name ? `<div class="detail-header"><div class="detail-name">${window.escHtml(p.name)}</div><div class="detail-actions">` +
      `<button class="btn btn-sm btn-primary" onclick="window.runPrompt(${p.id})" title="使用当前选中工作流跑图">🚀 跑图</button>` +
      `<button id="detailFavBtn" class="btn btn-sm ${favClass}" onclick="window.togglePromptFavorite(${p.id}, this)" title="收藏">${favIcon}</button>` +
      `<button id="detailPinBtn" class="btn btn-sm ${pinClass}" onclick="window.togglePromptPin(${p.id}, this)" title="置顶">${pinIcon}</button>` +
      `<button class="btn btn-sm btn-warning" onclick="window.openVariationDialog()">🎲 变体</button>` +
      `<button class="btn btn-sm btn-warning" onclick="window.openEditModal(${p.id})">✏️ 编辑</button>` +
      `<button class="btn btn-sm btn-danger" onclick="window.deletePrompt(${p.id})">🗑️ 删除</button>` +
    `</div></div>${ratingHtml}${usageHtml}` : "") +
    `<div class="section"><h3>📝 正面提示词 <button class="copy-btn" onclick="window.copyPromptText(this,0)">复制</button></h3><div class="content pos">${window.formatFragmentDisplay(p.prompt)}</div></div>` +
    `<div class="section"><h3>🚫 负面提示词 <button class="copy-btn" onclick="window.copyPromptText(this,1)">复制</button></h3><div class="content neg">${window.escHtml(p.negative_prompt || "(空)")}</div></div>` +
    `<div class="section"><h3>⚙️ 参数</h3><div class="params">` +
      `<div class="param-item"><div class="label">步数</div><div class="value">${p.steps || "-"}</div></div>` +
      `<div class="param-item"><div class="label">CFG</div><div class="value">${p.cfg_scale || "-"}</div></div>` +
      `<div class="param-item"><div class="label">采样器</div><div class="value">${window.escHtml(p.sampler || "-")}</div></div>` +
      `<div class="param-item"><div class="label">种子</div><div class="value">${p.seed ?? "-"}</div></div>` +
      `<div class="param-item"><div class="label">分辨率</div><div class="value">${p.width ? p.width + "×" + p.height : "-"}</div></div>` +
      `<div class="param-item"><div class="label">模型</div><div class="value" style="font-size:11px" title="${window.escHtml(p.model || "-")}">${window.escHtml(p.model || "-")}</div></div>` +
    `</div></div>` +
    (p.note ? `<div class="section"><h3>📌 备注</h3><div class="note-box">${window.escHtml(p.note)}</div></div>` : "") +
    `<div class="section"><h3>📂 分类</h3><div>${categoryHtml}</div></div>` +
    `<div class="section"><h3>🏷️ 标签</h3><div>${tagHtml || '<span style="color:#666;font-size:13px">无标签</span>'}</div></div>` +
    `<div class="section prompt-history-section" id="promptHistorySection"></div>` +
    `<div style="color:#555;font-size:11px;margin-top:16px">创建: ${p.created_at || "未知"}${p.updated_at && p.updated_at !== p.created_at ? " · 更新: " + p.updated_at : ""}</div>`;
};

// -------------------------------------------------------------------
// 分段编辑
// -------------------------------------------------------------------
const FRAGMENT_KEYS = ["拍摄视角", "姿态动作", "人物身材", "人物服饰", "人物面部", "场景环境", "光影色调", "画风技术"];
const FRAGMENT_ICONS = { "拍摄视角": "📷", "姿态动作": "🏃", "人物身材": "🧍", "人物服饰": "👗", "人物面部": "👤", "场景环境": "🌄", "光影色调": "💡", "画风技术": "🎨" };
const FRAGMENT_COLORS = { "拍摄视角": "#f97316", "姿态动作": "#f59e0b", "人物身材": "#059669", "人物服饰": "#a855f7", "人物面部": "#10b981", "场景环境": "#3b82f6", "光影色调": "#06b6d4", "画风技术": "#ef4444" };

window._fragmentEditMode = false;
window._customFragmentKeys = [];  // 当前弹窗内用户新增的自定义碎片模块标题

function allFragmentKeys() {
  return [...FRAGMENT_KEYS, ...(window._customFragmentKeys || [])];
}

// 收集当前所有碎片 textarea 的内容
function collectFragmentValues() {
  const fragments = {};
  for (const k of allFragmentKeys()) {
    const ta = document.getElementById(`f_frag_${k}`);
    if (ta) fragments[k] = ta.value;
  }
  return fragments;
}

// 渲染分段编辑器：固定八大碎片 + 自定义碎片模块 + 新增按钮
window.renderFragmentEditor = function (fragments) {
  const fragContainer = document.getElementById("f_fragments");
  const ta = document.getElementById("f_prompt");
  const btn = document.getElementById("f_toggleFragBtn");
  if (!fragContainer) return;
  let html = "";
  for (const key of allFragmentKeys()) {
    const color = FRAGMENT_COLORS[key] || "#6366f1";
    const icon = FRAGMENT_ICONS[key] || "📝";
    const val = fragments[key] || "";
    const isCustom = !FRAGMENT_KEYS.includes(key);
    const customIdx = window._customFragmentKeys ? window._customFragmentKeys.indexOf(key) : -1;
    html += `
      <div class="frag-field" id="frag_field_${key}">
        <div class="frag-field-label" style="color:${color}">
          ${icon} ${key}
          ${isCustom ? `<button type="button" class="frag-remove-btn" onclick="window.removeCustomFragment(${customIdx})" title="删除该碎片模块">✕</button>` : ""}
          <span class="frag-changed-dot" id="frag_dot_${key}" style="display:none;font-size:10px;color:#f59e0b;margin-left:4px">● 已修改</span>
        </div>
        <textarea id="f_frag_${key}" data-fragkey="${key}" data-original="${window.escAttr(val)}"
          oninput="window._markFragmentChanged(this);window._autoResizeFrag(this)">${window.escHtml(val)}</textarea>
      </div>`;
  }
  html += `
    <div class="frag-add-row">
      <button type="button" class="btn btn-sm btn-ghost" onclick="window.addCustomFragment()">＋ 新增碎片模块</button>
    </div>`;
  fragContainer.innerHTML = html;
  // 渲染后按内容撑高每个碎片 textarea
  fragContainer.querySelectorAll('textarea[data-fragkey]').forEach(ta => window._autoResizeFrag(ta));
  if (ta) ta.style.display = "none";
  fragContainer.style.display = "flex";
  if (btn) { btn.style.display = ""; btn.textContent = "📝 切换到全文编辑"; }
  window._fragmentEditMode = true;
};

window.addCustomFragment = function () {
  const raw = window.prompt ? window.prompt("输入新碎片模块名称：") : prompt("输入新碎片模块名称：");
  if (!raw) return;
  const name = String(raw).trim();
  if (!name) return;
  if (FRAGMENT_KEYS.includes(name) || (window._customFragmentKeys || []).includes(name)) {
    window.showToast("该碎片模块已存在", "warn");
    return;
  }
  window._customFragmentKeys = window._customFragmentKeys || [];
  window._customFragmentKeys.push(name);
  window.renderFragmentEditor(collectFragmentValues());
  const nta = document.getElementById(`f_frag_${name}`);
  if (nta) nta.focus();
};

window.removeCustomFragment = function (idx) {
  if (!window._customFragmentKeys || idx < 0 || idx >= window._customFragmentKeys.length) return;
  const removed = window._customFragmentKeys.splice(idx, 1)[0];
  const fragments = collectFragmentValues();
  delete fragments[removed];
  window.renderFragmentEditor(fragments);
};

function parsePromptFragments(text) {
  if (!text) return {};
  const result = {};
  const pattern = /【([^】]+)】\s*(.*?)(?=【|$)/gs;
  let m;
  while ((m = pattern.exec(text)) !== null) {
    result[m[1].trim()] = m[2].trim();
  }
  return result;
}

// 碎片 textarea 随内容弹性增长高度（不限定最大高度）
window._autoResizeFrag = function (textarea) {
  if (!textarea) return;
  textarea.style.height = 'auto';
  textarea.style.height = textarea.scrollHeight + 'px';
};

window._markFragmentChanged = function(textarea) {
  const key = textarea.dataset.fragkey;
  const dot = document.getElementById(`frag_dot_${key}`);
  const field = document.getElementById(`frag_field_${key}`);
  if (!dot || !field) return;
  const changed = textarea.value !== (textarea.dataset.original || "");
  dot.style.display = changed ? "inline" : "none";
  field.style.borderLeft = changed ? "3px solid #f59e0b" : "";
};

function reassemblePrompt(fragments) {
  const parts = [];
  for (const key of allFragmentKeys()) {
    if (fragments[key]) {
      parts.push(`【${key}】${fragments[key]}`);
    }
  }
  return parts.join("\n\n");
}

// 在「已含【】标记 + 后方还有扁平文字」的混合场景下，精确拆分：
// 以空行切块（与 reassemblePrompt 的分隔一致），块首为【类型】即视为标记碎片，
// 其余块保留为未标记文字交给智能分段。避免用跨换行的惰性正则（V8 存在 group 异常）。
function _segmentParse(text) {
  const marked = {};
  const leftoverBlocks = [];
  const blocks = (text || "").split(/\n\s*\n/);
  for (const blk of blocks) {
    const m = blk.match(/^\s*【([^】]+)】\s*([\s\S]*)$/);
    if (m) {
      marked[m[1].trim()] = (m[2] || "").trim();
    } else if (blk.trim()) {
      leftoverBlocks.push(blk.trim());
    }
  }
  const leftover = leftoverBlocks.join("\n\n").trim();
  return { marked, leftover };
}

// ===================================================================
// 智能分段（方案 A）：把扁平/AI 润色返回的提示词按关键词映射为碎片格式
// 纯前端规则，零依赖；准确率中等，未识别内容归入【其他】且不丢失。
// ===================================================================

// 八大碎片类型的关键词词典（中英文），用于规则匹配
window.FRAGMENT_SEGMENT_DICT = {
  "拍摄视角": ["close-up","close up","portrait","full body","fullbody","upper body","lower body","from side","from above","from below","low angle","high angle","cowboy shot","wide shot","extreme close","pov","selfie","dutch angle","birds eye","top-down","aerial","视角","特写","半身","全身","侧身","俯视","仰视","远景","近景","自拍","广角","鱼眼","第一人称"],
  "人物身材": ["tall","slender","slim","petite","curvy","muscular","flat chest","small chest","big breasts","large breasts","wide hips","long legs","short stature","athletic","chubby","身材","高挑","苗条","纤细","丰满","微胖","肌肉","巨乳","贫乳","长腿","小蛮腰","体型","胸部"],
  "人物服饰": ["dress","shirt","skirt","jacket","coat","sweater","gown","kimono","uniform","bikini","suit","hoodie","tshirt","t-shirt","pants","shorts","jeans","boots","hat","crown","ribbon","headband","glasses","scarf","armor","robe","maid","sailor","wedding","服饰","连衣裙","裙子","上衣","外套","毛衣","和服","制服","衬衫","短裤","裤子","牛仔裤","靴子","帽子","皇冠","丝带","发箍","眼镜","围巾","盔甲","长袍","女仆","水手服","婚纱","鞋子","袜子"],
  "人物面部": ["blue eyes","green eyes","red eyes","brown eyes","black eyes","golden eyes","heterochromia","blonde hair","red hair","black hair","white hair","silver hair","pink hair","blue hair","purple hair","long hair","short hair","medium hair","twintails","twin tails","ponytail","braid","bob cut","curly hair","facial","face","eyes","hair","双眸","蓝眼","绿眼","红眼","棕眼","黑眼","金眼","异色瞳","金发","红发","黑发","白发","银发","粉发","蓝发","紫发","长发","短发","中发","双马尾","单马尾","麻花辫","波波头","卷发","面容","五官","大眼睛","可爱","清纯","脸","瞳"],
  "姿态动作": ["standing","sitting","lying","laying","sleeping","jumping","running","walking","waving","smiling","laughing","crying","looking at viewer","looking back","looking at camera","arms up","hands on hips","pointing","holding","leaning","kneeling","squatting","stretching","dancing","winking","blush","pose","姿态","站立","坐着","躺","睡","跳","跑","走","挥手","微笑","大笑","哭","回头","比心","叉腰","指","抱","靠","跪","蹲","伸展","跳舞","眨眼","害羞","动作"],
  "场景环境": ["outdoors","indoors","forest","city","beach","room","garden","school","cafe","street","park","mountain","sky","ocean","water","flower","cherry blossoms","sakura","library","temple","playground","pool","bedroom","office","scene","background","scenery","户外","室内","森林","城市","海边","房间","花园","校园","咖啡馆","街道","公园","山","天空","海洋","水","花","樱花","图书馆","神社","操场","泳池","卧室","办公室","背景","场景","草地","夜景","雨天","雪"],
  "光影色调": ["sunny","sunlight","soft light","cinematic lighting","rim light","backlight","back light","volumetric light","studio light","moonlight","glow","lens flare","ambient","shadows","dramatic lighting","warm tone","cool tone","dim","bright","光影","阳光","柔光","逆光","轮廓光","体积光","影棚光","月光","辉光","暖色调","冷色调","暗调","明亮","光线","打光","光晕","氛围光"],
  "画风技术": ["anime","realistic","real life","illustration","masterpiece","best quality","high quality","3d","cg","oil painting","watercolor","cel shading","flat color","sketch","digital art","render","niji","noobai","contrast","saturation","sharp focus","detailed","ultra-detailed","8k","4k","hdr","画风","动漫","写实","真人","插画","杰作","最佳质量","高清","厚涂","赛璐璐","二次元","水彩","油画","素描","3d","cg","对比度","饱和度","锐焦","精细","细节","风格"],
};

// 多匹配时的优先顺序（越靠前越具体，优先收纳）
const _SEG_PRIORITY = ["人物面部","人物服饰","人物身材","姿态动作","场景环境","光影色调","拍摄视角","画风技术"];

// 把扁平文本按关键词拆分为碎片对象
window.smartSegmentText = function (text) {
  if (!text) return {};
  const dict = window.FRAGMENT_SEGMENT_DICT;
  const buckets = {};
  _SEG_PRIORITY.forEach(k => buckets[k] = []);
  const other = [];
  // 分词：按换行 / 中英文逗号、顿号、分号切分，覆盖 SD 提示词与中文描述
  const tokens = text
    .split(/\r?\n|，|、|；|;|,/)
    .map(t => t.trim())
    .filter(t => t && !/^[\s，,、；;。.]+$/.test(t));
  const lowerDict = {};
  _SEG_PRIORITY.forEach(k => lowerDict[k] = dict[k].map(s => s.toLowerCase()));
  for (const raw of tokens) {
    const low = raw.toLowerCase();
    let matched = null;
    for (const k of _SEG_PRIORITY) {
      if (lowerDict[k].some(kw => low.includes(kw))) { matched = k; break; }
    }
    if (matched) buckets[matched].push(raw);
    else other.push(raw);
  }
  const hasCJK = s => /[一-龥]/.test(s);
  const result = {};
  for (const k of _SEG_PRIORITY) {
    if (buckets[k].length) {
      result[k] = buckets[k].join(hasCJK(buckets[k].join("")) ? "，" : ", ");
    }
  }
  if (other.length) result["其他"] = other.join(hasCJK(other.join("")) ? "，" : ", ");
  return result;
};

// 编辑弹窗内的「🪄 智能分段」按钮
window.smartSegment = function () {
  const ta = document.getElementById("f_prompt");
  if (!ta) return;
  const text = (ta.value || "").trim();
  if (!text) { window.showToast("正面提示词为空", "warn"); return; }
  // 已带【】标记的碎片优先保留，只对未标记部分做智能分段
  const { marked, leftover } = _segmentParse(text);
  const seg = window.smartSegmentText(leftover);
  const fragments = Object.assign({}, marked, seg);
  if (Object.keys(fragments).length === 0) {
    window.showToast("未能识别任何碎片，请手动分段", "warn");
    return;
  }
  // 切换进分段编辑模式并渲染
  window._fragmentEditMode = true;
  window._customFragmentKeys = (window._customFragmentKeys || []).filter(k => FRAGMENT_KEYS.includes(k));
  for (const k of Object.keys(fragments)) {
    if (!FRAGMENT_KEYS.includes(k) && !window._customFragmentKeys.includes(k)) {
      window._customFragmentKeys.push(k);
    }
  }
  window.renderFragmentEditor(fragments);
  ta.style.display = "none";
  const fc = document.getElementById("f_fragments");
  if (fc) fc.style.display = "";
  const btn = document.getElementById("f_toggleFragBtn");
  if (btn) { btn.style.display = ""; btn.textContent = "📝 切换分段/全文编辑"; }
  const otherN = fragments["其他"] ? fragments["其他"].split(/[,，]/).length : 0;
  window.showToast(
    `智能分段完成：${Object.keys(fragments).length} 个碎片` +
    (fragments["其他"] ? `，${otherN} 项归入【其他】待手动整理` : ""),
    "success"
  );
};

// ===================================================================
// 批量导入（方案 C）：粘贴 AI 返回的一大堆提示词，自动分段后逐条入库
// ===================================================================

window._importItems = [];  // { name, prompt, negative_prompt, selected }

window.openImportModal = function () {
  const t = document.getElementById("importText");
  if (t) t.value = "";
  const pv = document.getElementById("importPreview");
  if (pv) pv.innerHTML = "";
  const st = document.getElementById("importParseStat");
  if (st) st.textContent = "";
  const sb = document.getElementById("importSubmitBtn");
  if (sb) sb.disabled = true;
  const sa = document.getElementById("importSelectAll");
  if (sa) sa.checked = true;
  window._importItems = [];
  const ov = document.getElementById("importModalOverlay");
  if (ov) ov.classList.add("active");
};

window.closeImportModal = function () {
  const ov = document.getElementById("importModalOverlay");
  if (ov) ov.classList.remove("active");
};

window.parseImportText = function () {
  const raw = (document.getElementById("importText").value || "");
  const blocks = raw.split(/\n\s*\n+/).map(b => b.trim()).filter(Boolean);
  if (blocks.length === 0) { window.showToast("没有可解析的内容", "warn"); return; }
  const items = [];
  for (const blk of blocks) {
    let name = "";
    let neg = "";
    const lines = blk.split(/\r?\n/);
    const first = lines[0] || "";
    const nm = first.match(/^(名称|name|标题)\s*[:：]\s*(.+)$/i);
    let bodyLines = lines;
    if (nm) { name = nm[2].trim(); bodyLines = lines.slice(1); }
    const posLines = [];
    for (const ln of bodyLines) {
      const ngm = ln.match(/^(negative|负面|反向)\s*[:：]\s*(.*)$/i);
      if (ngm) { neg = (neg ? neg + ", " : "") + ngm[2].trim(); }
      else posLines.push(ln);
    }
    const body = posLines.join("\n").trim();
    // 已含【】标记则用原文解析，否则智能分段
    const { marked, leftover } = _segmentParse(body);
    const seg = window.smartSegmentText(leftover);
    let finalFrags = Object.assign({}, marked, seg);
    if (Object.keys(finalFrags).length === 0) finalFrags = { "其他": body };
    const segText = reassemblePrompt(finalFrags);
    items.push({
      name: name || ("未命名 " + (items.length + 1)),
      prompt: segText,
      negative_prompt: neg,
      selected: true,
    });
  }
  window._importItems = items;
  window.renderImportPreview();
  const st = document.getElementById("importParseStat");
  if (st) st.textContent = `共解析 ${items.length} 条，已自动分段为碎片格式`;
  const sb = document.getElementById("importSubmitBtn");
  if (sb) sb.disabled = items.length === 0;
  window.showToast(`解析完成 ${items.length} 条`, "success");
};

window.renderImportPreview = function () {
  const box = document.getElementById("importPreview");
  if (!box) return;
  if (!window._importItems.length) { box.innerHTML = '<div class="empty-tip">暂无解析结果</div>'; return; }
  box.innerHTML = window._importItems.map((it, i) => {
    const fragCount = (it.prompt.match(/【[^】]+】/g) || []).length;
    return `<div class="import-card">
      <div class="import-card-head">
        <label class="sel-check"><input type="checkbox" ${it.selected ? "checked" : ""} onchange="window._importItems[${i}].selected=this.checked;document.getElementById('importSubmitBtn').disabled=!window._importItems.some(x=>x.selected)"></label>
        <input class="import-name-input" value="${window.escAttr(it.name)}" oninput="window._importItems[${i}].name=this.value">
        <span class="import-frag-count">${fragCount} 碎片</span>
      </div>
      <div class="import-card-body">${window.escHtml(it.prompt)}</div>
      ${it.negative_prompt ? `<div class="import-card-neg">负面：${window.escHtml(it.negative_prompt)}</div>` : ""}
    </div>`;
  }).join("");
};

window.toggleImportSelectAll = function (checked) {
  window._importItems.forEach(it => it.selected = checked);
  window.renderImportPreview();
  const sb = document.getElementById("importSubmitBtn");
  if (sb) sb.disabled = !checked;
};

window.doBatchImport = async function () {
  const sel = window._importItems.filter(it => it.selected);
  if (!sel.length) { window.showToast("请至少选择一条", "warn"); return; }
  const btn = document.getElementById("importSubmitBtn");
  if (btn) btn.disabled = true;
  try {
    const payload = sel.map(it => ({
      name: it.name || "",
      prompt: it.prompt,
      negative_prompt: it.negative_prompt || "",
    }));
    const resp = await window.api("/api/prompts/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompts: payload }),
    });
    if (resp && resp.success) {
      window.showToast(resp.message || `已导入 ${resp.imported} 条`, "success");
      window.closeImportModal();
      window.loadPrompts();
      window.loadCategories();
    } else {
      window.showToast((resp && resp.error) || "导入失败", "error");
    }
  } catch (e) {
    window.showToast("导入失败: " + e.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
};

window.toggleFragmentEdit = function () {
  window._fragmentEditMode = !window._fragmentEditMode;
  const textarea = document.getElementById("f_prompt");
  const fragContainer = document.getElementById("f_fragments");
  const btn = document.getElementById("f_toggleFragBtn");
  if (!textarea || !fragContainer || !btn) return;

  if (window._fragmentEditMode) {
    // 从 textarea 同步到碎片（含自动识别的自定义标题）
    const fragments = parsePromptFragments(textarea.value);
    window._customFragmentKeys = (window._customFragmentKeys || []).filter(k => FRAGMENT_KEYS.includes(k));
    for (const k of Object.keys(fragments)) {
      if (!FRAGMENT_KEYS.includes(k) && !window._customFragmentKeys.includes(k)) {
        window._customFragmentKeys.push(k);
      }
    }
    window.renderFragmentEditor(fragments);
  } else {
    // 从碎片同步到 textarea
    const fragments = collectFragmentValues();
    textarea.value = reassemblePrompt(fragments);
    textarea.style.display = "";
    fragContainer.style.display = "none";
    btn.textContent = "📝 切换到分段编辑";
  }
};

// -------------------------------------------------------------------
// 提示词 CRUD
// -------------------------------------------------------------------

window.setRating = function(rating) {
  document.getElementById("f_rating_value").value = rating;
  const stars = document.querySelectorAll("#f_rating .rating-star-input");
  stars.forEach((star, idx) => {
    star.classList.toggle("active", idx < rating);
  });
};

// 记录弹窗打开时的原始表单状态（JSON 字符串，最简单可靠的比对方式）
window._promptFormSnapshot = null;

window._promptGetFormState = function() {
  const ids = ["f_name","f_prompt","f_neg","f_steps","f_cfg","f_sampler","f_seed","f_model","f_tags","f_note","f_rating_value"];
  const state = {};
  for (const id of ids) {
    const el = document.getElementById(id);
    state[id] = el ? (el.value || "").trim() : "";
  }
  // 分段编辑模式下也要读碎片 textarea 的值（含自定义碎片）
  if (window._fragmentEditMode) {
    for (const key of allFragmentKeys()) {
      const ta = document.getElementById(`f_frag_${key}`);
      state[`frag_${key}`] = ta ? (ta.value || "").trim() : "";
    }
  }
  return JSON.stringify(state);
};

window._promptHasChanges = function() {
  if (!window._promptFormSnapshot) return false;
  return window._promptGetFormState() !== window._promptFormSnapshot;
};

// ===================================================================
// 草稿系统 —— sessionStorage 自动保存，页面刷新/崩溃后可恢复
// ===================================================================

window._DRAFT_FIELDS = ["f_name","f_prompt","f_neg","f_steps","f_cfg","f_sampler","f_seed","f_model","f_tags","f_note","f_rating_value"];

window._draftKey = function(id) { return `pb_draft_${id || "new"}`; };

window._saveDraft = function() {
  const id = document.getElementById("f_id").value || "new";
  const draft = {};
  for (const fid of window._DRAFT_FIELDS) {
    const el = document.getElementById(fid);
    if (el) draft[fid] = el.value;
  }
  draft._savedAt = Date.now();
  try { sessionStorage.setItem(window._draftKey(id), JSON.stringify(draft)); } catch (_) {}
};

window._loadDraft = function(id) {
  try {
    const raw = sessionStorage.getItem(window._draftKey(id || "new"));
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
};

window._clearDraft = function(id) {
  try { sessionStorage.removeItem(window._draftKey(id || "new")); } catch (_) {}
};

window._startAutoSaveDraft = function() {
  let timer = null;
  const handler = () => {
    clearTimeout(timer);
    timer = setTimeout(() => window._saveDraft(), 1500);  // 1.5 秒防抖
  };
  const body = document.getElementById("modalBody");
  if (!body || body.dataset.draftListener) return;
  body.dataset.draftListener = "1";
  body.addEventListener("input", handler);
  body.addEventListener("change", handler);
};

// 页面刷新/关闭前提醒（弹窗打开且有未保存/试跑记录时）
window.addEventListener("beforeunload", (e) => {
  const modal = document.getElementById("modalOverlay");
  if (!modal || !modal.classList.contains("active")) return;
  const hasChanges = window._promptHasChanges();
  const hasTrials = window._trialRuns && window._trialRuns.length > 0;
  if (hasChanges || hasTrials) {
    e.preventDefault();
    e.returnValue = "";
  }
});

// ===================================================================
// 编辑弹窗
// ===================================================================

window.openEditModal = async function(id) {
  // 检查草稿（在清空字段之前）
  const existingId = id;  // null = new, number = edit
  if (existingId != null) {
    const draft = window._loadDraft(existingId);
    if (draft) {
      const t = new Date(draft._savedAt);
      const when = `${t.getMonth()+1}/${t.getDate()} ${t.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit"})}`;
      const restore = confirm(`检测到 ${when} 的未保存草稿，是否恢复？\n（选择"取消"将丢弃草稿）`);
      if (restore) {
        document.getElementById("f_id").value = existingId;
        for (const fid of window._DRAFT_FIELDS) {
          const el = document.getElementById(fid);
          if (el && draft[fid] !== undefined) el.value = draft[fid];
        }
        if (draft.f_rating_value) window.setRating(parseInt(draft.f_rating_value) || 0);
        document.getElementById("modalTitle").textContent = `编辑提示词 #${existingId}`;
        document.getElementById("trialRunBtn").style.display = "";
        await window.loadCategoriesForSelect();
        await window.loadTagsForSelect();
        window._promptFormSnapshot = window._promptGetFormState();
        document.getElementById("modalOverlay").classList.add("active");
        window._startAutoSaveDraft();
        return;  // 草稿恢复完成，不走下面加载 DB 的逻辑
      } else {
        window._clearDraft(existingId);
      }
    }
  }

  window._fragmentEditMode = false;
  window._promptFormSnapshot = null;
  window._customFragmentKeys = [];

  // ---- 新建模式 ----
  if (id == null) {
    let draftRestored = false;
    const draft = window._loadDraft("new");
    if (draft) {
      const t = new Date(draft._savedAt);
      const when = `${t.getMonth()+1}/${t.getDate()} ${t.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit"})}`;
      if (confirm(`检测到 ${when} 的未完成新建草稿，是否恢复？`)) {
        for (const fid of window._DRAFT_FIELDS) {
          const el = document.getElementById(fid);
          if (el && draft[fid] !== undefined) el.value = draft[fid];
        }
        if (draft.f_rating_value) window.setRating(parseInt(draft.f_rating_value) || 0);
        draftRestored = true;
      }
    }
    document.getElementById("modalTitle").textContent = "新建提示词";
    document.getElementById("f_id").value = "";
    document.getElementById("trialRunBtn").style.display = "none";
    if (!draftRestored) {
      ["f_name", "f_prompt", "f_neg", "f_steps", "f_cfg", "f_sampler", "f_seed", "f_model", "f_tags", "f_note"].forEach(fid => document.getElementById(fid).value = "");
      window.setRating(0);
    }
    window.renderFragmentEditor({});
    await window.loadCategoriesForSelect();
    await window.loadTagsForSelect();
    document.getElementById("modalOverlay").classList.add("active");
    window._startAutoSaveDraft();
    return;
  }

  // ---- 编辑模式 ----
  document.getElementById("f_id").value = id;
  try {
    const p = await window.api(`/api/prompts/${id}`);
    document.getElementById("modalTitle").textContent = p.name ? `编辑：${p.name}` : `编辑提示词 #${id}`;
    document.getElementById("f_name").value = p.name || "";
    document.getElementById("f_prompt").value = p.prompt || "";
    document.getElementById("f_neg").value = p.negative_prompt || "";

    // 设置分段编辑器（固定八大碎片 + 自动识别的自定义碎片）
    const fragments = parsePromptFragments(p.prompt || "");
    const hasFrags = Object.keys(fragments).length > 0;
    const fragContainer = document.getElementById("f_fragments");

    if (fragContainer && hasFrags) {
      // 收集自定义碎片标题（prompt 中含【非固定名】的）
      window._customFragmentKeys = [];
      for (const k of Object.keys(fragments)) {
        if (!FRAGMENT_KEYS.includes(k) && !window._customFragmentKeys.includes(k)) {
          window._customFragmentKeys.push(k);
        }
      }
      window.renderFragmentEditor(fragments);
    } else if (fragContainer) {
      // 无碎片的旧 prompt 保留全文编辑，但显示切换按钮（不丢内容）
      fragContainer.style.display = "none";
      const ta = document.getElementById("f_prompt");
      const btn = document.getElementById("f_toggleFragBtn");
      if (ta) ta.style.display = "";
      if (btn) { btn.style.display = ""; btn.textContent = "📝 切换到分段编辑"; }
    }
    document.getElementById("f_steps").value = p.steps || "";
    document.getElementById("f_cfg").value = p.cfg_scale || "";
    document.getElementById("f_sampler").value = p.sampler || "";
    document.getElementById("f_seed").value = p.seed || "";
    document.getElementById("f_model").value = p.model || "";
    document.getElementById("f_tags").value = p.tags || "";
    document.getElementById("f_note").value = p.note || "";
    window.setRating(p.rating || 0);

    const categories = p.categories || [];
    const catId = categories.length > 0 ? categories[0].id : null;
    const tagsDetail = p.tags_detail || [];
    const tagIds = tagsDetail.map(t => t.id);

    await window.loadCategoriesForSelect(catId);
    await window.loadTagsForSelect(tagIds);

    window._promptFormSnapshot = window._promptGetFormState();
    document.getElementById("trialRunBtn").style.display = "";  // 编辑模式下显示试跑按钮
    document.getElementById("modalOverlay").classList.add("active");
    window._startAutoSaveDraft();
  } catch (e) {
    window.showToast("加载失败: " + e.message, "error");
  }
};

window.closePromptModal = function(force = false) {
  if (!force && window._trialRuns && window._trialRuns.length > 0) {
    if (!confirm(`有 ${window._trialRuns.length} 条试跑记录，关闭后无法恢复，确定吗？`)) return false;
  }
  if (!force && window._promptFormSnapshot && window._promptHasChanges()) {
    if (!confirm("有未保存的修改，确定关闭？")) return false;
  }
  document.getElementById("modalOverlay").classList.remove("active");
  window._fragmentEditMode = false;
  window._customFragmentKeys = [];
  window._promptFormSnapshot = null;
  window._clearTrialLog();  // 清空试跑记录
  // 还原 textarea 显示
  const ta = document.getElementById("f_prompt");
  const fc = document.getElementById("f_fragments");
  const btn = document.getElementById("f_toggleFragBtn");
  if (ta) ta.style.display = "";
  if (fc) fc.style.display = "none";
  if (btn) btn.style.display = "none";
  return true;
};

// 通用关闭弹窗（提示词编辑 > 动态弹窗 > 其他）
window.closeModal = function(force = false) {
  // 提示词编辑弹窗（带未保存确认）
  const modalOverlay = document.getElementById("modalOverlay");
  if (modalOverlay && modalOverlay.classList.contains("active")) {
    if (!force) {
      const wasClosed = window.closePromptModal();
      if (wasClosed === false) return;
    } else {
      window.closePromptModal(true);
    }
    return;
  }
  // 动态弹窗（自定义碎片、另存为等）
  if (window._closeDynamicModal) window._closeDynamicModal();
};

window.savePrompt = async function() {
  return window.withLock("savePrompt", async () => {
    const saveBtn = document.getElementById("modalSaveBtn");
    if (saveBtn) saveBtn.disabled = true;
    // 如果处于分段编辑模式，从碎片重新组装
    let promptValue;
    if (window._fragmentEditMode) {
      const frags = collectFragmentValues();
      promptValue = reassemblePrompt(frags);
    } else {
      promptValue = document.getElementById("f_prompt").value;
    }

    const data = {
      name: document.getElementById("f_name").value,
      prompt: promptValue,
      negative_prompt: document.getElementById("f_neg").value,
      steps: parseInt(document.getElementById("f_steps").value) || null,
      cfg_scale: parseFloat(document.getElementById("f_cfg").value) || null,
      sampler: document.getElementById("f_sampler").value,
      seed: parseInt(document.getElementById("f_seed").value) || null,
      model: document.getElementById("f_model").value,
      tags: document.getElementById("f_tags").value,
      note: document.getElementById("f_note").value,
      rating: parseInt(document.getElementById("f_rating_value").value) || null,
    };
    const id = document.getElementById("f_id").value;
    const isEdit = !!id;
    try {
      const resp = isEdit
        ? await window.api(`/api/prompts/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
        : await window.api("/api/prompts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
      if (resp.success) {
        const promptId = isEdit ? parseInt(id) : resp.id;
        if (promptId) {
          await window.savePromptCategories(promptId, isEdit);
          await window.savePromptTags(promptId, isEdit);
        }
        const isComposerSave = document.getElementById("modalTitle").textContent.includes("另存为");
        window.showToast(isEdit ? "已更新" : "已创建", "success");
        window._clearDraft(id || "new");  // 保存成功，清掉草稿
        window.closePromptModal(true);  // force close，跳过未保存确认
        window.loadTags();
        window.loadCategories();
        window.loadPrompts();
        if (isEdit) window.selectPrompt(parseInt(id));
        // 从组合创作另存后自动跳转到提示词 tab
        if (isComposerSave) {
          const btn = document.querySelector('.tab-btn[data-tab="promptTab"]');
          if (btn) {
            window.switchTab("promptTab", btn);
            setTimeout(() => {
              window._promptPage = 1;
              window._pendingCategoryFilter = "组合创作";
              window.loadPrompts();
            }, 200);
          }
        }
      } else {
        window.showToast(resp.error || "失败", "error");
      }
    } catch (e) {
      window.showToast("保存失败: " + e.message, "error");
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  });
};

window.savePromptCategories = async function(promptId, isEdit) {
  const catSelect = document.getElementById("f_category");
  const categoryId = catSelect ? catSelect.value : null;

  try {
    if (isEdit) {
      const p = await window.api(`/api/prompts/${promptId}`);
      const oldCats = p.categories || [];
      for (const cat of oldCats) {
        try {
          await window.api(`/api/categories/${cat.id}/prompts/${promptId}`, { method: "DELETE" });
        } catch (e) { }
      }
    }

    if (categoryId) {
      await window.api(`/api/categories/${categoryId}/prompts/${promptId}`, { method: "POST" });
    }
  } catch (e) {
    console.error("保存分类关联失败:", e);
  }
};

window.savePromptTags = async function(promptId, isEdit) {
  const selectedTags = [];
  document.querySelectorAll("#f_tags_select .tag-option.selected").forEach(el => {
    selectedTags.push(parseInt(el.dataset.tagId));
  });

  try {
    if (isEdit) {
      const p = await window.api(`/api/prompts/${promptId}`);
      const oldTags = p.tags_detail || [];
      for (const tag of oldTags) {
        try {
          await window.api(`/api/tags/${tag.id}/prompts/${promptId}`, { method: "DELETE" });
        } catch (e) { }
      }
    }

    for (const tagId of selectedTags) {
      try {
        await window.api(`/api/tags/${tagId}/prompts/${promptId}`, { method: "POST" });
      } catch (e) { }
    }
  } catch (e) {
    console.error("保存标签关联失败:", e);
  }
};

window.deletePrompt = async function(id) {
  if (!confirm("确定删除提示词 #" + id + " 吗？")) return;
  return window.withLock("deletePrompt", async () => {
    try {
      const r = await window.api(`/api/prompts/${id}`, { method: "DELETE" });
      if (r.success) {
        window.showToast("已删除", "success");
        if (window.selectedId === id) {
          window.selectedId = null;
          window.UiState.set("selectedId", null);
          document.getElementById("detailPanel").innerHTML = '<div class="placeholder">← 从左侧选择一个提示词</div>';
        }
        window.loadTags();
        window.loadPrompts();
        window.updateRunBtn();
      } else {
        window.showToast(r.error || "删除失败", "error");
      }
    } catch (e) {
      window.showToast("删除失败: " + e.message, "error");
    }
  });
};

// -------------------------------------------------------------------
// 提示词：收藏/置顶/评级
// -------------------------------------------------------------------

window.togglePromptFavorite = async function(promptId, btnElement) {
  try {
    const r = await window.api(`/api/prompts/${promptId}/favorite`, { method: "POST" });
    if (r.success) {
      window.showToast(r.is_favorite ? '已收藏' : '已取消收藏', 'info');
      if (window.selectedId === promptId && window._currentPromptData) {
        window._currentPromptData.is_favorite = r.is_favorite;
        const favBtn = document.getElementById('detailFavBtn');
        if (favBtn) {
          favBtn.classList.toggle('active', r.is_favorite);
          favBtn.textContent = r.is_favorite ? '★' : '☆';
        }
      }
      window.loadPrompts();
    }
  } catch (e) {
    window.showToast("操作失败: " + e.message, "error");
  }
};

window.togglePromptPin = async function(promptId, btnElement) {
  try {
    const r = await window.api(`/api/prompts/${promptId}/pin`, { method: "POST" });
    if (r.success) {
      window.showToast(r.is_pinned ? '已置顶' : '已取消置顶', 'info');
      window.loadPrompts();
    }
  } catch (e) {
    window.showToast("操作失败: " + e.message, "error");
  }
};

window.ratePrompt = async function(promptId, rating) {
  try {
    const r = await window.api(`/api/prompts/${promptId}/rate?rating=${rating}`, { method: "POST" });
    if (r.success) {
      window.showToast(`已设置为 ${rating} 星`, 'success');
      if (window.selectedId === promptId && window._currentPromptData) {
        window._currentPromptData.rating = r.rating;
      }
      window.loadPrompts();
    }
  } catch (e) {
    window.showToast("操作失败: " + e.message, "error");
  }
};

window.markPromptUsed = async function(promptId) {
  try {
    await window.api(`/api/prompts/${promptId}/use`, { method: "POST" });
    if (window.selectedId === promptId && window._currentPromptData) {
      window._currentPromptData.usage_count = (window._currentPromptData.usage_count || 0) + 1;
      window._currentPromptData.last_used_at = new Date().toISOString();
    }
  } catch (e) {
    console.error("markPromptUsed failed:", e);
  }
};

// -------------------------------------------------------------------
// 提示词：搜索/标签
// -------------------------------------------------------------------

window.loadTags = async function() {
  try {
    const data = await window.api("/api/tags");
    const sel = document.getElementById("tagFilter");
    const cur = sel.value;
    sel.innerHTML = '<option value="">全部标签</option>';
    (data.tags || []).forEach(t => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });
    sel.value = cur || window.UiState.get("tag", "");
  } catch (_) {}
};

window.onTagChange = function() {
  window._promptPage = 1;
  window.UiState.set("tag", document.getElementById("tagFilter").value);
  window.loadPrompts();
};

window.debounceSearch = function() {
  clearTimeout(window.searchTimer);
  window.searchTimer = setTimeout(() => {
    window._promptPage = 1;
    window.UiState.set("search", document.getElementById("searchInput").value);
    window.loadPrompts();
  }, 300);
};

window.copyPromptText = function(btn, type) {
  if (!window._currentPromptData) return;
  let text = type === 0 ? (window._currentPromptData.prompt || "") : (window._currentPromptData.negative_prompt || "");
  // 正面提示词复制时去掉【】碎片标题
  if (type === 0) text = text.replace(/【[^】]+】\s*/g, '');
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "已复制";
    setTimeout(() => btn.textContent = "复制", 1500);
  }, () => window.showToast("复制失败", "error"));
};

// 新增/编辑弹窗内的一键复制：读取当前编辑区内容（分段模式下从碎片组装），复制时剥离【】标题
window.copyModalPrompt = async function (btn, type) {
  let text;
  if (type === 0) {
    text = window._fragmentEditMode
      ? reassemblePrompt(collectFragmentValues())
      : (document.getElementById("f_prompt").value || "");
    text = text.replace(/【[^】]+】\s*/g, '');
  } else {
    text = document.getElementById("f_neg").value || "";
  }
  if (!text.trim()) { window.showToast("提示词为空", "warn"); return; }
  try {
    await navigator.clipboard.writeText(text);
    const orig = btn.textContent;
    btn.textContent = "已复制";
    setTimeout(() => { btn.textContent = orig; }, 1500);
  } catch (e) {
    window.showToast("复制失败", "error");
  }
};

// -------------------------------------------------------------------
// 提示词：分类和标签（Phase 2）
// -------------------------------------------------------------------

// window.loadCategories 由 category.js 定义，此处不重复声明
// window._currentCategoryId 由 category.js 声明
// window._selectedTags 由 tag.js 声明

// 加载分类列表到新建/编辑模态框的下拉框（f_category）
// 复用 category.js 中的共享函数 window.renderCategorySelect
window.loadCategoriesForSelect = async function(selectedCatId) {
  await window.renderCategorySelect("f_category", selectedCatId || "");
};

// 加载标签列表到新建/编辑模态框的多选区（f_tags_select）
// 复用 tag.js 中的共享函数 window.renderTagCheckboxes
window.loadTagsForSelect = async function(selectedTagIds) {
  await window.renderTagCheckboxes("f_tags_select", selectedTagIds || []);
  // 每次打开弹窗都重置标签区为展开态（清除上次的折叠/内联高度）
  const field = document.getElementById("tagsSelectBody")?.closest(".collapsible-field");
  if (field) {
    field.classList.remove("collapsed");
    const body = document.getElementById("tagsSelectBody");
    if (body) body.style.maxHeight = "none";
  }
};

// 编辑弹窗「标签（多选）」区域折叠/展开，节省空间
window.toggleTagsSelect = function () {
  const field = document.getElementById("tagsSelectBody")?.closest(".collapsible-field");
  if (!field) return;
  const body = document.getElementById("tagsSelectBody");
  const collapsed = field.classList.toggle("collapsed");
  if (collapsed) {
    // 折叠：先把当前高度固定为数值，再在下一帧设为 0 触发过渡
    body.style.maxHeight = body.scrollHeight + "px";
    requestAnimationFrame(() => { body.style.maxHeight = "0px"; });
  } else {
    // 展开：从 0 过渡到内容高度，结束后置 none 以支持动态内容
    body.style.maxHeight = body.scrollHeight + "px";
    setTimeout(() => { body.style.maxHeight = "none"; }, 220);
  }
};

// ====================================================================
// 新增：导入/导出 + 批量操作
// ====================================================================

/** 导出提示词为 JSON 文件 */
window.exportPrompts = async function() {
  try {
    const blob = await window.apiBlob("/api/prompts/export");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `prompts_export_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    window.showToast("导出成功", "info");
  } catch (e) {
    window.showToast("导出失败: " + e.message, "error");
  }
};

/** 导入提示词 JSON 文件 */
window.importPrompts = async function(fileInput) {
  const file = fileInput.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    const prompts = data.prompts;
    if (!Array.isArray(prompts)) {
      window.showToast("无效的导入格式", "error");
      return;
    }
    const resp = await window.api("/api/prompts/import", {
      method: "POST",
      body: JSON.stringify({ prompts }),
      headers: { "Content-Type": "application/json" },
    });
    window.showToast(resp.message || `导入 ${resp.imported} 条`, "info");
    window.loadPrompts();
  } catch (e) {
    window.showToast("导入失败: " + e.message, "error");
  } finally {
    fileInput.value = "";
  }
};

/** 批量删除选中的提示词 */
window.batchDeleteSelected = async function() {
  const ids = Array.from(window.selectedIds);
  if (!ids.length) { window.showToast("请先选择提示词", "warn"); return; }
  if (!confirm(`确定删除 ${ids.length} 条提示词？删除后不可恢复。`)) return;
  try {
    const resp = await window.api("/api/prompts/batch_delete", {
      method: "POST",
      body: JSON.stringify({ ids }),
      headers: { "Content-Type": "application/json" },
    });
    window.showToast(`已删除 ${resp.deleted} 条`, "info");
    window.selectedIds.clear();
    window.UiState.set("selectedIds", []);
    window.loadPrompts();
    window.updateSelectionBar();
  } catch (e) {
    window.showToast("批量删除失败: " + e.message, "error");
  }
};

/** 批量收藏选中的提示词 */
window.batchFavoriteSelected = async function() {
  const ids = Array.from(window.selectedIds);
  if (!ids.length) { window.showToast("请先选择提示词", "warn"); return; }
  try {
    const resp = await window.api("/api/prompts/batch_favorite?favorite=true", {
      method: "POST",
      body: JSON.stringify({ ids }),
      headers: { "Content-Type": "application/json" },
    });
    window.showToast(`已收藏 ${resp.updated} 条`, "info");
    window.loadPrompts();
  } catch (e) {
    window.showToast("批量收藏失败: " + e.message, "error");
  }
};

// ===================================================================
// 试跑功能 (trial run) —— 编辑弹窗内直接跑图，不保存原始提示词
// ===================================================================

window._trialRuns = [];

/** 清空当前弹窗的试跑记录 */
window._clearTrialLog = function() {
  window._trialRuns = [];
  window._trialWatchers.clear();  // 取消所有待完成的试跑回调
  window._trialFillBackup = null; // 顺带清除回填备份
  const log = document.getElementById("trialLog");
  const items = document.getElementById("trialLogItems");
  const undo = document.getElementById("undoFillBtn");
  if (log) log.style.display = "none";
  if (items) items.innerHTML = "";
  if (undo) undo.style.display = "none"; // 隐藏撤销回填按钮
};

/** 执行一次试跑 */
window.trialRun = async function() {
  // 分段编辑模式下从碎片重新组装，避免喂入未同步的旧全文提示词
  let prompt;
  if (window._fragmentEditMode) {
    const frags = collectFragmentValues();
    prompt = reassemblePrompt(frags);
  } else {
    prompt = document.getElementById("f_prompt").value;
  }
  if (!prompt.trim()) { window.showToast("提示词为空", "warn"); return; }

  const workflowPath = window.currentWorkflowPath ? window.currentWorkflowPath() : null;
  if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }

  const id = document.getElementById("f_id").value;
  const neg = document.getElementById("f_neg").value || "";
  const trialNum = window._trialRuns.length + 1;
  const trialStart = Date.now();

  const trial = { num: trialNum, start: trialStart, status: "pending", jobId: null, images: [], prompt, neg };
  window._trialRuns.push(trial);
  document.getElementById("trialLog").style.display = "";
  window.renderTrialLog();

  const btn = document.getElementById("trialRunBtn");
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ 跑图中...";

  try {
    const body = Object.assign({
      prompt: prompt,
      negative_prompt: neg,
      workflow_path: workflowPath,
      orientation: typeof window.currentOrientation === "function" ? window.currentOrientation() : (window.currentOrientation || "portrait"),
      quality: typeof window.getQuality === "function" ? window.getQuality() : "4K",
      seed: parseInt(document.getElementById("f_seed").value) || 0,
      source_prompt_id: id ? parseInt(id) : 0,
    }, typeof window.workflowExtraBody === "function" ? window.workflowExtraBody() : {});

    const data = await window.submitTask({
      endpoint: "/api/run_text",
      payload: body,
      title: "试跑中",
      errorPrefix: "试跑失败",
      onJob: (jobId) => {
        trial.jobId = jobId;
        trial.status = "running";
        window.renderTrialLog();

        // 注册完成回调（必须早于 trackJob，避免任务瞬间完成时错过事件）
        window._trialWatchers.set(jobId, (job) => {
          if (job.status === "done") {
            trial.status = "done";
            for (const item of (job.items || [])) {
              if (item.images && Array.isArray(item.images) && item.images.length > 0) {
                trial.images = item.images;
                break;
              }
            }
          } else {
            trial.status = job.status;
          }
          window.renderTrialLog();
        });
      },
    });
    if (!data) {
      trial.status = "error";
      window.renderTrialLog();
    }
  } catch (e) {
    trial.status = "error";
    window.renderTrialLog();
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
};

/** 在新标签页打开试跑结果原图 */
window.openTrialImage = function(filename, subfolder, type) {
  const url = `/api/image?filename=${encodeURIComponent(filename)}&subfolder=${encodeURIComponent(subfolder || "")}&type=${encodeURIComponent(type || "output")}`;
  window.open(url, "_blank");
};

/** 回填前的编辑器内容备份（用于撤销回填，防止误覆盖原提示词） */
window._trialFillBackup = null;

/** 用试跑版提示词回填编辑区（覆盖当前内容，不保存） */
window.fillFromTrial = function(idx) {
  const t = window._trialRuns[idx];
  if (!t || !t.prompt) return;
  const id = document.getElementById("f_id").value;
  const warn = id
    ? `若随后点击"保存"，将覆盖原提示词 #${id}。`
    : `将替换当前编辑区未保存的内容。`;
  if (!confirm(`回填将用试跑 #${t.num} 的提示词替换当前编辑区内容。\n${warn}\n\n确定继续？`)) {
    return;
  }
  // 备份当前编辑区内容，供撤销
  window._trialFillBackup = {
    prompt: document.getElementById("f_prompt").value,
    neg: document.getElementById("f_neg").value,
    name: document.getElementById("f_name").value,
    id: id,
    rating: document.getElementById("f_rating_value").value,
  };
  // 试跑提示词是扁平文本，强制切回全文编辑模式，避免分段模式吞掉回填内容
  window._fragmentEditMode = false;
  document.getElementById("f_prompt").style.display = "";
  const fc = document.getElementById("f_fragments");
  if (fc) fc.style.display = "none";
  const tg = document.getElementById("f_toggleFragBtn");
  if (tg) { tg.style.display = "none"; tg.textContent = "📝 切换分段/全文编辑"; }

  document.getElementById("f_prompt").value = t.prompt;
  document.getElementById("f_neg").value = t.neg || "";
  window._showUndoFill();
};

/** 回填后显示「撤销回填」按钮 */
window._showUndoFill = function() {
  const btn = document.getElementById("undoFillBtn");
  if (btn) btn.style.display = "";
  window.showToast("已回填试跑提示词，可点「撤销回填」恢复原内容", "info");
};

/** 撤销回填：恢复回填前的编辑器内容（含原提示词 id，避免误覆盖） */
window.undoFillFromTrial = function() {
  const b = window._trialFillBackup;
  if (!b) return;
  document.getElementById("f_prompt").value = b.prompt;
  document.getElementById("f_neg").value = b.neg;
  document.getElementById("f_name").value = b.name;
  document.getElementById("f_id").value = b.id;            // 还原原提示词 id，杜绝误覆盖
  if (b.rating) window.setRating(parseInt(b.rating) || 0);
  window._fragmentEditMode = false;
  document.getElementById("f_prompt").style.display = "";
  const fc = document.getElementById("f_fragments");
  if (fc) fc.style.display = "none";
  const tg = document.getElementById("f_toggleFragBtn");
  if (tg) { tg.style.display = "none"; tg.textContent = "📝 切换分段/全文编辑"; }
  window._trialFillBackup = null;
  const btn = document.getElementById("undoFillBtn");
  if (btn) btn.style.display = "none";
  window.showToast("已撤销回填，恢复原内容", "success");
};

/** 将试跑版提示词另存为新提示词 */
window.saveTrialAsNew = async function(idx) {
  const t = window._trialRuns[idx];
  if (!t || !t.prompt) return;
  document.getElementById("f_prompt").value = t.prompt;
  document.getElementById("f_neg").value = t.neg || "";
  document.getElementById("f_name").value = `试跑 #${t.num} ${new Date().toLocaleTimeString("zh-CN", {hour:"2-digit",minute:"2-digit"})}`;
  document.getElementById("f_id").value = "";
  document.getElementById("modalTitle").textContent = `💾 另存为：来自试跑 #${t.num}`;
  await window.savePrompt();
};

/** 刷新试跑日志区 DOM */
window.renderTrialLog = function() {
  const container = document.getElementById("trialLogItems");
  const log = document.getElementById("trialLog");
  if (!container) return;

  if (window._trialRuns.length === 0) {
    if (log) log.style.display = "none";
    return;
  }
  if (log) log.style.display = "";

  container.innerHTML = window._trialRuns.map((t, idx) => {
    const time = new Date(t.start).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    let badge = "";
    let actions = "";
    if (t.status === "pending") badge = `<span style="color:var(--warning)">⏳ 排队中</span>`;
    else if (t.status === "running") badge = `<span style="color:var(--accent)">🔄 跑图中...</span>`;
    else if (t.status === "done") {
      badge = `<span style="color:var(--success)">✓ 完成</span>`;
      if (t.images && t.images.length > 0) {
        const img = t.images[0];
        const thumbUrl = `/api/image?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || "")}&type=${encodeURIComponent(img.type || "output")}`;
        badge += ` <img src="${thumbUrl}" style="width:56px;height:56px;object-fit:cover;border-radius:4px;cursor:pointer;vertical-align:middle;border:1px solid var(--border);" onclick="window.openTrialImage('${img.filename.replace(/'/g, "\\'")}','${(img.subfolder||"").replace(/'/g, "\\'")}','${(img.type||"output").replace(/'/g, "\\'")}')" title="点击查看大图">`;
        if (t.images.length > 1) badge += ` <span style="font-size:11px;color:var(--muted)">+${t.images.length - 1}张</span>`;
      }
      actions = `<span style="margin-left:auto;display:flex;gap:3px;flex-shrink:0;">
        <button class="btn btn-ghost btn-sm" onclick="window.fillFromTrial(${idx})" title="用此版提示词覆盖编辑区" style="font-size:11px;padding:2px 6px;">📝 回填</button>
        <button class="btn btn-ghost btn-sm" onclick="window.saveTrialAsNew(${idx})" title="保存为新提示词" style="font-size:11px;padding:2px 6px;">💾 另存</button>
      </span>`;
    }
    else if (t.status === "error") badge = `<span style="color:var(--danger)">✗ 失败</span>`;
    else badge = `<span style="color:var(--muted)">${t.status}</span>`;

    return `<div style="display:flex;align-items:center;gap:6px;font-size:12px;padding:5px 8px;background:var(--bg-card);border-radius:6px;border:1px solid var(--border);">
      <span style="font-weight:bold;min-width:22px;color:var(--muted)">#${t.num}</span>
      <span style="color:var(--muted);font-size:11px;min-width:36px;">${time}</span>
      ${badge}
      ${actions}
    </div>`;
  }).join("");
};
