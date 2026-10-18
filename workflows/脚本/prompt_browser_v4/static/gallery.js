// gallery.js - 画廊模块
// 依赖：utils.js, history.js

window._gallerySelectedIds = new Set();
window._gallerySort = "newest";
window._galleryFilter = "all";
window._gallerySource = "";
window._galleryDate = "";
window._galleryModel = "";
window._galleryOrientation = "";
window._gallerySearch = "";
// Shift+点击范围选择的锚点（当前页内的 item 下标）
window._galleryLastIndex = null;

// -------------------------------------------------------------------
// 画廊渲染
// -------------------------------------------------------------------

window.renderGallery = function(items) {
  const grid = document.getElementById('galleryGrid');
  const countEl = document.getElementById('galleryCount');

  if (!items || !items.length) {
    grid.innerHTML = '<div class="empty-tip">暂无历史图片</div>';
    countEl.textContent = '0';
    return;
  }

  countEl.textContent = window._galleryTotal || items.length;
  grid.innerHTML = '';

  items.forEach((item, idx) => {
    const div = window._createGalleryItemDiv(item, idx);
    grid.appendChild(div);
  });

  window._addProcessButtonsToGallery();
  window.updateGalleryActionButtons();
  window.updateCompareButton();
  window.updateGallerySelectAllCheck();
  window.updateGalleryBulkPanel();
};

/** 画廊分页组件：复用提示词的分页渲染核心 */
window.renderGalleryPagination = function() {
  window.renderPaginationCore({
    containerId: "galleryPagination",
    total: window._galleryTotal || 0,
    page: window._galleryPage || 1,
    pageSize: window._galleryPageSize || 50,
    onPage: "window.loadGalleryPage",
    onPageSize: "window.changeGalleryPageSize",
  });
};

/** 共享：创建单个画廊 item 的 DOM 元素 */
window._createGalleryItemDiv = function(item, idx) {
  const div = document.createElement('div');
  div.className = 'gallery-item';
  div.dataset.id = item.id;
  div.dataset.index = idx;

  const thumbUrl = `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}&size=600&v=${encodeURIComponent(item.created_at || item.id)}`;

  const meta = window.buildImageMeta(item);
  const filename = item.filename || '';
  const favClass = item.favorite ? 'active' : '';
  const favChar = item.favorite ? '★' : '☆';
  const hasPrompt = item.prompt_id != null;

  // 从 prompt_params 提取组合创作的提示词
  let composerPrompt = "";
  let isRandomComposer = false;
  let promptParamsPrompt = "";
  if (item.prompt_params) {
    try {
      const pp = typeof item.prompt_params === "string" ? JSON.parse(item.prompt_params) : item.prompt_params;
      if (pp.source === "composer" && pp.prompt) composerPrompt = pp.prompt.slice(0, 80) + (pp.prompt.length > 80 ? "…" : "");
      if (pp.source === "composer_random") isRandomComposer = true;
      // 兜底：prompt_name 为空时用 prompt_params 中的提示词文本
      if (pp.prompt) promptParamsPrompt = pp.prompt;
    } catch(e) {}
  }

  let badgeTop = 8;
  const promptBadges = [];
  if (item.prompt_name) {
    promptBadges.push(`<div class="gallery-item-prompt" style="top:${badgeTop}px" onclick="event.stopPropagation();window.jumpToPrompt(${item.prompt_id})">📝 ${window.escHtml(item.prompt_name)}</div>`);
    badgeTop += 30;
  } else if (item.prompt_id && item.prompt_id > 0) {
    // prompt_name 缺失但 prompt_id 有效：用 prompt_params 中的提示词文本兜底
    const fallback = promptParamsPrompt ? promptParamsPrompt.slice(0, 40) + (promptParamsPrompt.length > 40 ? "…" : "") : `提示词 #${item.prompt_id}`;
    promptBadges.push(`<div class="gallery-item-prompt" style="top:${badgeTop}px;opacity:0.85" onclick="event.stopPropagation();window.jumpToPrompt(${item.prompt_id})">📝 ${window.escHtml(fallback)}</div>`);
    badgeTop += 30;
  }
  if (composerPrompt) {
    promptBadges.push(`<div class="gallery-item-prompt gallery-item-prompt-composer" style="top:${badgeTop}px" title="${window.escAttr(composerPrompt)}">🧩 ${window.escHtml(composerPrompt)}</div>`);
    badgeTop += 30;
  }
  if (isRandomComposer) {
    promptBadges.push(`<div class="gallery-item-prompt gallery-item-prompt-random" style="top:${badgeTop}px" onclick="event.stopPropagation();window.showRandomPromptDetail(${item.id})">🎲 随机组合</div>`);
  }

  div.innerHTML = `
    <img src="${thumbUrl}" alt=""
         onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
    <div class="gallery-item-placeholder" style="display:none;width:100%;aspect-ratio:1;background:var(--panel-2);align-items:center;justify-content:center;color:var(--muted);font-size:32px">🖼️</div>
    <button class="gallery-item-fav ${favClass}" onclick="event.stopPropagation();window.toggleFavorite(${item.id},this)" title="收藏">${favChar}</button>
    ${promptBadges.join('')}
    <div class="gallery-item-check" data-id="${item.id}"></div>
    <div class="gallery-item-actions"></div>
    <div class="gallery-item-meta">${meta}</div>
    <div class="gallery-item-filename" title="点击复制文件名" data-filename="${window.escAttr(filename)}">${window.escHtml(filename)}</div>
  `;

  const checkEl = div.querySelector('.gallery-item-check');
  // 重渲染时根据已选集合恢复勾选样式（数据状态 _gallerySelectedIds 与视觉状态保持一致）
  // 注：勾选点击统一由 #galleryGrid 事件委托处理（见下方委托逻辑），此处不再单独绑定，避免与委托重复触发
  if (window._gallerySelectedIds.has(item.id)) checkEl.classList.add('checked');

  const filenameEl = div.querySelector('.gallery-item-filename');
  if (filenameEl) filenameEl.onclick = (e) => { e.stopPropagation(); window.copyFilename(filenameEl.dataset.filename); };

  div.onclick = (e) => {
    // 点击勾选框时不打开灯箱（勾选由事件委托处理）
    if (e.target.closest('.gallery-item-check')) return;
    const realIdx = (window._galleryAllItems || window._historyItems).findIndex(it => it.id === item.id);
    window.openLightbox(item.view_url, meta, e, realIdx);
  };

  return div;
};

