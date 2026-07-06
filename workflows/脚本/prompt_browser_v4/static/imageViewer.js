// imageViewer.js - 图片查看器模块
// 依赖：utils.js, gallery.js, history.js

window._compareMode = null;
window._compareItems = [];
window._compareZoomSync = false;
window._lightboxItems = [];
window._lightboxIndex = 0;

// -------------------------------------------------------------------
// 统一图片查看弹窗
// -------------------------------------------------------------------

window.openUnifiedImageModal = function() {
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
          <div class="lightbox-wf-selector" id="lightboxWfSelector" style="display:none">
            <span class="lightbox-wf-label">工作流:</span>
            <button class="lightbox-wf-name" id="lightboxWfName">选择工作流</button>
          </div>
          <button id="compareSyncBtn2" class="active" onclick="window.setCompareMode('sync')">同步</button>
          <button id="compareSplitBtn2" onclick="window.setCompareMode('split')">分屏</button>
          <button id="lightboxFavBtn" class="lightbox-action-btn" style="display:none" onclick="window.toggleFavoriteFromLightbox()">☆</button>
          <button id="lightboxDlBtn" class="lightbox-action-btn" style="display:none" onclick="window.downloadFromLightbox()">⬇️</button>
          <button id="lightboxRegenBtn" class="lightbox-action-btn" style="display:none" onclick="window.regenFromLightbox()">🔄</button>
          <button id="lightboxProcessBtn" class="lightbox-action-btn" style="display:none" onclick="window.processFromLightbox()" title="投喂给工作流处理（超分/重绘等）">⚡</button>
          <button id="lightboxPrevBtn" class="lightbox-action-btn" style="display:none" onclick="window.prevLightboxImage()" title="上一张 (←)">←</button>
          <button id="lightboxNextBtn" class="lightbox-action-btn" style="display:none" onclick="window.nextLightboxImage()" title="下一张 (→)">→</button>
          <button id="imageFlipBtn" class="lightbox-action-btn" onclick="window.flipImage()" title="水平翻转">⇋</button>
          <button id="imageRotateBtn" class="lightbox-action-btn" onclick="window.rotateImage()" title="旋转 90°">⟳</button>
          <button id="imageFitBtn" class="lightbox-action-btn" onclick="window.toggleFitMode()" title="适应/原始尺寸">1:1</button>
          <button id="compareResetBtn" onclick="window.resetImageZoom()">重置</button>
          <button id="lightboxDelBtn" class="lightbox-action-btn" style="display:none;color:var(--danger)" onclick="window.deleteFromLightbox()" title="删除">🗑️</button>
          <button onclick="window.closeCompareModal(true)">✕ 退出</button>
        </div>
      </div>
      <div class="compare-modal-body" id="compareModalBody"></div>
    `;
    document.body.appendChild(overlay);

    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') window.closeCompareModal(true);
    });
  }

  const syncBtn = document.getElementById('compareSyncBtn2');
  const splitBtn = document.getElementById('compareSplitBtn2');
  const resetBtn = document.getElementById('compareResetBtn');
  const titleText = document.getElementById('imageModalTitleText');
  const zoomDisplay = document.getElementById('compareZoomDisplay');
  const favBtn = document.getElementById('lightboxFavBtn');
  const dlBtn = document.getElementById('lightboxDlBtn');
  const regenBtn = document.getElementById('lightboxRegenBtn');
  const processBtn = document.getElementById('lightboxProcessBtn');
  const prevBtn = document.getElementById('lightboxPrevBtn');
  const nextBtn = document.getElementById('lightboxNextBtn');
  const flipBtn = document.getElementById('imageFlipBtn');
  const rotateBtn = document.getElementById('imageRotateBtn');
  const fitBtn = document.getElementById('imageFitBtn');
  const delBtn = document.getElementById('lightboxDelBtn');
  const wfSelector = document.getElementById('lightboxWfSelector');
  const wfNameBtn = document.getElementById('lightboxWfName');

  // 绑定工作流按钮点击事件
  if (wfNameBtn && !wfNameBtn._clickBound) {
    wfNameBtn._clickBound = true;
    wfNameBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log('Workflow button clicked');
      if (window.openWfModal) {
        window.openWfModal();
      } else {
        console.error('openWfModal function not found');
      }
    });
  }

  if (window._compareMode === 'single') {
    syncBtn.style.display = 'none';
    splitBtn.style.display = 'none';
    favBtn.style.display = '';
    dlBtn.style.display = '';
    regenBtn.style.display = '';
    processBtn.style.display = '';
    resetBtn.style.display = '';
    prevBtn.style.display = '';
    nextBtn.style.display = '';
    flipBtn.style.display = '';
    rotateBtn.style.display = '';
    fitBtn.style.display = '';
    delBtn.style.display = '';
    wfSelector.style.display = '';
    titleText.textContent = `图片查看（${window._lightboxIndex + 1} / ${window._lightboxItems.length}）`;
  } else {
    syncBtn.style.display = '';
    splitBtn.style.display = '';
    favBtn.style.display = 'none';
    dlBtn.style.display = 'none';
    regenBtn.style.display = 'none';
    processBtn.style.display = 'none';
    resetBtn.style.display = '';
    prevBtn.style.display = 'none';
    nextBtn.style.display = 'none';
    flipBtn.style.display = '';
    rotateBtn.style.display = '';
    fitBtn.style.display = '';
    wfSelector.style.display = 'none';
    titleText.innerHTML = `对比模式（<span id="compareModalCount">0</span> 张）`;
  }

  // 更新灯箱中的工作流显示
  window.updateLightboxWorkflowDisplay();

  if (zoomDisplay) zoomDisplay.textContent = '100%';

  overlay.classList.add('active');
  overlay.focus();
  document.body.style.overflow = 'hidden';

  window.saveLightboxState();
  window.renderUnifiedImageGrid();
};

window.closeCompareModal = function(navigateBack = false) {
  const overlay = document.getElementById('compareModal');
  if (overlay) overlay.classList.remove('active');
  document.body.style.overflow = '';

  window._destroyAllViewers();

  // 对比模式退出时清除选中状态
  if (window._compareMode !== 'single') {
    window._gallerySelectedIds.clear();
    window.updateCompareButton();
    window.renderGallery(window._historyItems);
  }

  if (window._compareMode === 'single') {
    window._lightboxItems = [];
    window._lightboxIndex = 0;
  } else {
    window._compareItems = [];
  }

  window._compareMode = null;
  const toolbar = document.getElementById('compareToolbar');
  if (toolbar) toolbar.classList.remove('show');

  window.clearLightboxState();

  if (navigateBack) {
    history.back();
  }
};

// -------------------------------------------------------------------
// 图片网格渲染
// -------------------------------------------------------------------

window.renderUnifiedImageGrid = function() {
  const body = document.getElementById('compareModalBody');
  const countEl = document.getElementById('compareModalCount');
  if (!body) return;

  window._destroyAllViewers();
  window._activeImageIdx = 0;
  body.innerHTML = '';

  let items = [];
  if (window._compareMode === 'single') {
    items = [window._lightboxItems[window._lightboxIndex]];
    body.className = 'compare-modal-body compare-grid-1';

    // 添加左右切换箭头（仅单图模式）
    if (window._lightboxItems.length > 1) {
      const prevArrow = document.createElement('div');
      prevArrow.className = 'lightbox-nav-arrow lightbox-nav-prev';
      prevArrow.innerHTML = '‹';
      prevArrow.onclick = (e) => { e.stopPropagation(); window.prevLightboxImage(); };
      body.appendChild(prevArrow);

      const nextArrow = document.createElement('div');
      nextArrow.className = 'lightbox-nav-arrow lightbox-nav-next';
      nextArrow.innerHTML = '›';
      nextArrow.onclick = (e) => { e.stopPropagation(); window.nextLightboxImage(); };
      body.appendChild(nextArrow);
    }
  } else {
    items = window._compareItems;
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
    img.dataset.idx = idx;
    wrap.appendChild(img);

    const label = document.createElement('div');
    label.className = 'compare-item-label';
    let labelHTML = '';

    if (window._compareMode === 'single') {
      const rows = [];
      if (item.filename) rows.push(`<div class="label-param-row"><span class="label-param-key">文件名：</span><span class="label-param-val label-filename-clickable" title="点击复制文件名" data-filename="${window.escAttr(item.filename)}">${window.escHtml(item.filename)}</span></div>`);
      if (item.prompt_name && item.prompt_id) {
        rows.push(`<div class="label-param-row"><span class="label-param-key">提示词：</span><span class="label-param-val"><span class="lightbox-prompt-link" onclick="window.jumpToPrompt(${item.prompt_id})" title="跳转到提示词详情">📝 ${window.escHtml(item.prompt_name)}</span></span></div>`);
      }
      if (item.created_at) rows.push(`<div class="label-param-row"><span class="label-param-key">时间：</span><span class="label-param-val">${item.created_at}</span></div>`);
      const p = item.prompt_params || {};
      // 组合创作：展示完整提示词
      if (p.source === "composer" && p.prompt) {
        rows.push(`<div class="label-param-row"><span class="label-param-key">组合提示词：</span></div>`);
        rows.push(`<div class="label-param-row" style="max-width:400px;word-break:break-all;white-space:pre-wrap;line-height:1.6">${window.escHtml(p.prompt)}</div>`);
      }
      if (p.steps) rows.push(`<div class="label-param-row"><span class="label-param-key">步数：</span><span class="label-param-val">${p.steps}</span></div>`);
      if (p.cfg_scale) rows.push(`<div class="label-param-row"><span class="label-param-key">CFG：</span><span class="label-param-val">${p.cfg_scale}</span></div>`);
      if (p.sampler) rows.push(`<div class="label-param-row"><span class="label-param-key">采样器：</span><span class="label-param-val">${window.escHtml(p.sampler)}</span></div>`);
      if (p.seed != null) rows.push(`<div class="label-param-row"><span class="label-param-key">种子：</span><span class="label-param-val">${p.seed}</span></div>`);
      if (p.model) rows.push(`<div class="label-param-row"><span class="label-param-key">模型：</span><span class="label-param-val">${window.escHtml(p.model)}</span></div>`);
      if (item.width && item.height) rows.push(`<div class="label-param-row"><span class="label-param-key">分辨率：</span><span class="label-param-val">${item.width}×${item.height}</span></div>`);
      if (item.file_size) rows.push(`<div class="label-param-row"><span class="label-param-key">文件大小：</span><span class="label-param-val">${window.formatFileSize(item.file_size)}</span></div>`);
      labelHTML = rows.length ? rows.join('') : window.buildImageMeta(item);
    } else {
      let parts = [];
      if (item.filename) parts.push(`<span title="${window.escHtml(item.filename)}">${window.escHtml(item.filename)}</span>`);
      if (item.prompt_name && item.prompt_id) {
        parts.push(`<span class="lightbox-prompt-link" onclick="window.jumpToPrompt(${item.prompt_id})">📝 ${window.escHtml(item.prompt_name)}</span>`);
      }
      if (item.created_at) parts.push(item.created_at);
      labelHTML = parts.join(' · ') || window.buildImageMeta(item);
    }

    label.innerHTML = labelHTML;
    label.addEventListener('mousedown', (e) => e.stopPropagation());
    label.querySelectorAll('.label-filename-clickable').forEach(el => {
      el.style.cursor = 'pointer';
      el.onclick = (e) => {
        e.stopPropagation();
        window.copyFilename(el.dataset.filename);
      };
    });
    wrap.appendChild(label);
    body.appendChild(wrap);
  });

  const headerPrompt = document.getElementById('lightboxHeaderPrompt');
  if (headerPrompt) {
    if (window._compareMode === 'single' && window._lightboxItems.length > 0) {
      const item = window._lightboxItems[window._lightboxIndex];
      let promptName = item.prompt_name || '';
      if (!promptName && item.prompt_id) {
        const found = window.allPrompts.find(p => p.id === item.prompt_id);
        promptName = found ? found.name : '';
      }
      if (!promptName) {
        promptName = item.prompt_id ? `提示词 #${item.prompt_id}` : `图片 #${item.id}`;
      }
      if (promptName && promptName !== `图片 #${item.id}`) {
        if (item.prompt_id) {
          headerPrompt.innerHTML = `<span class="lightbox-prompt-link" onclick="window.jumpToPrompt(${item.prompt_id})">📝 ${window.escHtml(promptName)}</span>`;
        } else {
          headerPrompt.textContent = `📝 ${promptName}`;
        }
        headerPrompt.title = promptName;
      } else if (promptName === `图片 #${item.id}`) {
        headerPrompt.innerHTML = '';
      } else {
        headerPrompt.innerHTML = '';
      }
    } else {
      headerPrompt.innerHTML = '';
    }
  }

  if (window._compareMode === 'single') {
    window.setupImageModalKeyboardNav();
    window.updateLightboxActions();
    window.updateRoute(window._lightboxRouteReplace);
    window._lightboxRouteReplace = false;

    // 添加空白区域滑动切换图片功能
    let swipeStartX = 0;
    let swipeStartY = 0;
    let isSwiping = false;

    body.addEventListener('mousedown', (e) => {
      // 只在空白区域或箭头按钮上启动滑动
      const target = e.target;
      const isBlankArea = target === body ||
                          target.classList.contains('lightbox-nav-arrow') ||
                          target.classList.contains('lightbox-nav-prev') ||
                          target.classList.contains('lightbox-nav-next');

      if (isBlankArea && e.button === 0) {
        swipeStartX = e.clientX;
        swipeStartY = e.clientY;
        isSwiping = true;
      }
    });

    body.addEventListener('mouseup', (e) => {
      if (!isSwiping) return;
      isSwiping = false;

      const deltaX = e.clientX - swipeStartX;
      const deltaY = e.clientY - swipeStartY;
      const absDeltaX = Math.abs(deltaX);
      const absDeltaY = Math.abs(deltaY);

      // 水平滑动 > 50px 且垂直滑动 < 30px 时触发切换
      if (absDeltaX > 50 && absDeltaY < 30) {
        if (deltaX > 0) {
          // 向右滑动，显示上一张
          window.prevLightboxImage();
        } else {
          // 向左滑动，显示下一张
          window.nextLightboxImage();
        }
      }
    });
  }

  window._bindCompareInteractions(body);
};

