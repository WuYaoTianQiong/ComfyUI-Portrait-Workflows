// composer.js - 组合创作模块
// 依赖：utils.js, ui.js, generator.js
// 职责：五列碎片选择 + 组装工作台 + 模板收藏

// -------------------------------------------------------------------
// 碎片类型定义
// -------------------------------------------------------------------
const FRAGMENT_TYPES = [
  { key: "拍摄视角", label: "拍摄视角", color: "#f97316", icon: "📷" },
  { key: "姿态动作", label: "姿态动作", color: "#f59e0b", icon: "🏃" },
  { key: "人物身材", label: "人物身材", color: "#059669", icon: "🧍" },
  { key: "人物服饰", label: "人物服饰", color: "#a855f7", icon: "👗" },
  { key: "人物面部", label: "人物面部", color: "#10b981", icon: "👤" },
  { key: "场景环境", label: "场景环境", color: "#3b82f6", icon: "🌄" },
  { key: "光影色调", label: "光影色调", color: "#06b6d4", icon: "💡" },
  { key: "画风技术", label: "画风技术", color: "#ef4444", icon: "🎨" },
];

// -------------------------------------------------------------------
// 状态
// -------------------------------------------------------------------
window._composerSelection = {}; // { "人物外貌": {content, prompt_id, prompt_name}, ... }
window._composerFixed = {};      // { "人物面部": true, ... } 固定类型集合（固定后该类型不参与随机）
window._composerFragmentData = null; // 缓存碎片数据
window._composerTemplates = [];
window._templateCategories = [];
window._composerViewMode = "column"; // "column" | "list"

// -------------------------------------------------------------------
// 初始化
// -------------------------------------------------------------------
window.initComposer = function () {
  window._restoreComposerState();
  window._composerViewMode = window.UiState.get("composerViewMode", "column");
  const vtBtn = document.getElementById("viewToggleBtn");
  if (vtBtn) vtBtn.textContent = window._composerViewMode === "column" ? "📐 行视图" : "📐 列视图";
  const c = document.getElementById("composerColumns");
  const b = c?.closest(".composer-body");
  if (c && window._composerViewMode === "list") {
    c.classList.add("composer-list");
    if (b) b.style.overflow = "auto";
  }
  // 从 DB 加载模板
  window._loadTemplates().then(() => {
    // 首次加载时尝试迁移 localStorage 旧模板
    window._migrateLocalTemplates();
  });
  // 初始化批量随机跑图按钮状态
  const batchBtn = document.getElementById("composerBatchRunBtn");
  if (batchBtn) batchBtn.disabled = !window.currentWorkflowPath();
  // 初始化固定按钮 UI
  for (const ft of FRAGMENT_TYPES) {
    window._updateColumnFixUI(ft.key);
  }
  window._updateBatchRandomUI();
};

// 从 DB 加载模板列表
window._loadTemplates = async function () {
  try {
    const data = await window.api("/api/templates");
    window._composerTemplates = data.templates || [];
    window.renderTemplateList();
  } catch (e) {
    console.error("加载模板失败:", e);
  }
};

// 单次迁移 localStorage 旧模板
window._migrateLocalTemplates = function () {
  if (window._migratedOnce) return;
  window._migratedOnce = true;
  let local;
  try {
    local = JSON.parse(localStorage.getItem("composerTemplates_v4") || "[]");
    localStorage.removeItem("composerTemplates_v4"); // 移走
  } catch (_) { return; }
  if (!local || local.length === 0) return;

  const items = [];
  for (const tpl of local) {
    const frags = [];
    const types = tpl.fragments || {};
    for (const [type, frag] of Object.entries(types)) {
      if (frag && frag.prompt_id) {
        frags.push({ prompt_id: frag.prompt_id, fragment_type: type });
      }
    }
    if (frags.length > 0) {
      items.push({ name: tpl.name, fragments: frags });
    }
  }
  if (items.length === 0) return;

  // 发到后端批量导入
  window.api("/api/templates/batch_import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  }).then(res => {
    if (res.imported > 0) {
      window.showToast(`已迁移 ${res.imported} 个旧模板到数据库`, "success");
      window._loadTemplates();
    }
  }).catch(() => {});
};

