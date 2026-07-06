// gallery.js - 画廊模块
// 依赖：utils.js, history.js

window._gallerySelectedIds = new Set();
window._gallerySort = "newest";
window._galleryFilter = "all";
window._gallerySearch = "";

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

  const thumbUrl = `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}&size=600`;

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
  checkEl.onclick = (e) => { e.stopPropagation(); window.toggleGalleryItem(item.id, checkEl); };

  const filenameEl = div.querySelector('.gallery-item-filename');
  if (filenameEl) filenameEl.onclick = (e) => { e.stopPropagation(); window.copyFilename(filenameEl.dataset.filename); };

  div.onclick = (e) => {
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

window.toggleGalleryItem = function(id, checkEl) {
  if (window._gallerySelectedIds.has(id)) {
    window._gallerySelectedIds.delete(id);
    checkEl.classList.remove('checked');
  } else {
    window._gallerySelectedIds.add(id);
    checkEl.classList.add('checked');
  }
  window.updateCompareButton();
  window.updateGalleryActionButtons();
  window.updateGallerySelectAllCheck();
};

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
    const wfPath = window._currentWorkflow || "";
    if (!wfPath) { window.showToast("请先选择工作流", "warn"); return; }
    const r = await window.api(`/api/history/${historyId}/process`, {
      method: "POST",
      body: JSON.stringify({ workflow_path: wfPath }),
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