/** 为所有画廊 item 添加处理按钮和 prompt 查看按钮 */
window._addProcessButtonsToGallery = function() {
  document.querySelectorAll('.gallery-item-actions').forEach(el => {
    if (el.querySelector('.gallery-item-process')) return; // 已添加
    const id = el.closest('.gallery-item')?.dataset?.id;
    if (!id) return;
    // 处理按钮
    const processBtn = document.createElement('button');
    processBtn.className = 'gallery-item-process';
    processBtn.innerHTML = '✨';
    processBtn.title = '用工作流处理（超分等）';
    processBtn.onclick = (e) => { e.stopPropagation(); window.processHistoryWithWorkflow(parseInt(id)); };
    el.appendChild(processBtn);
    // 下载按钮
    const dlBtn = document.createElement('button');
    dlBtn.className = 'gallery-item-dl';
    dlBtn.innerHTML = '⬇️';
    dlBtn.title = '下载';
    dlBtn.onclick = (e) => { e.stopPropagation(); window.downloadHistoryItem(parseInt(id)); };
    el.appendChild(dlBtn);
    // 查看 prompt 按钮
    const promptBtn = document.createElement('button');
    promptBtn.className = 'gallery-item-prompt-btn';
    promptBtn.innerHTML = '📝';
    promptBtn.title = '查看提示词参数';
    const item = (window._galleryAllItems || window._historyItems).find(it => it.id === parseInt(id));
    if (item && item.prompt_params) {
      promptBtn.onclick = (e) => { e.stopPropagation(); window.showImagePromptDetail(item.prompt_params, item.id); };
      el.appendChild(promptBtn);
    }
  });
};

// -------------------------------------------------------------------
// 画廊选择
// -------------------------------------------------------------------

window.toggleGalleryItem = function(id, checkEl, index, shift) {
  const grid = document.getElementById('galleryGrid');
  // Shift+点击：选中锚点与该项之间的连续一片（仅当前页 DOM 范围内）
  if (shift && window._galleryLastIndex != null && grid) {
    const items = Array.from(grid.querySelectorAll('.gallery-item'));
    const lo = Math.min(window._galleryLastIndex, index);
    const hi = Math.max(window._galleryLastIndex, index);
    items.forEach(el => {
      const idx = parseInt(el.dataset.index, 10);
      if (idx >= lo && idx <= hi) {
        const iid = parseInt(el.dataset.id, 10);
        window._gallerySelectedIds.add(iid);
        const ce = el.querySelector('.gallery-item-check');
        if (ce) ce.classList.add('checked');
      }
    });
  } else {
    if (window._gallerySelectedIds.has(id)) {
      window._gallerySelectedIds.delete(id);
      if (checkEl) checkEl.classList.remove('checked');
    } else {
      window._gallerySelectedIds.add(id);
      if (checkEl) checkEl.classList.add('checked');
    }
    window._galleryLastIndex = (index != null && !isNaN(index)) ? index : null;
  }
  window.updateCompareButton();
  window.updateGalleryActionButtons();
  window.updateGallerySelectAllCheck();
  window.updateGalleryBulkPanel();
};

