// prompt.js - 提示词模块
// 依赖：utils.js, ui.js, router.js

// -------------------------------------------------------------------
// 提示词列表和详情
// -------------------------------------------------------------------

window.loadPrompts = async function(page) {
  return window.withLock("loadPrompts", async () => {
    if (page) window._promptPage = page;
    const search = document.getElementById("searchInput").value;
    const sort = document.getElementById("sortFilter").value;

    const params = {
      search: search,
      sort: sort,
      page: window._promptPage,
      page_size: window._promptPageSize,
    };

    if (window._currentCategoryId !== null) {
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
      const totalEl = document.getElementById("countBadge");
      if (totalEl) totalEl.textContent = window._promptTotal;

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
      const data = await window.api("/api/templates/as_items");
      window.allPrompts = data.prompts || [];
      window._promptTotal = data.total || 0;
      window.renderList(window.allPrompts);
      window.renderPagination();
      const totalEl = document.getElementById("countBadge");
      if (totalEl) totalEl.textContent = window._promptTotal;
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

window.onSortChange = function() {
  window._promptPage = 1;
  window.loadPrompts();
  window.UiState.set("sortFilter", document.getElementById("sortFilter").value);
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

window.renderPagination = function() {
  const totalPages = Math.max(1, Math.ceil(window._promptTotal / window._promptPageSize));
  const el = document.getElementById("promptPagination");
  if (!el) return;
  if (totalPages <= 1) { el.innerHTML = ""; return; }

  let html = `<span class="page-info">第 ${window._promptPage}/${totalPages} 页，共 ${window._promptTotal} 条</span>`;
  html += `<button class="page-btn" ${window._promptPage <= 1 ? "disabled" : ""} onclick="window.loadPrompts(1)">«</button>`;
  html += `<button class="page-btn" ${window._promptPage <= 1 ? "disabled" : ""} onclick="window.loadPrompts(${window._promptPage - 1})">‹</button>`;

  let start = Math.max(1, window._promptPage - 2);
  let end = Math.min(totalPages, start + 4);
  start = Math.max(1, end - 4);
  for (let i = start; i <= end; i++) {
    html += `<button class="page-btn${i === window._promptPage ? " active" : ""}" onclick="window.loadPrompts(${i})">${i}</button>`;
  }

  html += `<button class="page-btn" ${window._promptPage >= totalPages ? "disabled" : ""} onclick="window.loadPrompts(${window._promptPage + 1})">›</button>`;
  html += `<button class="page-btn" ${window._promptPage >= totalPages ? "disabled" : ""} onclick="window.loadPrompts(${totalPages})">»</button>`;
  el.innerHTML = html;
};

window.selectPrompt = async function(id, fetchDetail = true, shiftKey = false, ctrlKey = false, isRestore = false) {
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
    categories.map(c => `<span class="tag" style="background:${c.color}20;color:${c.color};border:1px solid ${c.color}40">${window.escHtml(c.name)}</span>`).join("") :
    '<span style="color:#666;font-size:13px">未分类</span>';

  const tagsDetail = p.tags_detail || [];
  const tags = (p.tags || "").split(",").filter(Boolean);
  let tagHtml = '';
  if (tagsDetail.length > 0) {
    tagHtml = tagsDetail.map(t => `<span class="tag" style="background:${t.color}20;color:${t.color};border:1px solid ${t.color}40">${window.escHtml(t.name)}</span>`).join("");
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
      `<button id="detailFavBtn" class="btn btn-sm ${favClass}" onclick="window.togglePromptFavorite(${p.id}, this)" title="收藏">${favIcon}</button>` +
      `<button id="detailPinBtn" class="btn btn-sm ${pinClass}" onclick="window.togglePromptPin(${p.id}, this)" title="置顶">${pinIcon}</button>` +
      `<button class="btn btn-sm btn-warning" onclick="window.openVariationDialog()">🎲 变体</button>` +
      `<button class="btn btn-sm btn-warning" onclick="window.openEditModal(${p.id})">✏️ 编辑</button>` +
      `<button class="btn btn-sm btn-danger" onclick="window.deletePrompt(${p.id})">🗑️ 删除</button>` +
    `</div></div>${ratingHtml}${usageHtml}` : "") +
    `<div class="section"><h3>📝 正面提示词 <button class="copy-btn" onclick="window.copyPromptText(this,0)">复制</button></h3><div class="content pos">${window.escHtml(p.prompt)}</div></div>` +
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
    `<div class="section prompt-history-section"><h3>🖼️ 生成历史</h3><div class="prompt-history-grid" id="promptHistoryGrid"><div class="empty-tip" style="font-size:12px">加载中...</div></div></div>` +
    `<div style="color:#555;font-size:11px;margin-top:16px">创建: ${p.created_at || "未知"}${p.updated_at && p.updated_at !== p.created_at ? " · 更新: " + p.updated_at : ""}</div>`;
};

// -------------------------------------------------------------------
// 分段编辑
// -------------------------------------------------------------------
const FRAGMENT_KEYS = ["人物外貌", "姿态动作", "服装配饰", "场景背景", "风格技术"];
const FRAGMENT_ICONS = { "人物外貌": "👤", "姿态动作": "🏃", "服装配饰": "👗", "场景背景": "🌄", "风格技术": "🎨" };
const FRAGMENT_COLORS = { "人物外貌": "#10b981", "姿态动作": "#f59e0b", "服装配饰": "#a855f7", "场景背景": "#3b82f6", "风格技术": "#ef4444" };

window._fragmentEditMode = false;

function parsePromptFragments(text) {
  if (!text) return {};
  const result = {};
  const pattern = /【([^】]+)】\s*(.*?)(?=\n【|$)/g;
  let m;
  while ((m = pattern.exec(text)) !== null) {
    result[m[1].trim()] = m[2].trim();
  }
  return result;
}

function reassemblePrompt(fragments) {
  const parts = [];
  for (const key of FRAGMENT_KEYS) {
    if (fragments[key]) {
      parts.push(`【${key}】${fragments[key]}`);
    }
  }
  return parts.join("\n");
}

window.toggleFragmentEdit = function () {
  window._fragmentEditMode = !window._fragmentEditMode;
  const textarea = document.getElementById("f_prompt");
  const fragContainer = document.getElementById("f_fragments");
  const btn = document.getElementById("f_toggleFragBtn");
  if (!textarea || !fragContainer || !btn) return;

  if (window._fragmentEditMode) {
    // 从 textarea 同步到碎片
    const fragments = parsePromptFragments(textarea.value);
    for (const key of FRAGMENT_KEYS) {
      const ta = document.getElementById(`f_frag_${key}`);
      if (ta) ta.value = fragments[key] || "";
    }
    textarea.style.display = "none";
    fragContainer.style.display = "flex";
    btn.textContent = "📝 切换到全文编辑";
  } else {
    // 从碎片同步到 textarea
    const fragments = {};
    for (const key of FRAGMENT_KEYS) {
      const ta = document.getElementById(`f_frag_${key}`);
      if (ta) fragments[key] = ta.value;
    }
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

window.openCreateModal = async function() {
  document.getElementById("modalTitle").textContent = "新建提示词";
  document.getElementById("f_id").value = "";
  window._fragmentEditMode = false;
  ["f_name","f_prompt","f_neg","f_steps","f_cfg","f_sampler","f_seed","f_model","f_tags","f_note"].forEach(id => document.getElementById(id).value = "");
  window.setRating(0);
  // 重置碎片编辑器
  const fc = document.getElementById("f_fragments");
  const btn = document.getElementById("f_toggleFragBtn");
  const ta = document.getElementById("f_prompt");
  if (fc) fc.style.display = "none";
  if (btn) btn.style.display = "none";
  if (ta) ta.style.display = "";
  // 异步加载分类和标签选项（无预选）
  await window.loadCategoriesForSelect();
  await window.loadTagsForSelect();
  document.getElementById("modalOverlay").classList.add("active");
};

window.openEditModal = async function(id) {
  document.getElementById("modalTitle").textContent = "编辑提示词 #" + id;
  document.getElementById("f_id").value = id;
  window._fragmentEditMode = false;
  try {
    const p = await window.api(`/api/prompts/${id}`);
    document.getElementById("f_name").value = p.name || "";
    document.getElementById("f_prompt").value = p.prompt || "";
    document.getElementById("f_neg").value = p.negative_prompt || "";

    // 设置分段编辑器
    const fragments = parsePromptFragments(p.prompt || "");
    const hasFrags = Object.keys(fragments).length > 0;
    const fragContainer = document.getElementById("f_fragments");
    const btn = document.getElementById("f_toggleFragBtn");
    const textarea = document.getElementById("f_prompt");

    if (fragContainer && hasFrags) {
      let html = "";
      for (const key of FRAGMENT_KEYS) {
        const color = FRAGMENT_COLORS[key] || "#6366f1";
        const icon = FRAGMENT_ICONS[key] || "📝";
        const val = fragments[key] || "";
        html += `
          <div class="frag-field">
            <div class="frag-field-label" style="color:${color}">${icon} ${key}</div>
            <textarea id="f_frag_${key}" rows="2" data-fragkey="${key}">${window.escHtml(val)}</textarea>
          </div>`;
      }
      fragContainer.innerHTML = html;
      // 自动切换到分段模式
      textarea.style.display = "none";
      fragContainer.style.display = "flex";
      btn.style.display = "";
      btn.textContent = "📝 切换到全文编辑";
      window._fragmentEditMode = true;
    } else if (fragContainer) {
      fragContainer.style.display = "none";
      btn.style.display = "none";
      textarea.style.display = "";
    }
    document.getElementById("f_steps").value = p.steps || "";
    document.getElementById("f_cfg").value = p.cfg_scale || "";
    document.getElementById("f_sampler").value = p.sampler || "";
    document.getElementById("f_seed").value = p.seed || "";
    document.getElementById("f_model").value = p.model || "";
    document.getElementById("f_tags").value = p.tags || "";
    document.getElementById("f_note").value = p.note || "";
    const rating = p.rating || 0;
    window.setRating(rating);

    // 直接传入预选值，共享函数内部处理选中状态
    const categories = p.categories || [];
    const catId = categories.length > 0 ? categories[0].id : null;
    const tagsDetail = p.tags_detail || [];
    const tagIds = tagsDetail.map(t => t.id);

    await window.loadCategoriesForSelect(catId);
    await window.loadTagsForSelect(tagIds);

    document.getElementById("modalOverlay").classList.add("active");
  } catch (e) {
    window.showToast("加载失败: " + e.message, "error");
  }
};

window.closeModal = function() {
  document.getElementById("modalOverlay").classList.remove("active");
  window._fragmentEditMode = false;
  // 还原 textarea 显示
  const ta = document.getElementById("f_prompt");
  const fc = document.getElementById("f_fragments");
  const btn = document.getElementById("f_toggleFragBtn");
  if (ta) ta.style.display = "";
  if (fc) fc.style.display = "none";
  if (btn) btn.style.display = "none";
};

window.savePrompt = async function() {
  return window.withLock("savePrompt", async () => {
    const saveBtn = document.getElementById("modalSaveBtn");
    if (saveBtn) saveBtn.disabled = true;
    // 如果处于分段编辑模式，从碎片重新组装
    let promptValue;
    if (window._fragmentEditMode) {
      const frags = {};
      for (const key of FRAGMENT_KEYS) {
        const ta = document.getElementById(`f_frag_${key}`);
        if (ta) frags[key] = ta.value;
      }
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
        window.showToast(isEdit ? "已更新" : "已创建", "success");
        window.closeModal();
        window.loadTags();
        window.loadCategories();
        window.loadPrompts();
        if (isEdit) window.selectPrompt(parseInt(id));
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
  const text = type === 0 ? (window._currentPromptData.prompt || "") : (window._currentPromptData.negative_prompt || "");
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "已复制";
    setTimeout(() => btn.textContent = "复制", 1500);
  }, () => window.showToast("复制失败", "error"));
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
};