// -------------------------------------------------------------------
// 灯箱操作
// -------------------------------------------------------------------

window.updateLightboxActions = function() {
  const item = window._lightboxItems[window._lightboxIndex];
  if (!item) return;
  const favBtn = document.getElementById('lightboxFavBtn');
  const regenBtn = document.getElementById('lightboxRegenBtn');
  const processBtn = document.getElementById('lightboxProcessBtn');
  if (favBtn) {
    favBtn.textContent = item.favorite ? '★' : '☆';
    favBtn.title = item.favorite ? '取消收藏' : '收藏';
  }
  if (regenBtn) {
    regenBtn.style.display = item.prompt_id ? '' : 'none';
  }
  if (processBtn) {
    processBtn.title = '投喂给工作流处理（超分/重绘等）';
  }
};

// -------------------------------------------------------------------
// 更新灯箱中的工作流显示
// -------------------------------------------------------------------

window.updateLightboxWorkflowDisplay = function() {
  const wfNameBtn = document.getElementById('lightboxWfName');
  if (!wfNameBtn) return;

  const workflowPath = window.currentWorkflowPath();
  if (workflowPath) {
    // 查找工作流名称
    const wf = window.workflowList.find(w => w.path === workflowPath);
    wfNameBtn.textContent = wf ? wf.name : '选择工作流';
    wfNameBtn.title = workflowPath;
  } else {
    wfNameBtn.textContent = '选择工作流';
    wfNameBtn.title = '点击选择工作流';
  }
};