// 全选当前筛选条件下的所有页（跨页），结果来自后端 /api/history/ids
window.selectAllGalleryPages = async function() {
  const params = new URLSearchParams();
  if (window._galleryFilter === 'favorite') params.set('favorite', '1');
  if (window._gallerySort) params.set('sort', window._gallerySort);
  if (window._gallerySearch) params.set('search', window._gallerySearch);
  if (window._galleryOrientation) params.set('orientation', window._galleryOrientation);
  // 关键：分类/标签/来源/时间/模型必须一起带上，否则"全选全部"会选到筛选条件之外的图，
  // 紧接着的批量删除就是真删（旧版这里漏了 5 个参数）。
  if (window._galleryCategoryId) params.set('category_id', window._galleryCategoryId);
  if (window._galleryTagIds && window._galleryTagIds.length) params.set('tag_ids', window._galleryTagIds.join(','));
  if (window._gallerySource) params.set('source', window._gallerySource);
  if (window._galleryDate) params.set('date', window._galleryDate);
  if (window._galleryModel) params.set('model', window._galleryModel);
  try {
    const data = await window.api('/api/history/ids?' + params.toString());
    const ids = data.ids || [];
    if (!ids.length) { window.showToast('当前筛选下没有可选项', 'info'); return; }
    ids.forEach(id => window._gallerySelectedIds.add(id));
    // 刷新当前页勾选视觉
    document.querySelectorAll('.gallery-item-check').forEach(el => {
      if (window._gallerySelectedIds.has(parseInt(el.dataset.id, 10))) el.classList.add('checked');
    });
    window.updateCompareButton();
    window.updateGalleryActionButtons();
    window.updateGallerySelectAllCheck();
  window.updateGalleryBulkPanel();
    window.showToast(`已全选全部 ${ids.length} 项（仅当前筛选范围）`, 'success');
  } catch (e) {
    window.showToast('全选失败: ' + e.message, 'error');
  }
};

// 统一选中交互（事件委托，兼容 HTMX / JS 两种渲染模式；同时修复 HTMX 模式下勾选框无点击绑定的隐藏问题）
if (!window._gallerySelectDelegated) {
  document.body.addEventListener('click', (e) => {
    const check = e.target.closest('.gallery-item-check');
    if (!check) return;
    e.preventDefault();
    const itemEl = check.closest('.gallery-item');
    if (!itemEl) return;
    const id = parseInt(check.dataset.id, 10);
    const index = parseInt(itemEl.dataset.index, 10);
    window.toggleGalleryItem(id, check, index, e.shiftKey);
  });
  window._gallerySelectDelegated = true;
}

// -------------------------------------------------------------------
// 画廊全选 / 取消全选
// -------------------------------------------------------------------

window.selectAllGallery = function(checked) {
  document.querySelectorAll('.gallery-item-check').forEach(el => {
    const id = parseInt(el.dataset.id);
    if (checked) {
      window._gallerySelectedIds.add(id);
      el.classList.add('checked');
    } else {
      window._gallerySelectedIds.delete(id);
      el.classList.remove('checked');
    }
  });
  window.updateCompareButton();
  window.updateGalleryActionButtons();
};

window.updateGallerySelectAllCheck = function() {
  const allCheck = document.getElementById('gallerySelectAll');
  if (!allCheck) return;
  const total = document.querySelectorAll('.gallery-item-check').length;
  const checked = document.querySelectorAll('.gallery-item-check.checked').length;
  allCheck.checked = total > 0 && total === checked;
  // 如果有选中项但非全选，设为 indeterminate 状态
  allCheck.indeterminate = checked > 0 && checked < total;
};

window.updateCompareButton = function() {
  const btn = document.getElementById('compareBtn');
  const countEl = document.getElementById('compareCount');
  const count = window._gallerySelectedIds.size;

  if (count >= 2) {
    btn.style.display = 'inline-flex';
    countEl.textContent = count;
    if (count > 4) {
      btn.disabled = true;
      btn.style.opacity = '0.45';
      btn.style.cursor = 'not-allowed';
    } else {
      btn.disabled = false;
      btn.style.opacity = '';
      btn.style.cursor = '';
    }
  } else {
    btn.style.display = 'none';
  }
};

window.enterCompareMode = function() {
  if (window._gallerySelectedIds.size > 4) {
    window.showToast('对比最多只能选择 4 张图片，请取消部分选择', 'error');
    return;
  }
  if (window._gallerySelectedIds.size < 2) {
    window.showToast('至少选择 2 张图片才能对比', 'error');
    return;
  }

  window._compareItems = (window._galleryAllItems || window._historyItems).filter(item => window._gallerySelectedIds.has(item.id));
  window._compareMode = 'sync';

  document.getElementById('compareToolbar').classList.remove('show');
  window.openUnifiedImageModal();
};