// 工作台弹窗
window.openWorkbenchModal = function () {
  window.renderComposerWorkbench();
  document.getElementById("wbModalOverlay").classList.add("active");
};
window.closeWorkbenchModal = function () {
  document.getElementById("wbModalOverlay").classList.remove("active");
};

// 持久化当前选择
window._saveComposerState = function () {
  window.UiState.set("composerSelection", JSON.parse(JSON.stringify(window._composerSelection)));
};

// 恢复上次选择
window._restoreComposerState = function () {
  const saved = window.UiState.get("composerSelection", null);
  if (saved && typeof saved === "object" && Object.keys(saved).length > 0) {
    window._composerSelection = saved;
  }
};

// -------------------------------------------------------------------
// 刷新碎片数据
// -------------------------------------------------------------------
window.refreshComposer = async function () {
  window._composerDataStale = false;
  // 从当前提示词筛选条件取参
  const search = document.getElementById("searchInput").value;
  const params = { search };
  // 修复：category_id 必须是有效的整数，不能是 "__templates__" 等字符串
  if (window._currentCategoryId !== null && String(window._currentCategoryId).match(/^\d+$/)) {
    params.category_id = window._currentCategoryId;
  }
  if (window._selectedTags && window._selectedTags.size > 0) {
    params.tag_ids = Array.from(window._selectedTags).join(",");
  }

  const qs = new URLSearchParams(params).toString();
  try {
    const data = await window.api(`/api/composer/fragments?${qs}`);
    window._composerFragmentData = data;
    if (window._composerViewMode === "list") {
      window.renderComposerList(data.grouped);
    } else {
      window.renderComposerColumns(data.grouped);
    }
    window.updateComposerStats(data);
    // 保留已选碎片（如果来源提示词仍在结果中）
    window._syncComposerSelection(data.grouped);
    // 确保工作台与 restored state 同步
    window.renderComposerWorkbench();
    // 同步固定按钮 UI
    for (const ft of FRAGMENT_TYPES) {
      window._updateColumnFixUI(ft.key);
    }
    window._updateBatchRandomUI();
    // 检查是否有从提示词列表跳转过来的待加载模板
    if (window._pendingTemplateId) {
      const tid = window._pendingTemplateId;
      window._pendingTemplateId = null;
      // 从模板列表中找到索引
      const idx = window._composerTemplates.findIndex(t => t.id === tid);
      if (idx >= 0) {
        window.loadComposerTemplate(idx);
      } else {
        // 还没加载到内存，直接按 ID 加载
        window.loadComposerTemplateById(tid);
      }
    }
  } catch (e) {
    window.showToast("加载碎片失败: " + e.message, "error");
  }
};

// 同步已选：按 ID 匹配，内容变化不影响选中状态
window._syncComposerSelection = function (grouped) {
  let changed = false;
  for (const type of Object.keys(window._composerSelection)) {
    const sel = window._composerSelection[type];
    if (!sel) continue;
    // 自定义碎片不参与同步，始终保留
    if (sel.custom || sel.source === "custom") continue;
    let available = false;
    if (sel.source === "library") {
      available = (grouped[type] || []).some(
        f => f.fragment_id && sel.fragment_id && f.fragment_id === sel.fragment_id
      );
    } else if (sel.prompt_id) {
      available = (grouped[type] || []).some(f => f.prompt_id === sel.prompt_id);
    }
    if (!available) {
      delete window._composerSelection[type];
      changed = true;
    }
  }
  if (changed) window.renderComposerWorkbench();
};

