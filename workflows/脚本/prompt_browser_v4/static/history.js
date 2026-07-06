// history.js - 历史管理模块
// 依赖：utils.js, gallery.js

window._historyItems = [];
window._promptHistoryItems = [];
window._galleryPage = 1;
window._galleryTotal = 0;
window._galleryLoading = false;

// -------------------------------------------------------------------
// 历史加载（分页：复用画廊分页组件）
// -------------------------------------------------------------------

window.loadHistory = async function(sync = false) {
  // Phase 2: HTMX 模式 —— 画廊由 HTMX 自动加载
  if (document.body.dataset.htmxActive === "1") {
    if (!sync) {
      document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
    }
    return;
  }

  try {
    if (sync) {
      // 同步并加载第一页
      const url = `/api/history_sync?page_size=${window._galleryPageSize}`;
      const data = await window.api(url);
      window._galleryAllItems = data.items || [];
      window._historyItems = window._galleryAllItems;
      window._galleryTotal = data.total || window._galleryAllItems.length;
      window._galleryPage = 1;
      window.renderGallery(window._historyItems);
      window.renderGalleryPagination();
      window.updateGalleryBadge();
      return;
    }

    // 普通加载：重置为第一页
    window._galleryPage = 1;
    window._galleryAllItems = [];
    window._historyItems = [];
    await window._loadHistoryPage();
  } catch (e) {
    console.error("loadHistory", e);
  }
};

window._loadHistoryPage = async function() {
  if (window._galleryLoading) return;
  window._galleryLoading = true;
  try {
    const params = [
      `page=${window._galleryPage}`,
      `page_size=${window._galleryPageSize}`,
    ];
    if (window._galleryFilter === "favorite") params.push("favorite=1");
    if (window._gallerySort) params.push(`sort=${window._gallerySort}`);
    if (window._gallerySearch) params.push(`search=${encodeURIComponent(window._gallerySearch)}`);
    const url = "/api/history?" + params.join("&");
    const data = await window.api(url);
    const items = data.items || [];
    window._galleryTotal = data.total || 0;
    window._historyItems = items;

    // 累积所有已加载页，供灯箱 / 对比跨页使用
    if (!window._galleryAllItems) window._galleryAllItems = [];
    const seen = new Set(window._galleryAllItems.map(it => it.id));
    for (const it of items) {
      if (!seen.has(it.id)) { window._galleryAllItems.push(it); seen.add(it.id); }
    }

    window.renderGallery(items);
    window.renderGalleryPagination();
    window.updateGalleryBadge();
  } catch (e) {
    console.error("_loadHistoryPage", e);
  } finally {
    window._galleryLoading = false;
  }
};

// 切换每页显示条数（与提示词分页组件同一交互）
window.changeGalleryPageSize = function(size) {
  if (size === window._galleryPageSize) return;
  window._galleryPageSize = size;
  window._galleryPage = 1;
  window.UiState.set("galleryPageSize", size);
  if (document.body.dataset.htmxActive === "1") {
    document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
  } else {
    window.loadHistory(false);
  }
};