window.exitCompareMode = function() {
  window._compareMode = null;
  window._compareItems = [];
  document.getElementById('compareToolbar').classList.remove('show');
  
  if (window.pswpLightbox) {
    window.pswpLightbox.destroy();
    window.pswpLightbox = null;
  }
};

// -------------------------------------------------------------------
// 画廊徽章
// -------------------------------------------------------------------

window.updateGalleryBadge = function() {
  const badge = document.getElementById('galleryBadge');
  const count = window.activeJobs ? window.activeJobs.size : 0;
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = 'inline';
  } else {
    badge.style.display = 'none';
  }
};

// -------------------------------------------------------------------
// 分页：画廊分页组件在 renderGalleryPagination() 中渲染（复用提示词核心）
// -------------------------------------------------------------------

// ====================================================================
// 新增：历史图片处理 + prompt 详情
// ====================================================================

window.processHistoryWithWorkflow = async function(historyId) {
  try {
    // 旧代码读 window._currentWorkflow，但全仓没有任何地方给它赋值 → 这个入口永远不可用
    const wfPath = window.currentWorkflowPath ? window.currentWorkflowPath() : "";
    if (!wfPath) { window.showToast("请先选择工作流", "warn"); return; }
    const r = await window.api(`/api/history/${historyId}/process`, {
      method: "POST",
      body: JSON.stringify({
        workflow_path: wfPath,
        orientation: window.currentOrientation || "portrait",
        quality: window.getQuality ? window.getQuality() : "4K",
      }),
      headers: { "Content-Type": "application/json" },
    });
    if (r.success) {
      window.showToast("已提交处理任务", "info");
      window.trackJob(r.job_id);
    }
  } catch (e) {
    window.showToast("处理失败: " + e.message, "error");
  }
};

// 为画廊中的下载按钮添加反馈
window.downloadHistoryItemWithFeedback = function(id, btn) {
  if (btn) window.showButtonFeedback(btn, '⬇️', 1500);
  window.downloadHistoryItem(id);
};

window.showImagePromptDetail = function(promptParams, itemId) {
  if (!promptParams) { window.showToast("该图片无关联的提示词参数", "info"); return; }
  const pp = typeof promptParams === "string" ? JSON.parse(promptParams) : promptParams;
  const lines = [];
  if (pp.prompt) lines.push(`<div class="prompt-detail-line"><label>正向提示词</label><div class="prompt-detail-text">${window.escHtml(pp.prompt)}</div></div>`);
  if (pp.negative_prompt) lines.push(`<div class="prompt-detail-line"><label>反向提示词</label><div class="prompt-detail-text">${window.escHtml(pp.negative_prompt)}</div></div>`);
  if (pp.seed != null) lines.push(`<div class="prompt-detail-line"><label>种子</label><span>${pp.seed}</span></div>`);
  if (pp.steps) lines.push(`<div class="prompt-detail-line"><label>步数</label><span>${pp.steps}</span></div>`);
  if (pp.cfg_scale) lines.push(`<div class="prompt-detail-line"><label>CFG</label><span>${pp.cfg_scale}</span></div>`);
  if (pp.sampler) lines.push(`<div class="prompt-detail-line"><label>采样器</label><span>${pp.sampler}</span></div>`);
  if (pp.model) lines.push(`<div class="prompt-detail-line"><label>模型</label><span>${pp.model}</span></div>`);
  if (pp.width && pp.height) lines.push(`<div class="prompt-detail-line"><label>分辨率</label><span>${pp.width}x${pp.height}</span></div>`);
  if (pp.selection) {
    for (const [k, v] of Object.entries(pp.selection)) {
      lines.push(`<div class="prompt-detail-line" style="padding-left:12px"><label>${k}</label><div class="prompt-detail-text">${window.escHtml(v)}</div></div>`);
    }
  }
  var linesHtml = lines.join('');
  promptText = JSON.stringify(pp.prompt || '');
  negText = JSON.stringify(pp.negative_prompt || '');
  // 保存 prompt 参数到闭包变量，供投喂按钮使用
  window._pendingFeedPrompt = pp;
  window.showModal(
    '<div class="modal-header"><h2>Prompt 参数</h2><button class="close-btn" onclick="window.closeModal()">X</button></div>' +
    '<div class="modal-body" style="max-height:60vh;overflow-y:auto;gap:8px">' + linesHtml + '</div>' +
    '<div class="modal-footer">' +
      '<button class="btn btn-sm btn-primary" onclick="navigator.clipboard.writeText(' + promptText + ')">复制正向提示词</button>' +
      (negText !== '""' ? '<button class="btn btn-sm btn-ghost" onclick="navigator.clipboard.writeText(' + negText + ')">复制反向提示词</button>' : '') +
      '<button class="btn btn-sm btn-success" onclick="window._feedPromptToWorkflow()">🚀 投喂到工作流</button>' +
    '</div>'
  );
};

