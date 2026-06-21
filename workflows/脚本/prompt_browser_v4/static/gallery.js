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

    const favClass = item.favorite ? 'active' : '';
    const favChar = item.favorite ? '★' : '☆';
    const hasPrompt = item.prompt_id != null;

    div.innerHTML = `
      <img src="${thumbUrl}" alt=""
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
      <div class="gallery-item-placeholder" style="display:none;width:100%;aspect-ratio:1;background:var(--panel-2);align-items:center;justify-content:center;color:var(--muted);font-size:32px">🖼️</div>
      <button class="gallery-item-fav ${favClass}" onclick="event.stopPropagation();window.toggleFavorite(${item.id},this)" title="收藏">${favChar}</button>
      ${item.prompt_name ? `<div class="gallery-item-prompt" onclick="event.stopPropagation();window.jumpToPrompt(${item.prompt_id})">📝 ${window.escHtml(item.prompt_name)}</div>` : ""}
      <div class="gallery-item-check" data-id="${item.id}"></div>
      <div class="gallery-item-actions">
        ${hasPrompt ? `<button class="gallery-item-regen" onclick="event.stopPropagation();window.regenerateFromHistory(${item.prompt_id})" title="重新生成">🔄</button>` : ""}
        <button class="gallery-item-dl" onclick="event.stopPropagation();window.downloadHistoryItem(${item.id})" title="下载">⬇️</button>
      </div>
      <div class="gallery-item-meta">${meta}</div>
    `;

    const checkEl = div.querySelector('.gallery-item-check');
    checkEl.onclick = (e) => {
      e.stopPropagation();
      window.toggleGalleryItem(item.id, checkEl);
    };

    div.onclick = () => {
      if (window._gallerySelectedIds.size > 0) {
        window.toggleGalleryItem(item.id, checkEl);
      } else {
        window.openLightbox(item.view_url, meta, null, idx);
      }
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
    if (window._gallerySelectedIds.size >= 4) {
      window.showToast('最多只能选择 4 张图片进行对比', 'error');
      return;
    }
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
  } else {
    btn.style.display = 'none';
  }
};

window.enterCompareMode = function() {
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
