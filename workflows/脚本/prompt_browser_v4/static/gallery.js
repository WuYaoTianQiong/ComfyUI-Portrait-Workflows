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

  countEl.textContent = items.length;
  grid.innerHTML = '';

  items.forEach((item, idx) => {
    const div = document.createElement('div');
    div.className = 'gallery-item';
    div.dataset.id = item.id;
    div.dataset.index = idx;

    const thumbUrl = `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}&size=300`;

    const meta = window.buildImageMeta(item);
    const filename = item.filename || '';

    const favClass = item.favorite ? 'active' : '';
    const favChar = item.favorite ? '★' : '☆';
    const hasPrompt = item.prompt_id != null;
    // 组合创作的提示词：从 prompt_params 提取
    let composerPrompt = "";
    let isRandomComposer = false;
    if (item.prompt_params) {
      try {
        const pp = typeof item.prompt_params === "string" ? JSON.parse(item.prompt_params) : item.prompt_params;
        if (pp.source === "composer" && pp.prompt) {
          composerPrompt = pp.prompt.slice(0, 80) + (pp.prompt.length > 80 ? "…" : "");
        }
        if (pp.source === "composer_random") {
          isRandomComposer = true;
        }
      } catch(e) {}
    }

    // 动态计算提示词入口位置，避免重叠
    let badgeTop = 8;
    const promptBadges = [];
    if (item.prompt_name) {
      promptBadges.push(`<div class="gallery-item-prompt" style="top:${badgeTop}px" onclick="event.stopPropagation();window.jumpToPrompt(${item.prompt_id})">📝 ${window.escHtml(item.prompt_name)}</div>`);
      badgeTop += 30;
    }
    if (composerPrompt) {
      promptBadges.push(`<div class="gallery-item-prompt gallery-item-prompt-composer" style="top:${badgeTop}px" title="${window.escAttr(composerPrompt)}">🧩 ${window.escHtml(composerPrompt)}</div>`);
      badgeTop += 30;
    }
    if (isRandomComposer) {
      promptBadges.push(`<div class="gallery-item-prompt gallery-item-prompt-random" style="top:${badgeTop}px" onclick="event.stopPropagation();window.showRandomPromptDetail(${item.id})" title="点击查看随机组合详情">🎲 随机组合</div>`);
    }

    div.innerHTML = `
      <img src="${thumbUrl}" alt=""
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
      <div class="gallery-item-placeholder" style="display:none;width:100%;aspect-ratio:1;background:var(--panel-2);align-items:center;justify-content:center;color:var(--muted);font-size:32px">🖼️</div>
      <button class="gallery-item-fav ${favClass}" onclick="event.stopPropagation();window.toggleFavorite(${item.id},this)" title="收藏">${favChar}</button>
      ${promptBadges.join('')}
      <div class="gallery-item-check" data-id="${item.id}"></div>
      <div class="gallery-item-actions">
        ${hasPrompt ? `<button class="gallery-item-regen" onclick="event.stopPropagation();window.regenerateFromHistory(${item.prompt_id})" title="重新生成">🔄</button>` : ""}
        <button class="gallery-item-dl" onclick="event.stopPropagation();window.downloadHistoryItem(${item.id})" title="下载">⬇️</button>
      </div>
      <div class="gallery-item-meta">${meta}</div>
      <div class="gallery-item-filename" title="点击复制文件名" data-filename="${window.escAttr(filename)}">${window.escHtml(filename)}</div>
    `;

    const checkEl = div.querySelector('.gallery-item-check');
    checkEl.onclick = (e) => {
      e.stopPropagation();
      window.toggleGalleryItem(item.id, checkEl);
    };

    const filenameEl = div.querySelector('.gallery-item-filename');
    if (filenameEl) {
      filenameEl.onclick = (e) => {
        e.stopPropagation();
        window.copyFilename(filenameEl.dataset.filename);
      };
    }

    div.onclick = () => {
      const realIdx = window._historyItems.findIndex(it => it.id === item.id);
      window.openLightbox(item.view_url, meta, null, realIdx);
    };

    if (window._gallerySelectedIds.has(item.id)) {
      checkEl.classList.add('checked');
    }

    grid.appendChild(div);
  });

  window.updateGalleryActionButtons();
  window.updateCompareButton();
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

  window._compareItems = window._historyItems.filter(item => window._gallerySelectedIds.has(item.id));
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
// 分页：追加渲染 + 加载更多
// -------------------------------------------------------------------