/** 投喂 prompt 到选中的工作流 */
window._feedPromptToWorkflow = async function() {
  const pp = window._pendingFeedPrompt;
  if (!pp) { window.showToast("无提示词数据", "error"); return; }
  const workflowPath = window.currentWorkflowPath();
  if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }
  try {
    const body = Object.assign({
      prompt: pp.prompt || "",
      negative_prompt: pp.negative_prompt || "",
      workflow_path: workflowPath,
      orientation: window.currentOrientation,
      quality: window.getQuality(),
      seed: pp.seed || 0,
    }, window.workflowExtraBody());
    const data = await window.api("/api/run_text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    window.showToast(`已推送（job ${data.job_id}）`, "success");
    window.closeModal();
    window.trackJob(data.job_id);
  } catch (e) {
    window.showToast("投喂失败: " + e.message, "error");
  }
};


// ======== Phase 5: 图片分类 / 标签（gallery 侧栏）========
window._galleryCategoryId = "";
window._galleryTagIds = [];
window._galleryCats = [];
window._galleryTags = [];

window.loadGallerySidebar = async function() {
  try {
    const cd = await window.api("/api/categories?tree=true&count_scope=image");
    window._galleryCats = (cd && cd.categories) || [];
    const treeEl = document.getElementById("galleryCatTree");
    if (treeEl) {
      let html = '<div class="gallery-cat-item' + (window._galleryCategoryId === "" ? " active" : "") + '" data-cat="" data-level="0" style="padding-left:8px" onclick="window.onGalleryCategoryClick(\'\')">全部图片</div>';
      html += window._renderGalleryCatTree(window._galleryCats, 0);
      treeEl.innerHTML = html;
    }
    const td = await window.api("/api/tags?count_scope=image");
    window._galleryTags = (td && td.tags) || [];
    const cloud = document.getElementById("galleryTagCloud");
    if (cloud) {
      cloud.innerHTML = window._galleryTags.map(t => {
        // 背景用标签色（钢蓝/自定义色），文字为白色
        const tagColor = t.color || "#5b8fb9";
        return '<span class="gallery-tag' + (window._galleryTagIds.indexOf(t.id) >= 0 ? " active" : "") + '" data-tag="' + t.id + '" style="--c:' + tagColor + '" onclick="window.onGalleryTagClick(' + t.id + ')">' + window.escHtml(t.name) + ' <i>' + (t.prompt_count || 0) + '</i></span>';
      }).join("");
    }
    const bc = document.getElementById("galleryBulkCat");
    if (bc) {
      const flat = [];
      (function walk(list){ (list||[]).forEach(c=>{ flat.push(c); if (c.children) walk(c.children); }); })(window._galleryCats);
      bc.innerHTML = '<option value="">选择分类…</option>' + flat.map(c => '<option value="' + c.id + '">' + window.escHtml(c.name) + '</option>').join("");
    }
    const bt = document.getElementById("galleryBulkTag");
    if (bt) {
      bt.innerHTML = '<option value="">选择标签…</option>' + window._galleryTags.map(t => '<option value="' + t.id + '">' + window.escHtml(t.name) + '</option>').join("");
    }
    window.updateGalleryBulkPanel();
    try { await window.loadGalleryFacets(); } catch(e) { console.error("loadGalleryFacets", e); }
    window._restoreGallerySidebarState();
    window.renderGalleryActiveFilters();
  } catch(e) { console.error("loadGallerySidebar", e); }
};

window._renderGalleryCatTree = function(cats, level) {
  let html = "";
  (cats||[]).forEach(c => {
    const active = (String(window._galleryCategoryId) === String(c.id)) ? " active" : "";
    const hasChildren = c.children && c.children.length;
    const toggle = hasChildren
      ? '<span class="gallery-cat-toggle" onclick="event.stopPropagation();window.toggleGalleryCatNode(this)">▾</span>'
      : '<span class="gallery-cat-toggle-spacer"></span>';
    html += '<div class="gallery-cat-node">';
    html += '<div class="gallery-cat-item' + active + (hasChildren ? ' has-children' : '') + '" data-cat="' + c.id + '" data-level="' + level + '" style="padding-left:' + (8 + level * 16) + 'px" onclick="window.onGalleryCategoryClick(' + c.id + ')">' + toggle + '<span class="gallery-cat-label">' + window.escHtml(c.name) + '</span> <i>' + (c.prompt_count || 0) + '</i></div>';
    if (hasChildren) html += '<div class="gallery-cat-children">' + window._renderGalleryCatTree(c.children, level + 1) + '</div>';
    html += '</div>';
  });
  return html;
};