// -------------------------------------------------------------------
// 渲染五列碎片区
// -------------------------------------------------------------------
window.renderComposerColumns = function (grouped) {
  const container = document.getElementById("composerColumns");
  if (!container) return;
  container.innerHTML = "";

  for (const ft of FRAGMENT_TYPES) {
    const col = document.createElement("div");
    col.className = "composer-col";
    col.style.setProperty("--col-color", ft.color);

    // 列头
    const header = document.createElement("div");
    header.className = "composer-col-header";
    const isFixed = !!window._composerFixed[ft.key];
    header.innerHTML = `
      <span class="composer-col-icon">${ft.icon}</span>
      <span class="composer-col-title">${ft.label}</span>
      <span class="composer-col-count">${(grouped[ft.key] || []).length}</span>
      <span class="col-fix-btn" style="cursor:pointer;font-size:11px;user-select:none;color:${isFixed ? 'var(--warning)' : 'var(--muted)'}" onclick="event.stopPropagation();window.toggleFixFragmentType('${ft.key.replace(/'/g, "\\'")}')" title="固定此类型：批量随机时不再变动">📌 <span class="fix-text">${isFixed ? '已固定' : '未固定'}</span></span>
    `;
    col.appendChild(header);

    // 碎片列表
    const list = document.createElement("div");
    list.className = "composer-col-list";
    list.id = `composerList_${ft.key}`;

    const fragments = grouped[ft.key] || [];
    // 如果有自定义内容，在列头显示标记
    const hasCustom = window._composerSelection[ft.key] && window._composerSelection[ft.key].custom;
    // 已选内容预览
    const selContent = window._composerSelection[ft.key]?.content;

    // 如果有自定义内容，在列表顶部显示自定义卡片
    if (hasCustom) {
      const customCard = document.createElement("div");
      customCard.className = "composer-frag-card selected custom-frag-card";
      customCard.style.borderColor = "var(--warning)";
      customCard.style.background = "color-mix(in srgb, var(--warning) 8%, var(--panel-2))";
      const contentShort = selContent.length > 80 ? selContent.slice(0, 80) + "…" : selContent;
      customCard.innerHTML = `
        <div class="frag-content"><span class="frag-text-click">✏️ ${window.escHtml(contentShort)}</span></div>
        <div class="frag-source" style="color:var(--warning);display:flex;justify-content:space-between;align-items:center;width:100%">
          自定义内容（已固定）
          <span class="frag-actions-inline" onclick="event.stopPropagation()" style="flex-shrink:0;margin-left:8px">
            <button class="wfa-btn wfa-save" onclick="window._saveCustomFragmentToLibrary('${ft.key.replace(/'/g, "\\'")}')" title="保存到碎片库">💾 入库</button>
            <button class="wfa-btn wfa-del" onclick="window._removeCustomFragment('${ft.key.replace(/'/g, "\\'")}')" title="删除自定义内容">🗑️ 删除</button>
          </span>
        </div>
        <div class="frag-check">✓</div>
      `;
      // 点击编辑自定义内容
      customCard.addEventListener("click", (e) => {
        if (!e.target.closest(".frag-actions")) {
          window._editCustomFragment(ft.key);
        }
      });
      list.appendChild(customCard);
    }

    if (fragments.length === 0 && !hasCustom) {
      list.innerHTML = '<div class="composer-empty">无匹配碎片<br><button class="btn btn-xxs btn-ghost" onclick="window._addCustomFragment(\'' + ft.key + '\')" style="margin-top:4px">✏️ 自定义</button></div>';
    } else {
      for (const f of fragments) {
        const isSelected = window._isFragmentSelected(ft.key, f);
        const card = document.createElement("div");
        card.className = "composer-frag-card" + (isSelected ? " selected" : "");
        card.dataset.type = ft.key;
        card.dataset.promptId = f.prompt_id;
        card.dataset.fragmentId = f.fragment_id || "";
        card.dataset.content = f.content;

        // 缩略内容（点击弹窗查看完整内容）
        const contentShort = f.content.length > 80 ? f.content.slice(0, 80) + "…" : f.content;
        const isLibrary = f.source === "library";
        const dupCount = f.dup_count || 1;
        const dupBadge = dupCount > 1 ? ` <span class="frag-dup-badge" title="出现在 ${dupCount} 条提示词中">×${dupCount}</span>` : "";
        const sourceNames = (f.source_names && f.source_names.length > 1)
          ? `来源: ${f.source_names.join("、")}`
          : (isLibrary ? "碎片库独立碎片" : `来源: ${window.escHtml(f.prompt_name)}`);
        const sourceLabel = isLibrary
          ? `📦 ${window.escHtml(f.prompt_name || "碎片库")}`
          : window.escHtml(f.prompt_name || `#${f.prompt_id}`);
        card.innerHTML = `
          <div class="frag-content"><span class="frag-text-click">${window.escHtml(contentShort)}${dupBadge}</span></div>
          <div class="frag-source ${isLibrary ? 'frag-source-library' : ''}" title="${window.escAttr(sourceNames)}">${sourceLabel}</div>
          ${isSelected ? '<div class="frag-check">✓</div>' : ''}
        `;

        // 点击选择（整张卡片）
        card.addEventListener("click", () => window.selectComposerFragment(ft.key, f));
        // 点击文字查看完整内容（不触发卡片选择）
        const textSpan = card.querySelector(".frag-text-click");
        if (textSpan) {
          textSpan.addEventListener("click", (e) => {
            e.stopPropagation();
            window._showFullFrag(ft.key, f.prompt_id || f.fragment_id || 0);
          });
        }
        list.appendChild(card);
      }
    }

    // 添加"自定义"按钮到列表末尾（即使有碎片也允许用户手写）
    const customBtn = document.createElement("div");
    customBtn.className = "composer-custom-btn";
    customBtn.innerHTML = hasCustom
      ? `<span style="color:var(--warning);font-size:11px">✏️ ${(selContent||'').slice(0,30)}${(selContent||'').length>30?'…':''}</span>`
      : `<button class="btn btn-xxs btn-ghost" onclick="window._addCustomFragment('${ft.key}')" style="width:100%;font-size:11px">✏️ 自定义...</button>`;
    list.appendChild(customBtn);

    col.appendChild(list);
    container.appendChild(col);
  }

  // 为每列列表添加底部垫片，让最后一项可以滚到容器中间
  requestAnimationFrame(() => {
    for (const ft of FRAGMENT_TYPES) {
      const list = document.getElementById(`composerList_${ft.key}`);
      if (!list) continue;
      // 先移除旧垫片
      const old = list.querySelector(".bottom-spacer");
      if (old) old.remove();
      // 创建底部垫片
      const spacer = document.createElement("div");
      spacer.className = "bottom-spacer";
      list.appendChild(spacer);
    }
  });
};

