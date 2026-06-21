// history.js - 历史管理模块
// 依赖：utils.js, gallery.js

window._historyItems = [];
window._promptHistoryItems = [];

// -------------------------------------------------------------------
// 历史加载
// -------------------------------------------------------------------

window.loadHistory = async function(sync = false) {
  try {
    let url;
    if (sync) {
      url = "/api/history_sync";
    } else {
      url = "/api/history?";
      const params = [];
      if (window._galleryFilter === "favorite") params.push("favorite=1");
      if (window._gallerySort) params.push(`sort=${window._gallerySort}`);
      if (window._gallerySearch) params.push(`search=${encodeURIComponent(window._gallerySearch)}`);
      url += params.join("&");
    }
    const data = await window.api(url);
    window._historyItems = data.items || [];
    window.renderGallery(window._historyItems);
    window.updateGalleryBadge();
  } catch (e) {
    console.error("loadHistory", e);
  }
};

window.renderHistory = function(items) {
  // 底部历史条已移除，此函数保留但不再渲染
};

window.buildImageMeta = function(item) {
  const parts = [];
  if (item.width && item.height) parts.push(item.width + "×" + item.height);
  if (item.file_size) parts.push(window.formatFileSize(item.file_size));
  return parts.join(" · ");
};

window.jumpToPrompt = function(promptId) {
  window.closeCompareModal();
  
  window._suppressRouteUpdate = true;
  const tabBtn = document.querySelector('.tab-btn[data-tab="promptTab"]');
  if (tabBtn) window.switchTab("promptTab", tabBtn);
  window.selectPrompt(promptId, true, false, false, false);
  window._suppressRouteUpdate = false;
  
  window.updateRoute();
};

// -------------------------------------------------------------------
// 提示词历史
// -------------------------------------------------------------------

window.loadPromptHistory = async function(promptId) {
  const grid = document.getElementById("promptHistoryGrid");
  if (!grid) return;
  grid.innerHTML = '<div class="empty-tip" style="font-size:12px">加载中...</div>';
  try {
    const data = await window.api(`/api/prompts/${promptId}/history`);
    const items = data.items || [];
    window._promptHistoryItems = items;
    if (!items.length) {
      grid.innerHTML = '<div class="empty-tip" style="font-size:12px">暂无生成历史</div>';
      return;
    }
    grid.innerHTML = "";
    items.forEach((item, idx) => {
      const img = document.createElement("img");
      img.className = "prompt-history-thumb";
      img.src = `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || "")}&type=${encodeURIComponent(item.img_type || "output")}&size=120`;
      img.alt = item.filename;
      img.title = item.filename + (item.created_at ? "\n" + item.created_at : "");
      img.onclick = () => window.openPromptHistoryLightbox(idx);
      grid.appendChild(img);
    });
  } catch (e) {
    grid.innerHTML = '<div class="empty-tip" style="font-size:12px;color:var(--danger)">加载失败</div>';
  }
};

window.openPromptHistoryLightbox = function(clickedIdx) {
  if (!window._promptHistoryItems.length) return;
  window._lightboxItems = window._promptHistoryItems.map(item => ({
    ...item,
    view_url: item.view_url || `/api/image?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || "")}&type=${encodeURIComponent(item.img_type || "output")}`
  }));
  window._lightboxIndex = clickedIdx >= 0 ? clickedIdx : 0;
  window._compareMode = 'single';
  window.openUnifiedImageModal();
};

// -------------------------------------------------------------------
// 历史操作：删除/清空
// -------------------------------------------------------------------

window.deleteHistoryItem = async function(id) {
  return window.withLock("deleteHistoryItem_" + id, async () => {
    try {
      await window.api(`/api/history/${id}`, { method: "DELETE" });
      window.loadHistory(false);
    } catch (e) {
      window.showToast("删除失败: " + e.message, "error");
    }
  });
};

window.clearHistory = async function() {
  if (!confirm("确定清空全部历史吗？")) return;
  return window.withLock("clearHistory", async () => {
    try {
      await window.api("/api/history", { method: "DELETE" });
      window.loadHistory(false);
    } catch (e) {
      window.showToast("清空失败: " + e.message, "error");
    }
  });
};

// -------------------------------------------------------------------
// 历史操作：收藏/下载/重新生成
// -------------------------------------------------------------------