window.onGalleryCategoryClick = function(catId) {
  window._galleryCategoryId = (catId === "" || catId === null) ? "" : parseInt(catId);
  // 分类变化后旧的选中项已不在当前结果集里，必须清空，否则会被批量删除带上
  window._clearGallerySelection?.();
  document.querySelectorAll("#galleryCatTree .gallery-cat-item").forEach(el => {
    el.classList.toggle("active", String(el.dataset.cat) === String(catId));
  });
  if (window._persistGalleryState) window._persistGalleryState();
  window.renderGalleryActiveFilters();
  // 防抖：连续快速切换时只触发最后一次刷新
  clearTimeout(window._catClickTimer);
  window._catClickTimer = setTimeout(() => {
    document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
  }, 250);
};

window.onGalleryTagClick = function(tagId) {
  const i = window._galleryTagIds.indexOf(tagId);
  if (i >= 0) window._galleryTagIds.splice(i, 1);
  else window._galleryTagIds.push(tagId);
  window._clearGallerySelection?.();
  // 仅局部更新标签高亮 + 筛选汇总，不再整块重建侧栏（避免闪烁与重复请求）
  document.querySelectorAll("#galleryTagCloud .gallery-tag").forEach(el => {
    el.classList.toggle("active", window._galleryTagIds.indexOf(parseInt(el.dataset.tag)) >= 0);
  });
  if (window._persistGalleryState) window._persistGalleryState();
  window.renderGalleryActiveFilters();
  // 防抖：连续切换标签时只触发最后一次画廊刷新，避免缩略图请求堆积
  clearTimeout(window._tagClickTimer);
  window._tagClickTimer = setTimeout(() => {
    document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
  }, 250);
};

window.onGalleryFacetClick = function(type, value) {
  const key = "_gallery" + type[0].toUpperCase() + type.slice(1);
  window[key] = (window[key] === value) ? "" : value;
  window._clearGallerySelection?.();
  if (window._persistGalleryState) window._persistGalleryState();
  document.querySelectorAll("#galleryFacets .facet-chip").forEach(el => {
    const cur = window["_gallery" + el.dataset.ftype[0].toUpperCase() + el.dataset.ftype.slice(1)];
    el.classList.toggle("active", el.dataset.ftype === type && cur === el.dataset.fval);
  });
  window.renderGalleryActiveFilters();
  document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
};