window.downloadFromLightbox = function() {
  const item = window._lightboxItems[window._lightboxIndex];
  if (!item) return;
  window.downloadHistoryItem(item.id);
};

window.regenFromLightbox = function() {
  const item = window._lightboxItems[window._lightboxIndex];
  if (!item || !item.prompt_id) {
    window.showToast('该图片没有关联的提示词，无法重新生成', 'error');
    return;
  }
  window.regenerateFromHistory(item.prompt_id);
};

window.deleteFromLightbox = async function() {
  const item = window._lightboxItems[window._lightboxIndex];
  if (!item) return;
  if (!confirm("删除此图片的历史记录？")) return;
  try {
    await window.api(`/api/history/${item.id}`, { method: "DELETE" });
    // 从列表中移除
    window._lightboxItems.splice(window._lightboxIndex, 1);
    if (window._lightboxItems.length === 0) {
      window.closeCompareModal(true);
      window.showToast("已删除", "info");
      return;
    }
    if (window._lightboxIndex >= window._lightboxItems.length) {
      window._lightboxIndex = window._lightboxItems.length - 1;
    }
    window._lightboxRouteReplace = true;
    window.renderUnifiedImageGrid();
    window.showToast("已删除", "info");
    // 同步刷新画廊和提示词历史
    if (typeof window.loadHistory === "function") window.loadHistory(false);
    if (typeof window.selectedId === "number" && window.selectedId > 0
        && typeof window.loadPromptHistory === "function") {
      window.loadPromptHistory(window.selectedId);
    }
  } catch (e) {
    window.showToast("删除失败: " + e.message, "error");
  }
};