// -------------------------------------------------------------------
// 自定义碎片功能（手写内容，不依赖碎片池）
// -------------------------------------------------------------------

/** 添加自定义碎片：弹窗让用户输入内容 */
window._addCustomFragment = function (type) {
  const existing = window._composerSelection[type];
  const defaultValue = existing ? existing.content : "";
  const isCustom = !!(existing && (existing.custom || existing.source === "custom"));
  const html = `
    <div class="modal-header"><h2>✏️ 自定义 ${type}</h2></div>
    <div class="modal-body">
      <p style="font-size:11px;color:var(--muted)">输入任意提示词片段，不会被随机替换</p>
      <textarea id="customFragInput" style="width:100%;min-height:80px;background:var(--bg);border:1px solid var(--border-soft);color:var(--text);border-radius:6px;padding:8px;font-size:12px">${window.escHtml(defaultValue)}</textarea>
    </div>
    <div class="modal-footer">
      ${isCustom ? `<button class="btn btn-sm btn-ghost" onclick="if(confirm('删除自定义${type}？')){window._removeCustomFragment('${type.replace(/'/g, "\\'")}',true);window.closeModal();}" style="color:var(--danger)">🗑️ 删除</button>` : ""}
      ${isCustom ? `<button class="btn btn-sm btn-ghost" onclick="window._saveCustomFragmentToLibrary('${type.replace(/'/g, "\\'")}')" style="color:var(--success)">💾 入库</button>` : ""}
      <button class="btn btn-sm btn-primary" onclick="window._saveCustomFragment('${type}')">保存</button>
      <button class="btn btn-sm btn-ghost" onclick="window.closeModal()">取消</button>
    </div>
  `;
  window.showModal(html);
  // 自动聚焦
  setTimeout(() => {
    const ta = document.getElementById("customFragInput");
    if (ta) { ta.focus(); ta.select(); }
  }, 100);
};

/** 保存自定义碎片到选中区 */
window._saveCustomFragment = function (type) {
  const ta = document.getElementById("customFragInput");
  if (!ta) return;
  const content = ta.value.trim();
  if (!content) {
    window.showToast("内容不能为空", "warn");
    return;
  }
  // 保存为自定义碎片
  window._composerSelection[type] = {
    content: content,
    prompt_id: 0,
    fragment_id: null,
    prompt_name: "自定义",
    type: type,
    source: "custom",
    custom: true,
  };
  // 自动固定（自定义内容不应被随机覆盖）
  window._composerFixed[type] = true;
  window.closeModal();
  // 重新渲染列视图，让自定义碎片显示在列表中
  if (window._composerFragmentData) {
    window.renderComposerColumns(window._composerFragmentData.grouped);
  }
  window._updateColumnSelectionUI(type);
  window._updateColumnFixUI(type);
  window.renderComposerWorkbench();
  window._saveComposerState();
  window._updateBatchRandomUI();
  // 自动打开工作台，让用户看到自定义碎片已添加
  window.showToast(`已添加自定义${type}，已自动固定`, "success");
  setTimeout(() => window.openWorkbenchModal(), 300);
};

/** 编辑已有的自定义碎片 */
window._editCustomFragment = function (type) {
  window._addCustomFragment(type);
};

/** 删除自定义碎片 */
window._removeCustomFragment = function (type, skipConfirm) {
  if (!skipConfirm && !confirm(`删除自定义${type}？`)) return false;
  delete window._composerSelection[type];
  delete window._composerFixed[type];
  // 重新渲染列视图
  if (window._composerFragmentData) {
    window.renderComposerColumns(window._composerFragmentData.grouped);
  }
  window.renderComposerWorkbench();
  window._saveComposerState();
  window._updateBatchRandomUI();
  window.showToast(`已删除自定义${type}`, "info");
  return true;
};

/** 将自定义碎片保存到碎片库（入库） */
window._saveCustomFragmentToLibrary = async function (type) {
  const sel = window._composerSelection[type];
  if (!sel || !sel.custom) {
    window.showToast("没有自定义内容", "warn");
    return;
  }
  try {
    await window.api("/api/fragments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: sel.content,
        fragment_type: type,
      }),
    });
    window.showToast(`已保存到碎片库`, "success");
    // 刷新碎片数据
    await window.refreshComposer();
  } catch (e) {
    window.showToast("保存失败: " + e.message, "error");
  }
};

// -------------------------------------------------------------------
// 行视图渲染（替代列视图）
// -------------------------------------------------------------------
window.toggleComposerView = function () {
  window._composerViewMode = window._composerViewMode === "column" ? "list" : "column";
  window.UiState.set("composerViewMode", window._composerViewMode);
  const btn = document.getElementById("viewToggleBtn");
  if (btn) {
    const newText = window._composerViewMode === "column" ? "📐 行视图" : "📐 列视图";
    btn.textContent = newText;
    // 添加视觉反馈
    btn.style.transform = "scale(0.95)";
    setTimeout(() => {
      btn.style.transform = "";
    }, 200);
  }
  // 切换容器和父容器样式
  const container = document.getElementById("composerColumns");
  const body = container?.closest(".composer-body");
  if (container) {
    if (window._composerViewMode === "list") {
      container.classList.add("composer-list");
      if (body) body.style.overflow = "auto";
    } else {
      container.classList.remove("composer-list");
      if (body) body.style.overflow = "hidden";
    }
  }
  if (window._composerFragmentData) {
    if (window._composerViewMode === "list") {
      window.renderComposerList(window._composerFragmentData.grouped);
    } else {
      window.renderComposerColumns(window._composerFragmentData.grouped);
    }
  }
  window.showToast(`已切换为${window._composerViewMode === "column" ? "列" : "行"}视图`, "info");
};

window.renderComposerList = function (grouped) {
  const container = document.getElementById("composerColumns");
  if (!container) return;
  container.innerHTML = "";
  container.className = "composer-columns composer-list";

  for (const ft of FRAGMENT_TYPES) {
    const fragments = grouped[ft.key] || [];
    if (fragments.length === 0) continue;

    const section = document.createElement("div");
    section.className = "composer-list-section";

    // 节标题（点击折叠/展开）
    const sectionKey = `composerSection_${ft.key}`;
    const isCollapsed = window.UiState.get(sectionKey, false);
    const header = document.createElement("div");
    header.className = "composer-list-header";
    header.style.cursor = "pointer";
    header.innerHTML = `
      <span style="color:${ft.color}">${ft.icon} ${ft.label}</span>
      <span class="composer-col-count">${fragments.length}</span>
      <span style="margin-left:auto;font-size:10px;color:var(--muted)">${isCollapsed ? "展开 ▼" : "收起 ▲"}</span>
    `;
    header.onclick = () => {
      const now = !window.UiState.get(sectionKey, false);
      window.UiState.set(sectionKey, now);
      const items = section.querySelector(".composer-list-items");
      const label = section.querySelector(".composer-list-header span:last-child");
      if (items) items.style.display = now ? "none" : "";
      if (label) label.textContent = now ? "展开 ▼" : "收起 ▲";
    };
    section.appendChild(header);

    // 碎片列表（可折叠）
    const list = document.createElement("div");
    list.className = "composer-list-items";
    if (isCollapsed) list.style.display = "none";

    for (const f of fragments) {
      const isSelected = window._isFragmentSelected(ft.key, f);
      const card = document.createElement("div");
      card.className = "composer-list-card" + (isSelected ? " selected" : "");
      card.dataset.type = ft.key;
      card.dataset.promptId = f.prompt_id;
      card.dataset.content = f.content;

      const isLibrary = f.source === "library";
      const dupCount = f.dup_count || 1;
      const dupBadge = dupCount > 1 ? ` <span class="frag-dup-badge">x${dupCount}</span>` : "";
      const sourceLabel = isLibrary
        ? `📦 ${window.escHtml(f.prompt_name || "碎片库")}${dupBadge}`
        : `${window.escHtml(f.prompt_name || `#${f.prompt_id}`)}${dupBadge}`;

      card.innerHTML = `
        <div class="clc-content">
          <span class="clc-text">${window.escHtml(f.content)}</span>
        </div>
        <div class="clc-source ${isLibrary ? 'frag-source-library' : ''}">${sourceLabel}</div>
        ${isSelected ? '<div class="frag-check">✓</div>' : ''}
      `;

      card.addEventListener("click", () => window.selectComposerFragment(ft.key, f));
      // 点击文字查看详情
      const textEl = card.querySelector(".clc-text");
      if (textEl) {
        textEl.addEventListener("click", (e) => {
          e.stopPropagation();
          window._showFullFrag(ft.key, f.prompt_id || f.fragment_id || 0);
        });
      }

      list.appendChild(card);
    }

    section.appendChild(list);
    container.appendChild(section);
  }
};

// 判断碎片是否已被选中（按 ID 匹配，不比较内容）
window._isFragmentSelected = function (type, fragment) {
  const sel = window._composerSelection[type];
  if (!sel) return false;
  if (fragment.fragment_id && sel.fragment_id) {
    return sel.fragment_id === fragment.fragment_id;
  }
  return sel.prompt_id === fragment.prompt_id;
};

// -------------------------------------------------------------------
// 选择/取消碎片
// -------------------------------------------------------------------
window.selectComposerFragment = function (type, fragment) {
  // 如果已选同一碎片，则取消选择（同时取消固定）
  if (window._isFragmentSelected(type, fragment)) {
    delete window._composerSelection[type];
    delete window._composerFixed[type];
    window._updateColumnSelectionUI(type);
    window._updateColumnFixUI(type);
    window.renderComposerWorkbench();
    window._saveComposerState();
    window._updateBatchRandomUI();
    return;
  }

  // 选择新碎片
  window._composerSelection[type] = {
    content: fragment.content,
    prompt_id: fragment.prompt_id,
    fragment_id: fragment.fragment_id || null,
    prompt_name: fragment.prompt_name,
    type: type,
    source: fragment.source || "prompt",
  };
  window._updateColumnSelectionUI(type);
  window.renderComposerWorkbench();
  window._saveComposerState();
};

// 移除已选
window.removeComposerFragment = function (type) {
  delete window._composerSelection[type];
  // 同时取消固定
  delete window._composerFixed[type];
  window._updateColumnSelectionUI(type);
  window.renderComposerWorkbench();
  window._saveComposerState();
  window.showToast(`已移除「${type}」`, "info");
};

// -------------------------------------------------------------------