window.loadGalleryFacets = async function() {
  try {
    const params = new URLSearchParams();
    if (window._galleryFilter === "favorite") params.set("favorite", "1");
    if (window._gallerySearch) params.set("search", window._gallerySearch);
    if (window._galleryCategoryId) params.set("category_id", window._galleryCategoryId);
    if (window._galleryTagIds && window._galleryTagIds.length) params.set("tag_ids", window._galleryTagIds.join(","));
    const data = await window.api("/api/history/facets?" + params.toString());
    const el = document.getElementById("galleryFacets");
    if (!el) return;
    const src = data.source || {}, dates = data.date || {}, models = data.model || {};
    const srcLabels = { "comfyui_sync": "ComfyUI同步", "local": "本地生成" };
    let h = '<div class="facet-group"><div class="facet-title">来源</div>';
    Object.keys(src).sort().forEach(k => {
      const active = window._gallerySource === k ? " active" : "";
      h += '<span class="facet-chip' + active + '" data-ftype="source" data-fval="' + String(k).replace(/"/g, "&quot;") + '" onclick=\'window.onGalleryFacetClick("source", ' + JSON.stringify(k) + ')\'>' + window.escHtml(srcLabels[k] || k) + ' <i>' + src[k] + '</i></span>';
    });
    h += '</div><div class="facet-group"><div class="facet-title">时间</div>';
    Object.keys(dates).sort().reverse().forEach(k => {
      const active = window._galleryDate === k ? " active" : "";
      h += '<span class="facet-chip' + active + '" data-ftype="date" data-fval="' + String(k).replace(/"/g, "&quot;") + '" onclick=\'window.onGalleryFacetClick("date", ' + JSON.stringify(k) + ')\'>' + window.escHtml(k) + ' <i>' + dates[k] + '</i></span>';
    });
    h += '</div><div class="facet-group"><div class="facet-title">模型</div>';
    Object.keys(models).sort().forEach(k => {
      const active = window._galleryModel === k ? " active" : "";
      h += '<span class="facet-chip' + active + '" data-ftype="model" data-fval="' + String(k).replace(/"/g, "&quot;") + '" onclick=\'window.onGalleryFacetClick("model", ' + JSON.stringify(k) + ')\'>' + window.escHtml(k) + ' <i>' + models[k] + '</i></span>';
    });
    h += '</div>';
    const orients = data.orientation || {};
    const orientOrder = { "横图": 0, "竖图": 1, "方图": 2, "未记录": 3 };
    h += '<div class="facet-group"><div class="facet-title">方向</div>';
    Object.keys(orients).sort((a, b) => (orientOrder[a] ?? 9) - (orientOrder[b] ?? 9)).forEach(k => {
      const active = window._galleryOrientation === k ? " active" : "";
      h += '<span class="facet-chip' + active + '" data-ftype="orientation" data-fval="' + String(k).replace(/"/g, "&quot;") + '" onclick=\'window.onGalleryFacetClick("orientation", ' + JSON.stringify(k) + ')\'>' + window.escHtml(k) + ' <i>' + orients[k] + '</i></span>';
    });
    h += '</div>';
    el.innerHTML = h;
  } catch (e) { console.error("loadGalleryFacets", e); }
};

window.updateGalleryBulkPanel = function() {
  const panel = document.getElementById("galleryBulk");
  if (!panel) return;
  const n = window._gallerySelectedIds.size;
  panel.style.display = n > 0 ? "block" : "none";
  const cnt = document.getElementById("galleryBulkCount");
  if (cnt) cnt.textContent = n;
  // 选中图片后自动展开批量操作分组，方便操作
  if (n > 0) {
    const grp = document.querySelector('.gallery-group[data-group="bulk"]');
    if (grp) grp.classList.remove("collapsed");
  }
};

window.bulkAddCategory = async function() {
  const sel = document.getElementById("galleryBulkCat");
  const catId = sel ? parseInt(sel.value) : 0;
  if (!catId) { window.showToast("请选择分类", "warn"); return; }
  const ids = Array.from(window._gallerySelectedIds);
  if (!ids.length) return;
  let ok = 0;
  for (const id of ids) {
    try { const r = await window.api(`/api/history/${id}/categories/${catId}`, {method:"POST"}); if (r && r.success) ok++; } catch(e){}
  }
  window.showToast(`已为 ${ok} 张图片加入分类`, "success");
  window.loadGallerySidebar();
};

window.bulkAddTag = async function() {
  const sel = document.getElementById("galleryBulkTag");
  const tagId = sel ? parseInt(sel.value) : 0;
  if (!tagId) { window.showToast("请选择标签", "warn"); return; }
  const ids = Array.from(window._gallerySelectedIds);
  if (!ids.length) return;
  let ok = 0;
  for (const id of ids) {
    try { const r = await window.api(`/api/history/${id}/tags/${tagId}`, {method:"POST"}); if (r && r.success) ok++; } catch(e){}
  }
  window.showToast(`已为 ${ok} 张图片打标签`, "success");
  window.loadGallerySidebar();
};

window.bulkInherit = async function() {
  const ids = Array.from(window._gallerySelectedIds);
  if (!ids.length) return;
  let ok = 0;
  for (const id of ids) {
    try { const r = await window.api(`/api/history/${id}/inherit`, {method:"POST"}); if (r && r.success) ok++; } catch(e){}
  }
  window.showToast(`已为 ${ok} 张图片继承来源分类`, "success");
  window.loadGallerySidebar();
  document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
};

window.backfillGalleryTaxonomy = async function() {
  try {
    const r = await window.api("/api/history/backfill_taxonomy", {method:"POST"});
    if (r && r.success) window.showToast(`已补齐 ${r.backfilled} 张图片的分类/标签`, "success");
    window.loadGallerySidebar();
  } catch(e) { window.showToast("补齐失败: " + e.message, "error"); }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", window.loadGallerySidebar);
} else {
  window.loadGallerySidebar();
}

// ---- 侧栏宽度拖动 ----
window.initGalleryResize = function() {
  const layout = document.querySelector(".gallery-layout");
  const sidebar = document.getElementById("gallerySidebar");
  const handle = document.getElementById("galleryResizeHandle");
  if (!layout || !sidebar || !handle) return;
  // 恢复上次宽度
  try {
    const w = parseInt(localStorage.getItem("gallery_sidebar_width") || "240", 10);
    if (w >= 160 && w <= 560) { sidebar.style.width = w + "px"; sidebar.style.flexBasis = w + "px"; }
  } catch (e) {}
  let dragging = false;
  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    dragging = true;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    handle.style.cursor = "col-resize";
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const rect = layout.getBoundingClientRect();
    let w = e.clientX - rect.left;
    w = Math.max(160, Math.min(560, w));
    sidebar.style.width = w + "px";
    sidebar.style.flexBasis = w + "px";
  });
  document.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    handle.style.cursor = "";
    try { localStorage.setItem("gallery_sidebar_width", parseInt(sidebar.style.width, 10) || 240); } catch (e) {}
  });
};
window.initGalleryResize();

// ---- 侧栏折叠 / 分组折叠 / 当前筛选汇总 ----
window._restoreGallerySidebarState = function() {
  try {
    if (localStorage.getItem("gallery_sidebar_collapsed") === "1") {
      const layout = document.querySelector(".gallery-layout");
      if (layout) layout.classList.add("collapsed");
      const ro = document.getElementById("galleryReopen");
      if (ro) ro.style.display = "inline-flex";
    }
    document.querySelectorAll(".gallery-group").forEach(g => {
      const st = localStorage.getItem("gallery_group_" + g.dataset.group);
      if (st === "1") g.classList.add("collapsed");
      else if (st === "0") g.classList.remove("collapsed");
    });
  } catch (e) {}
};