// -------------------------------------------------------------------
// 图片处理（超分/重绘等）
// -------------------------------------------------------------------

window._processBtnLoading = false; // 防抖标志
window._processLoadingToast = null; // 保存loading toast 元素

window.processFromLightbox = async function() {
  // 防抖：如果正在处理中，忽略点击
  if (window._processBtnLoading) {
    window.showToast('正在处理中，请稍候...', 'info');
    return;
  }

  const item = window._lightboxItems[window._lightboxIndex];
  if (!item) return;

  const workflowPath = window.currentWorkflowPath();
  if (!workflowPath) {
    window.showToast('请先选择工作流', 'error');
    return;
  }

  // 设置loading状态
  window._processBtnLoading = true;
  const processBtn = document.getElementById('lightboxProcessBtn');
  if (processBtn) {
    processBtn.disabled = true;
    processBtn.style.opacity = '0.6';
    processBtn.innerHTML = '⏳'; // 改为loading图标
    processBtn.title = '正在提交处理任务...';
  }

  // 显示loading toast（使用自定义元素，因为showToast不支持持久化）
  if (!window._processLoadingToast) {
    const toast = document.createElement('div');
    toast.id = 'processLoadingToast';
    toast.style.cssText = `
      position: fixed;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      background: var(--panel);
      color: var(--text);
      padding: 12px 24px;
      border-radius: 8px;
      border: 1px solid var(--primary);
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      z-index: 100002;
      font-size: 14px;
    `;
    toast.textContent = '⏳ 正在提交处理任务...';
    document.body.appendChild(toast);
    window._processLoadingToast = toast;
  }

  try {
    const body = {
      workflow_path: workflowPath,
      ...window.workflowExtraBody(),
      orientation: window.currentOrientation,
      quality: window.getQuality(),
    };

    const data = await window.api(`/api/history/${item.id}/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    // 移除loading toast
    if (window._processLoadingToast) {
      window._processLoadingToast.remove();
      window._processLoadingToast = null;
    }

    window.showToast(`已提交处理任务 (job ${data.job_id})`, 'success');
    if (data.job_id) window.trackJob(data.job_id);
  } catch (e) {
    // 移除loading toast
    if (window._processLoadingToast) {
      window._processLoadingToast.remove();
      window._processLoadingToast = null;
    }

    window.showToast('处理失败: ' + e.message, 'error');
  } finally {
    // 恢复按钮状态
    window._processBtnLoading = false;
    if (processBtn) {
      processBtn.disabled = false;
      processBtn.style.opacity = '1';
      processBtn.innerHTML = '⚡'; // 恢复 original 图标
      processBtn.title = '投喂给工作流处理（超分/重绘等）';
    }
  }
};

// -------------------------------------------------------------------
// 缩放和拖拽交互
// -------------------------------------------------------------------

window._imageStates = [];
window._activeImageIdx = 0;

window._initImageState = function(img, wrap) {
  const nW = img.naturalWidth, nH = img.naturalHeight;
  const cW = wrap.clientWidth, cH = wrap.clientHeight;
  if (!nW || !nH || !cW || !cH) return null;

  const fitScale = Math.min(cW / nW, cH / nH);
  const x = (cW - nW * fitScale) / 2;
  const y = (cH - nH * fitScale) / 2;

  return {
    scale: fitScale, x, y,
    targetScale: fitScale, targetX: x, targetY: y,
    anchorX: 0, anchorY: 0, rafId: null,
    flipX: false,
    rotation: 0,
    fitScale: fitScale
  };
};

window._applyTransform = function(img, state) {
  const flip = state.flipX ? -1 : 1;
  img.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale * flip}, ${state.scale})`;
  img.style.transformOrigin = '0 0';
};

window._applyRotation = function(wrap, state) {
  const rot = state.rotation || 0;
  wrap.style.transform = `rotate(${rot}deg)`;
  wrap.style.transformOrigin = 'center center';
};

window._constrain = function(state, wrap, img) {
  const imgW = img.naturalWidth * state.scale;
  const imgH = img.naturalHeight * state.scale;
  const cW = wrap.clientWidth;
  const cH = wrap.clientHeight;

  const RATIO = 0.15;
  const keepW = Math.max(Math.min(imgW, cW) * RATIO, 20);
  const keepH = Math.max(Math.min(imgH, cH) * RATIO, 20);

  state.x = Math.max(keepW - imgW, Math.min(cW - keepW, state.x));
  state.y = Math.max(keepH - imgH, Math.min(cH - keepH, state.y));
};

window._updateZoomDisplay = function() {
  const zd = document.getElementById('compareZoomDisplay');
  if (!zd) return;
  for (let i = 0; i < window._imageStates.length; i++) {
    if (window._imageStates[i]) {
      zd.textContent = Math.round(window._imageStates[i].scale * 100) + '%';
      return;
    }
  }
  zd.textContent = '100%';
};

window._cancelAllAnimations = function() {
  window._imageStates.forEach(s => {
    if (s && s.rafId) { cancelAnimationFrame(s.rafId); s.rafId = null; }
  });
};

window._destroyAllViewers = function() {
  window._cancelAllAnimations();
  window._imageStates = [];
  document.querySelectorAll('#compareModalBody .compare-img').forEach(img => {
    img.style.transform = '';
    img.style.transformOrigin = '';
  });
  document.querySelectorAll('#compareModalBody .compare-item-wrap').forEach(wrap => {
    wrap.style.transform = '';
  });
};

window._startZoomAnim = function(idx, img, wrap) {
  const state = window._imageStates[idx];
  if (!state) return;
  if (state.rafId) return;

  const LERP = 0.35;

  function tick() {
    state.rafId = null;

    const ds = state.targetScale - state.scale;
    const dx = state.targetX - state.x;
    const dy = state.targetY - state.y;

    if (Math.abs(ds) < 0.0001 && Math.abs(dx) < 0.1 && Math.abs(dy) < 0.1) {
      state.scale = state.targetScale;
      state.x = state.targetX;
      state.y = state.targetY;
      window._constrain(state, wrap, img);
      window._applyTransform(img, state);
      window._updateZoomDisplay();
      return;
    }

    state.scale += ds * LERP;
    state.x += dx * LERP;
    state.y += dy * LERP;
    window._constrain(state, wrap, img);
    window._applyTransform(img, state);

    state.rafId = requestAnimationFrame(tick);
  }

  state.rafId = requestAnimationFrame(tick);
};

window._calcZoomTarget = function(state, wrap, img, targetScale, mouseX, mouseY) {
  const imgX = (mouseX - state.x) / state.scale;
  const imgY = (mouseY - state.y) / state.scale;

  const targetX = mouseX - imgX * targetScale;
  const targetY = mouseY - imgY * targetScale;

  const preview = { x: targetX, y: targetY, scale: targetScale };
  window._constrain(preview, wrap, img);

  return { targetX: preview.x, targetY: preview.y };
};

window._bindCompareInteractions = function(body) {
  window._destroyAllViewers();

  const wraps = body.querySelectorAll('.compare-item-wrap');
  wraps.forEach((wrap, idx) => {
    const img = wrap.querySelector('.compare-img');
    if (!img) return;

    const initState = () => {
      const s = window._initImageState(img, wrap);
      if (!s) return;
      while (window._imageStates.length <= idx) window._imageStates.push(null);
      window._imageStates[idx] = s;
      window._applyTransform(img, s);
      window._applyRotation(wrap, s);
      window._updateZoomDisplay();
    };
    if (img.complete && img.naturalWidth > 0) {
      initState();
    } else {
      img.addEventListener('load', initState);
    }

    wrap.addEventListener('wheel', (e) => {
      e.preventDefault();
      const state = window._imageStates[idx];
      if (!state) return;

      const curScale = state.scale;
      const zoomDelta = -e.deltaY * 0.002;
      const targetScale = Math.max(0.05, Math.min(20, curScale * Math.exp(zoomDelta)));

      const rect = wrap.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const { targetX, targetY } = window._calcZoomTarget(state, wrap, img, targetScale, mx, my);

      state.targetScale = targetScale;
      state.targetX = targetX;
      state.targetY = targetY;
      state.anchorX = mx;
      state.anchorY = my;

      window._startZoomAnim(idx, img, wrap);

      if (window._compareMode === 'sync') {
        window._syncTargetZoom(idx, targetScale, wrap, img, mx, my);
      }
    }, { passive: false });

    let isDragging = false;
    let dragStartX, dragStartY, dragStateX, dragStateY;
    let dragOtherSnap = null;

    const onDragMove = (e) => {
      if (!isDragging) return;
      const state = window._imageStates[idx];
      if (!state) return;
      let deltaX = (e.clientX - dragStartX);
      let deltaY = (e.clientY - dragStartY);

      // 根据翻转和旋转状态调整拖拽方向
      const rot = state.rotation % 360;
      if (state.flipX) deltaX = -deltaX;
      if (rot === 90) {
        const tmp = deltaX;
        deltaX = deltaY;
        deltaY = -tmp;
      } else if (rot === 180) {
        deltaX = -deltaX;
        deltaY = -deltaY;
      } else if (rot === 270) {
        const tmp = deltaX;
        deltaX = -deltaY;
        deltaY = tmp;
      }

      state.x = dragStateX + deltaX;
      state.y = dragStateY + deltaY;
      state.targetX = state.x;
      state.targetY = state.y;
      window._constrain(state, wrap, img);
      window._applyTransform(img, state);

      if (window._compareMode === 'sync' && dragOtherSnap) {
        window._imageStates.forEach((otherState, otherIdx) => {
          if (otherIdx === idx || !otherState || !dragOtherSnap[otherIdx]) return;
          const otherImg = document.querySelectorAll('#compareModalBody .compare-img')[otherIdx];
          const otherWrap = otherImg ? otherImg.closest('.compare-item-wrap') : null;
          if (!otherImg || !otherWrap) return;
          otherState.x = dragOtherSnap[otherIdx].x + deltaX;
          otherState.y = dragOtherSnap[otherIdx].y + deltaY;
          otherState.targetX = otherState.x;
          otherState.targetY = otherState.y;
          window._constrain(otherState, otherWrap, otherImg);
          window._applyTransform(otherImg, otherState);
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
      const state = window._imageStates[idx];
      if (!state) return;
      window._activeImageIdx = idx;
      isDragging = true;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      dragStateX = state.x;
      dragStateY = state.y;
      window._cancelAllAnimations();
      dragOtherSnap = {};
      if (window._compareMode === 'sync') {
        window._imageStates.forEach((os, oi) => {
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
};

window._syncTargetZoom = function(sourceIdx, targetScale, sourceWrap, sourceImg, mx, my) {
  window._imageStates.forEach((state, idx) => {
    if (idx === sourceIdx || !state) return;

    const img = document.querySelectorAll('#compareModalBody .compare-img')[idx];
    const wrap = img ? img.closest('.compare-item-wrap') : null;
    if (!img || !wrap) return;

    state.targetScale = targetScale;
    state.anchorX = mx;
    state.anchorY = my;

    const wrapRect = wrap.getBoundingClientRect();
    const sourceRect = sourceWrap.getBoundingClientRect();
    const relX = sourceRect.width > 0 ? (mx / sourceRect.width) : 0.5;
    const relY = sourceRect.height > 0 ? (my / sourceRect.height) : 0.5;
    const localX = wrapRect.width * relX;
    const localY = wrapRect.height * relY;

    const { targetX, targetY } = window._calcZoomTarget(state, wrap, img, targetScale, localX, localY);
    state.targetX = targetX;
    state.targetY = targetY;

    window._startZoomAnim(idx, img, wrap);
  });
};

// -------------------------------------------------------------------
// 对比模式设置
// -------------------------------------------------------------------

window.setCompareMode = function(mode) {
  window._compareMode = mode;
  const btn1 = document.getElementById('compareSyncBtn2');
  const btn2 = document.getElementById('compareSplitBtn2');
  if (btn1) btn1.classList.toggle('active', mode === 'sync');
  if (btn2) btn2.classList.toggle('active', mode === 'split');
  const oBtn1 = document.getElementById('compareSyncBtn');
  const oBtn2 = document.getElementById('compareSplitBtn');
  if (oBtn1) oBtn1.classList.toggle('active', mode === 'sync');
  if (oBtn2) oBtn2.classList.toggle('active', mode === 'split');
};

window.openCompareLightbox = function() {
  if (!window._compareItems.length) return;
  window.openCompareModal();
};

window.resetImageZoom = function() {
  window._cancelAllAnimations();

  const wraps = document.querySelectorAll('#compareModalBody .compare-item-wrap');
  wraps.forEach((wrap, idx) => {
    const img = wrap.querySelector('.compare-img');
    if (!img) return;

    const doReset = () => {
      const s = window._initImageState(img, wrap);
      if (!s) return;
      while (window._imageStates.length <= idx) window._imageStates.push(null);
      window._imageStates[idx] = s;
      window._applyTransform(img, s);
    };

    if (img.complete && img.naturalWidth > 0) {
      doReset();
    } else {
      img.removeEventListener('load', img._resetHandler);
      img._resetHandler = doReset;
      img.addEventListener('load', doReset);
    }
  });
  window._updateZoomDisplay();
};

// -------------------------------------------------------------------
// 键盘导航
// -------------------------------------------------------------------

window.setupImageModalKeyboardNav = function() {
  const overlay = document.getElementById('compareModal');
  if (!overlay) return;
  
  overlay.removeEventListener('keydown', overlay._keyboardNavHandler);
  
  overlay._keyboardNavHandler = (e) => {
    if (e.key === 'ArrowLeft' && window._lightboxIndex > 0) {
      window._lightboxIndex--;
      window.renderUnifiedImageGrid();
      window.updateImageModalTitle();
    } else if (e.key === 'ArrowRight' && window._lightboxIndex < window._lightboxItems.length - 1) {
      window._lightboxIndex++;
      window.renderUnifiedImageGrid();
      window.updateImageModalTitle();
    }
  };
  
  overlay.addEventListener('keydown', overlay._keyboardNavHandler);
};

window.updateImageModalTitle = function() {
  const titleText = document.getElementById('imageModalTitleText');
  if (titleText && window._compareMode === 'single') {
    titleText.textContent = `图片查看（${window._lightboxIndex + 1} / ${window._lightboxItems.length}）`;
  }
};

// -------------------------------------------------------------------
// 图片编辑功能
// -------------------------------------------------------------------

window.flipImage = function() {
  const idx = window._activeImageIdx || 0;
  const state = window._imageStates[idx];
  if (!state) return;
  state.flipX = !state.flipX;
  const img = document.querySelectorAll('#compareModalBody .compare-img')[idx];
  if (img) window._applyTransform(img, state);
};

window.rotateImage = function() {
  const idx = window._activeImageIdx || 0;
  const state = window._imageStates[idx];
  if (!state) return;
  state.rotation = (state.rotation + 90) % 360;

  const img = document.querySelectorAll('#compareModalBody .compare-img')[idx];
  const wrap = document.querySelectorAll('#compareModalBody .compare-item-wrap')[idx];
  if (!img || !wrap) return;

  const nW = img.naturalWidth, nH = img.naturalHeight;
  const cW = wrap.clientWidth, cH = wrap.clientHeight;

  const isRotated = (state.rotation % 360 === 90 || state.rotation % 360 === 270);
  const effectiveW = isRotated ? nH : nW;
  const effectiveH = isRotated ? nW : nH;

  state.fitScale = Math.min(cW / effectiveW, cH / effectiveH);
  state.scale = state.fitScale;
  state.x = (cW - effectiveW * state.fitScale) / 2;
  state.y = (cH - effectiveH * state.fitScale) / 2;
  state.targetScale = state.scale;
  state.targetX = state.x;
  state.targetY = state.y;

  window._applyTransform(img, state);
  window._applyRotation(wrap, state);
  window._updateZoomDisplay();
};

window.toggleFitMode = function() {
  const idx = window._activeImageIdx || 0;
  const state = window._imageStates[idx];
  if (!state) return;
  const img = document.querySelectorAll('#compareModalBody .compare-img')[idx];
  const wrap = document.querySelectorAll('#compareModalBody .compare-item-wrap')[idx];
  if (!img || !wrap) return;

  const btn = document.getElementById('imageFitBtn');
  const isFit = Math.abs(state.scale - state.fitScale) < 0.01;

  if (isFit) {
    state.scale = 1;
    state.x = (wrap.clientWidth - img.naturalWidth) / 2;
    state.y = (wrap.clientHeight - img.naturalHeight) / 2;
    if (btn) btn.textContent = '适应';
  } else {
    state.scale = state.fitScale;
    state.x = (wrap.clientWidth - img.naturalWidth * state.fitScale) / 2;
    state.y = (wrap.clientHeight - img.naturalHeight * state.fitScale) / 2;
    if (btn) btn.textContent = '1:1';
  }
  state.targetScale = state.scale;
  state.targetX = state.x;
  state.targetY = state.y;
  window._applyTransform(img, state);
  window._updateZoomDisplay();
};

// -------------------------------------------------------------------
// 灯箱图片切换
// -------------------------------------------------------------------

window.prevLightboxImage = function() {
  if (window._lightboxIndex > 0) {
    window._lightboxIndex--;
    window._lightboxRouteReplace = true;
    window.renderUnifiedImageGrid();
    window.updateImageModalTitle();
  }
};

window.nextLightboxImage = function() {
  if (window._lightboxIndex < window._lightboxItems.length - 1) {
    window._lightboxIndex++;
    window._lightboxRouteReplace = true;
    window.renderUnifiedImageGrid();
    window.updateImageModalTitle();
  }
};

// -------------------------------------------------------------------
// 灯箱状态持久化
// -------------------------------------------------------------------

window.saveLightboxState = function() {
  try {
    const state = {
      mode: window._compareMode,
      lightboxIndex: window._lightboxIndex,
      lightboxItems: window._lightboxItems,
      compareItems: window._compareItems
    };
    sessionStorage.setItem('pb_lightbox_state', JSON.stringify(state));
  } catch (e) { }
};

window.clearLightboxState = function() {
  try { sessionStorage.removeItem('pb_lightbox_state'); } catch (e) {}
};

window.restoreLightboxState = function() {
  try {
    const raw = sessionStorage.getItem('pb_lightbox_state');
    if (!raw) return;
    const state = JSON.parse(raw);
    if (!state || !state.mode) return;

    window._compareMode = state.mode;
    window._lightboxIndex = state.lightboxIndex || 0;
    window._lightboxItems = state.lightboxItems || [];
    window._compareItems = state.compareItems || [];

    if (window._lightboxItems.length > 0 || window._compareItems.length > 0) {
      window.openUnifiedImageModal();
    }
  } catch (e) {
    window.clearLightboxState();
  }
};

// -------------------------------------------------------------------
// 旧版灯箱兼容
// -------------------------------------------------------------------

window.openLightbox = function(src, meta, event, clickedIndex) {
  // Phase 5: Viewer.js 作为备选（保留原有弹窗主流程不变）
  // 只有在 Viewer.js 可用、且是单图且 ctrl 键按下时使用
  if (typeof Viewer !== "undefined" && clickedIndex < 0 && event && (event.ctrlKey || event.metaKey)) {
    const img = new Image();
    img.onload = () => { window.viewImageWithViewer(img); };
    img.onerror = () => { window._openLightboxLegacy(src, meta, event, clickedIndex); };
    img.src = src;
    return;
  }
  window._openLightboxLegacy(src, meta, event, clickedIndex);
};

/** 旧版灯箱 */
window._openLightboxLegacy = function(src, meta, event, clickedIndex) {
  const allItems = (window._galleryAllItems || window._historyItems).map((item) => {
    return {
      ...item,
      view_url: item.view_url || `/api/image?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}`
    };
  });

  window._lightboxItems = allItems;
  window._lightboxIndex = clickedIndex >= 0 ? clickedIndex : 0;
  window._compareMode = 'single';

  window.openUnifiedImageModal();
};

window.pswpLightbox = null;

// ====================================================================
// Phase 5: Viewer.js 增强 —— 单图查看使用 Viewer.js
// ====================================================================

/** 初始化 Viewer.js 查看单张图片（替代旧的 zoom/pan 手写逻辑） */
window.viewImageWithViewer = function(imgElement) {
  if (typeof Viewer === "undefined") {
    // Viewer.js 未加载，回退到旧方式
    return false;
  }
  // 如果已有 viewer 实例，先销毁
  if (window._viewerInstance) {
    window._viewerInstance.destroy();
    window._viewerInstance = null;
  }
  const viewer = new Viewer(imgElement, {
    inline: false,
    viewed() {
      window._viewerInstance = viewer;
    },
    hidden() {
      if (window._viewerInstance === viewer) {
        window._viewerInstance = null;
      }
    },
    toolbar: {
      zoomIn: 1,
      zoomOut: 1,
      oneToOne: 1,
      reset: 1,
      rotateLeft: 1,
      rotateRight: 1,
      flipHorizontal: 1,
      flipVertical: 1,
    },
    title: false,  // 由我们自己的 header 提供标题
    navbar: false,
  });
  viewer.show();
  return true;
};