// 跳转到指定页（JS 模式直接加载；HTMX 模式由模板按钮驱动，此处兜底刷新）
window.loadGalleryPage = function(page) {
  if (!page || page < 1) return;
  window._galleryPage = page;
  if (document.body.dataset.htmxActive === "1") {
    const container = document.getElementById("galleryGridContainer");
    if (container) {
      const params = new URLSearchParams({
        page: String(page),
        sort: window._gallerySort,
        favorite: window._galleryFilter === "favorite" ? "1" : "",
        search: window._gallerySearch,
        page_size: String(window._galleryPageSize),
      });
      container.setAttribute("hx-get", "/api/history/html?" + params.toString());
      document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
    }
  } else {
    window._loadHistoryPage();
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

window.jumpToPrompt = async function(promptId) {
  window.closeCompareModal();
  
  window._suppressRouteUpdate = true;
  const tabBtn = document.querySelector('.tab-btn[data-tab="promptTab"]');
  if (tabBtn) window.switchTab("promptTab", tabBtn);
  
  // 确保目标提示词在列表中：清空搜索和分类，加载所有提示词
  const searchEl = document.getElementById("searchInput");
  if (searchEl) searchEl.value = "";
  window._currentCategoryId = null;
  window._promptPageSize = 200;
  window._promptPage = 1;
  await window.loadPrompts();
  
  // 计算目标在第几页，加载到对应页
  const idx = window.allPrompts.findIndex(p => p.id === promptId);
  if (idx >= 0) {
    window._promptPageSize = 50;
    window._promptPage = Math.floor(idx / window._promptPageSize) + 1;
    await window.loadPrompts();
  }
  
  window.selectPrompt(promptId, true, false, false, false);
  
  // 滚动到目标
  setTimeout(() => {
    const item = document.querySelector(`.prompt-item[data-id="${promptId}"]`);
    if (item) item.scrollIntoView({ block: "center", behavior: "smooth" });
  }, 300);
  
  window._suppressRouteUpdate = false;
  window.updateRoute();
};

// -------------------------------------------------------------------
// 提示词历史
// -------------------------------------------------------------------

window.loadPromptHistory = async function(promptId) {
  const section = document.getElementById("promptHistorySection");
  if (!section) return;
  // 先隐藏，请求完成后再决定是否显示
  section.classList.remove("visible");
  section.innerHTML = "";
  try {
    const data = await window.api(`/api/prompts/${promptId}/history`);
    const items = data.items || [];
    window._promptHistoryItems = items;
    if (!items.length) return;  // 无数据，保持隐藏
    section.classList.add("visible");
    section.innerHTML = '<h3>🖼️ 生成历史</h3><div class="prompt-history-grid" id="promptHistoryGrid"></div>';
    const grid = document.getElementById("promptHistoryGrid");
    if (!grid) return;
    items.forEach((item, idx) => {
      const wrap = document.createElement("div");
      wrap.className = "prompt-history-item";

      const img = document.createElement("img");
      img.className = "prompt-history-thumb";
      img.src = `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || "")}&type=${encodeURIComponent(item.img_type || "output")}&size=400`;
      img.alt = item.filename;
      img.title = item.filename + (item.created_at ? "\n" + item.created_at : "");
      img.onclick = () => window.openPromptHistoryLightbox(idx);
      wrap.appendChild(img);

      const delBtn = document.createElement("button");
      delBtn.className = "hist-del";
      delBtn.textContent = "✕";
      delBtn.title = "删除";
      delBtn.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm("删除此图片的历史记录？")) return;
        try {
          await window.api(`/api/history/${item.id}`, { method: "DELETE" });
          window.loadPromptHistory(promptId);
          if (typeof window.loadHistory === "function") window.loadHistory(false);
        } catch (err) {
          window.showToast("删除失败: " + err.message, "error");
        }
      };
      wrap.appendChild(delBtn);

      grid.appendChild(wrap);
    });
  } catch (e) {
    section.classList.add("visible");
    section.innerHTML = '<h3>🖼️ 生成历史</h3><div class="prompt-history-grid" id="promptHistoryGrid"><div class="empty-tip" style="font-size:12px;color:var(--danger)">加载失败</div></div>';
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
      window.showToast("已删除", "success");
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
      window.showToast("已清空历史", "success");
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
      const item = (window._galleryAllItems || window._historyItems).find(it => it.id === id);
      if (item) item.favorite = r.favorite;
      const lbItem = window._lightboxItems.find(it => it && it.id === id);
      if (lbItem) lbItem.favorite = r.favorite;
      if (btn) {
        btn.classList.toggle('active', r.favorite);
        btn.textContent = r.favorite ? '★' : '☆';
        // 添加视觉反馈
        btn.style.transform = "scale(1.3)";
        setTimeout(() => {
          btn.style.transform = "";
        }, 300);
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
  const btn = document.getElementById('galleryBatchDel');
  if (btn) window.showButtonFeedback(btn, '🗑️ 删除中...', 2000);
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

/** 批量跑图：对每个选中的历史图片调用工作流处理 */
window.batchProcessHistory = async function() {
  const ids = Array.from(window._gallerySelectedIds);
  if (!ids.length) return;
  const wfPath = window._currentWorkflow || "";
  if (!wfPath) { window.showToast("请先选择工作流", "warn"); return; }
  const btn = document.getElementById('galleryBatchProcess');
  if (btn) window.showButtonFeedback(btn, '✨ 提交中...', 3000);
  let submitted = 0;
  for (const id of ids) {
    try {
      const r = await window.api(`/api/history/${id}/process`, {
        method: "POST",
        body: JSON.stringify({ workflow_path: wfPath }),
        headers: { "Content-Type": "application/json" },
      });
      if (r.success) {
        submitted++;
        window.trackJob(r.job_id);
      }
    } catch (e) {
      console.error(`批量跑图 #${id} 失败:`, e);
    }
  }
  window.showToast(`已提交 ${submitted} 个处理任务`, 'info');
};

window.downloadHistoryItem = function(id) {
  const a = document.createElement('a');
  a.href = `/api/history/${id}/download`;
  a.target = '_blank';
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.showToast('已开始下载', 'info');
};

window.batchDownloadHistory = async function() {
  const ids = Array.from(window._gallerySelectedIds);
  if (!ids.length) return;
  const btn = document.getElementById('galleryBatchDl');
  if (btn) window.showButtonFeedback(btn, '⬇️ 下载中...', 3000);
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

/** 画廊搜索/排序/筛选变化时清空选中的 item */
window._clearGallerySelection = function() {
  window._gallerySelectedIds.clear();
  document.querySelectorAll('.gallery-item-check').forEach(el => el.classList.remove('checked'));
  window.updateGalleryActionButtons();
  window.updateCompareButton();
  const allCheck = document.getElementById('gallerySelectAll');
  if (allCheck) { allCheck.checked = false; allCheck.indeterminate = false; }
};

window.onGallerySearch = function() {
  clearTimeout(window._gallerySearchTimer);
  window._gallerySearchTimer = setTimeout(() => {
    window._gallerySearch = document.getElementById('gallerySearch').value;
    window._clearGallerySelection();
    if (document.body.dataset.htmxActive === "1") {
      document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
    } else {
      window.loadHistory(false);
    }
  }, 300);
};

window.onGallerySortChange = function() {
  window._gallerySort = document.getElementById('gallerySort').value;
  window._clearGallerySelection();
  if (document.body.dataset.htmxActive === "1") {
    document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
  } else {
    window.loadHistory(false);
  }
};

window.onGalleryFilterChange = function() {
  window._galleryFilter = document.getElementById('galleryFilter').value;
  window._clearGallerySelection();
  if (document.body.dataset.htmxActive === "1") {
    document.body.dispatchEvent(new CustomEvent("galleryRefresh"));
  } else {
    window.loadHistory(false);
  }
};

window.updateGalleryActionButtons = function() {
  const count = window._gallerySelectedIds.size;
  const batchDel = document.getElementById('galleryBatchDel');
  const batchDl = document.getElementById('galleryBatchDl');
  const batchProc = document.getElementById('galleryBatchProcess');
  if (batchDel) batchDel.style.display = count >= 1 ? 'inline-flex' : 'none';
  if (batchDl) batchDl.style.display = count >= 1 ? 'inline-flex' : 'none';
  if (batchProc) batchProc.style.display = count >= 1 ? 'inline-flex' : 'none';
  window.updateCompareButton();
  window.updateGallerySelectAllCheck();
};