window.toggleGallerySidebar = function() {
  const layout = document.querySelector(".gallery-layout");
  const reopen = document.getElementById("galleryReopen");
  if (!layout) return;
  const collapsed = layout.classList.toggle("collapsed");
  if (reopen) reopen.style.display = collapsed ? "inline-flex" : "none";
  try { localStorage.setItem("gallery_sidebar_collapsed", collapsed ? "1" : "0"); } catch (e) {}
};

window.toggleGalleryGroup = function(name) {
  const g = document.querySelector('.gallery-group[data-group="' + name + '"]');
  if (!g) return;
  const collapsed = g.classList.toggle("collapsed");
  try { localStorage.setItem("gallery_group_" + name, collapsed ? "1" : "0"); } catch (e) {}
};

window.toggleGalleryCatNode = function(arrowEl) {
  const item = arrowEl.closest(".gallery-cat-item");
  if (!item) return;
  const children = item.parentElement.querySelector(".gallery-cat-children");
  if (!children) return;
  const collapsed = children.classList.toggle("collapsed");
  arrowEl.textContent = collapsed ? "▸" : "▾";
};

window.renderGalleryActiveFilters = function() {
  const el = document.getElementById("galleryActiveFilters");
  if (!el) return;
  const chips = [];
  if (window._galleryCategoryId) {
    let name = "未分类";
    (function find(list){ (list||[]).forEach(c => { if (String(c.id) === String(window._galleryCategoryId)) name = c.name; if (c.children) find(c.children); }); })(window._galleryCats);
    chips.push('<span class="active-filter-chip">' + window.escHtml(name) + ' <button onclick="window.clearGalleryFilter(\'category\')">×</button></span>');
  }
  (window._galleryTagIds || []).forEach(id => {
    const t = (window._galleryTags || []).find(x => x.id === id);
    const nm = t ? t.name : ("#" + id);
    chips.push('<span class="active-filter-chip">' + window.escHtml(nm) + ' <button onclick="window.clearGalleryFilter(\'tag\', ' + id + ')">×</button></span>');
  });
  const facetDefs = [
    ["source", window._gallerySource, {"comfyui_sync": "ComfyUI同步", "local": "本地生成"}],
    ["date", window._galleryDate, null],
    ["model", window._galleryModel, null],
    ["orientation", window._galleryOrientation, null],
  ];
  facetDefs.forEach(([type, val, labels]) => {
    if (val) {
      const disp = (labels && labels[val]) ? labels[val] : val;
      chips.push('<span class="active-filter-chip">' + window.escHtml(disp) + ' <button onclick="window.clearGalleryFilter(\'' + type + '\')">×</button></span>');
    }
  });
  if (!chips.length) { el.style.display = "none"; return; }
  el.style.display = "flex";
  el.innerHTML = chips.join("") + '<button class="active-filter-clear" onclick="window.clearGalleryFilter(\'all\')">清除全部</button>';
};

window.clearGalleryFilter = function(type, value) {
  if (type === "all") {
    window._galleryCategoryId = "";
    window._galleryTagIds = [];
    window._gallerySource = "";
    window._galleryDate = "";
    window._galleryModel = "";
    window._galleryOrientation = "";
  } else if (type === "category") {
    window._galleryCategoryId = "";
  } else if (type === "tag") {
    const i = window._galleryTagIds.indexOf(value);
    if (i >= 0) window._galleryTagIds.splice(i, 1);
  } else if (type === "source") {
    window._gallerySource = "";
  } else if (type === "date") {
    window._galleryDate = "";
  } else if (type === "model") {
    window._galleryModel = "";
  } else if (type === "orientation") {
    window._galleryOrientation = "";
  }
  if (window._persistGalleryState) window._persistGalleryState();
  window.syncGalleryFilterVisuals();
  window.renderGalleryActiveFilters();
  document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
};

window.syncGalleryFilterVisuals = function() {
  document.querySelectorAll("#galleryCatTree .gallery-cat-item").forEach(el => {
    el.classList.toggle("active", String(el.dataset.cat) === String(window._galleryCategoryId));
  });
  document.querySelectorAll("#galleryTagCloud .gallery-tag").forEach(el => {
    el.classList.toggle("active", window._galleryTagIds.indexOf(parseInt(el.dataset.tag)) >= 0);
  });
  document.querySelectorAll("#galleryFacets .facet-chip").forEach(el => {
    const key = "_gallery" + el.dataset.ftype[0].toUpperCase() + el.dataset.ftype.slice(1);
    el.classList.toggle("active", window[key] === el.dataset.fval);
  });
};