window.toggleFavorite = async function(id, btn) {
  try {
    const r = await window.api(`/api/history/${id}/favorite`, { method: "POST" });
    if (r.success) {
      const item = window._historyItems.find(it => it.id === id);
      if (item) item.favorite = r.favorite;
      const lbItem = window._lightboxItems.find(it => it && it.id === id);
      if (lbItem) lbItem.favorite = r.favorite;
      if (btn) {
        btn.classList.toggle('active', r.favorite);
        btn.textContent = r.favorite ? '★' : '☆';
      }
      if (window._compareMode === 'single') {
        const favBtn = document.getElementById('lightboxFavBtn');
        if (favBtn && window._lightboxItems[window._lightboxIndex] && window._lightboxItems[window._lightboxIndex].id === id) {
          favBtn.classList.toggle('active', r.favorite);
          favBtn.textContent = r.favorite ? '★' : '☆';
        }
      }
      window.showToast(r.favorite ? '已收藏' : '已取消收藏', 'info');
    }
  } catch (e) {
    window.showToast("操作失败: " + e.message, "error");
  }
};

window.toggleFavoriteFromLightbox = function() {
  const item = window._lightboxItems[window._lightboxIndex];
  if (!item) return;
  window.toggleFavorite(item.id, document.getElementById('lightboxFavBtn'));
};

window.batchDeleteHistory = async function() {
  const ids = Array.from(window._gallerySelectedIds);
  if (!ids.length) return;
  if (!confirm(`确定删除选中的 ${ids.length} 张图片吗？`)) return;
  try {
    const r = await window.api('/api/history/batch_delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    window.showToast(`已删除 ${r.deleted} 项`, 'success');
    window._gallerySelectedIds.clear();
    window.loadHistory(false);
  } catch (e) {
    window.showToast('批量删除失败: ' + e.message, 'error');
  }
};

window.downloadHistoryItem = function(id) {
  const a = document.createElement('a');
  a.href = `/api/history/${id}/download`;
  a.target = '_blank';
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
};

window.batchDownloadHistory = async function() {
  const ids = Array.from(window._gallerySelectedIds);
  if (!ids.length) return;
  window.showToast(`正在下载 ${ids.length} 张图片...`, 'info');
  for (const id of ids) {
    await window.downloadHistoryItem(id);
    await new Promise(r => setTimeout(r, 500));
  }
  window.showToast('下载完成', 'success');
};

window.regenerateFromHistory = async function(promptId) {
  if (!promptId) {
    window.showToast('该图片没有关联的提示词，无法重新生成', 'error');
    return;
  }
  const workflowPath = window.currentWorkflowPath();
  if (!workflowPath) {
    window.showToast('请先选择工作流', 'error');
    return;
  }
  if (window.comfyStatus !== 'online') {
    window.showToast('ComfyUI 离线，无法生成', 'error');
    return;
  }
  try {
    const body = {
      id: promptId,
      workflow_path: workflowPath,
      orientation: window.currentOrientation,
      quality: window.getQuality(),
    };
    const data = await window.api('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    window.showToast(`已重新生成 (job ${data.job_id})`, 'success');
    if (data.job_id) window.trackJob(data.job_id);
  } catch (e) {
    window.showToast('重新生成失败: ' + e.message, 'error');
  }
};

// -------------------------------------------------------------------
// 画廊：搜索/排序/筛选
// -------------------------------------------------------------------

window._gallerySearchTimer = null;

window.onGallerySearch = function() {
  clearTimeout(window._gallerySearchTimer);
  window._gallerySearchTimer = setTimeout(() => {
    window._gallerySearch = document.getElementById('gallerySearch').value;
    window.loadHistory(false);
  }, 300);
};

window.onGallerySortChange = function() {
  window._gallerySort = document.getElementById('gallerySort').value;
  window.loadHistory(false);
};

window.onGalleryFilterChange = function() {
  window._galleryFilter = document.getElementById('galleryFilter').value;
  window.loadHistory(false);
};

window.updateGalleryActionButtons = function() {
  const count = window._gallerySelectedIds.size;
  const batchDel = document.getElementById('galleryBatchDel');
  const batchDl = document.getElementById('galleryBatchDl');
  if (batchDel) batchDel.style.display = count >= 1 ? 'inline-flex' : 'none';
  if (batchDl) batchDl.style.display = count >= 1 ? 'inline-flex' : 'none';
  window.updateCompareButton();
};