window.appendGalleryItems = function(items) {
  const grid = document.getElementById('galleryGrid');
  const countEl = document.getElementById('galleryCount');
  if (!grid || !items || !items.length) return;

  countEl.textContent = window._historyItems.length;

  items.forEach((item, idx) => {
    const div = document.createElement('div');
    div.className = 'gallery-item';
    div.dataset.id = item.id;
    div.dataset.index = window._historyItems.length - items.length + idx;

    const thumbUrl = `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}&size=300`;

    const meta = window.buildImageMeta(item);
    const filename = item.filename || '';

    const favClass = item.favorite ? 'active' : '';
    const favChar = item.favorite ? '★' : '☆';
    const hasPrompt = item.prompt_id != null;
    let composerPrompt = "";
    let isRandomComposer = false;
    if (item.prompt_params) {
      try {
        const pp = typeof item.prompt_params === "string" ? JSON.parse(item.prompt_params) : item.prompt_params;
        if (pp.source === "composer" && pp.prompt) {
          composerPrompt = pp.prompt.slice(0, 80) + (pp.prompt.length > 80 ? "…" : "");
        }
        if (pp.source === "composer_random") {
          isRandomComposer = true;
        }
      } catch(e) {}
    }

    // 动态计算提示词入口位置，避免重叠
    let badgeTop = 8;
    const promptBadges = [];
    if (item.prompt_name) {
      promptBadges.push(`<div class="gallery-item-prompt" style="top:${badgeTop}px" onclick="event.stopPropagation();window.jumpToPrompt(${item.prompt_id})">📝 ${window.escHtml(item.prompt_name)}</div>`);
      badgeTop += 30;
    }
    if (composerPrompt) {
      promptBadges.push(`<div class="gallery-item-prompt gallery-item-prompt-composer" style="top:${badgeTop}px" title="${window.escAttr(composerPrompt)}">🧩 ${window.escHtml(composerPrompt)}</div>`);
      badgeTop += 30;
    }
    if (isRandomComposer) {
      promptBadges.push(`<div class="gallery-item-prompt gallery-item-prompt-random" style="top:${badgeTop}px" onclick="event.stopPropagation();window.showRandomPromptDetail(${item.id})" title="点击查看随机组合详情">🎲 随机组合</div>`);
    }

    div.innerHTML = `
      <img src="${thumbUrl}" alt=""
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
      <div class="gallery-item-placeholder" style="display:none;width:100%;aspect-ratio:1;background:var(--panel-2);align-items:center;justify-content:center;color:var(--muted);font-size:32px">🖼️</div>
      <button class="gallery-item-fav ${favClass}" onclick="event.stopPropagation();window.toggleFavorite(${item.id},this)" title="收藏">${favChar}</button>
      ${promptBadges.join('')}
      <div class="gallery-item-check" data-id="${item.id}"></div>
      <div class="gallery-item-actions">
        ${hasPrompt ? `<button class="gallery-item-regen" onclick="event.stopPropagation();window.regenerateFromHistory(${item.prompt_id})" title="重新生成">🔄</button>` : ""}
        <button class="gallery-item-dl" onclick="event.stopPropagation();window.downloadHistoryItem(${item.id})" title="下载">⬇️</button>
      </div>
      <div class="gallery-item-meta">${meta}</div>
      <div class="gallery-item-filename" title="点击复制文件名" data-filename="${window.escAttr(filename)}">${window.escHtml(filename)}</div>
    `;

    const checkEl = div.querySelector('.gallery-item-check');
    checkEl.onclick = (e) => {
      e.stopPropagation();
      window.toggleGalleryItem(item.id, checkEl);
    };

    const filenameEl = div.querySelector('.gallery-item-filename');
    if (filenameEl) {
      filenameEl.onclick = (e) => {
        e.stopPropagation();
        window.copyFilename(filenameEl.dataset.filename);
      };
    }

    div.onclick = () => {
      const realIdx = window._historyItems.findIndex(it => it.id === item.id);
      window.openLightbox(item.view_url, meta, null, realIdx);
    };

    if (window._gallerySelectedIds.has(item.id)) {
      checkEl.classList.add('checked');
    }

    grid.appendChild(div);
  });

  window.updateGalleryActionButtons();
  window.updateCompareButton();
};

window.updateGalleryLoadMore = function() {
  let indicator = document.getElementById('galleryLoadMore');
  const grid = document.getElementById('galleryGrid');
  if (!indicator && grid) {
    indicator = document.createElement('div');
    indicator.id = 'galleryLoadMore';
    indicator.className = 'gallery-load-more';
    grid.parentNode.insertBefore(indicator, null);
  }
  if (!indicator) return;
  const loaded = window._historyItems.length;
  const total = window._galleryTotal || 0;
  if (window._galleryLoading) {
    indicator.style.display = 'block';
    indicator.innerHTML = '<span style="color:var(--muted);font-size:12px">加载中...</span>';
  } else if (loaded >= total) {
    indicator.style.display = 'none';
  } else {
    indicator.style.display = 'block';
    indicator.innerHTML = `<span style="color:var(--muted);font-size:12px">滚动加载更多（${loaded} / ${total}）</span>`;
  }
};
