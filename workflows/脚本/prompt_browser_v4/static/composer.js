// composer.js - 组合创作模块
// 依赖：utils.js, ui.js, generator.js
// 职责：五列碎片选择 + 组装工作台 + 模板收藏

// -------------------------------------------------------------------
// 碎片类型定义
// -------------------------------------------------------------------
const FRAGMENT_TYPES = [
  { key: "人物面部", label: "人物面部", color: "#10b981", icon: "👤" },
  { key: "人物身材", label: "人物身材", color: "#059669", icon: "🧍" },
  { key: "人物服饰", label: "人物服饰", color: "#a855f7", icon: "👗" },
  { key: "姿态动作", label: "姿态动作", color: "#f59e0b", icon: "🏃" },
  { key: "拍摄视角", label: "拍摄视角", color: "#f97316", icon: "📷" },
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
  if (window._currentCategoryId !== null) {
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
      <span class="col-fix-btn" style="cursor:pointer;font-size:11px;margin-left:4px;user-select:none;color:${isFixed ? 'var(--warning)' : 'var(--muted)'}" onclick="event.stopPropagation();window.toggleFixFragmentType('${ft.key.replace(/'/g, "\\'")}')" title="固定此类型：批量随机时不再变动">${isFixed ? '📌 已固定' : '📌 固定'}</span>
    `;
    col.appendChild(header);

    // 碎片列表
    const list = document.createElement("div");
    list.className = "composer-col-list";
    list.id = `composerList_${ft.key}`;

    const fragments = grouped[ft.key] || [];
    if (fragments.length === 0) {
      list.innerHTML = '<div class="composer-empty">无匹配碎片</div>';
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
// 行视图渲染（替代列视图）
// -------------------------------------------------------------------
window.toggleComposerView = function () {
  window._composerViewMode = window._composerViewMode === "column" ? "list" : "column";
  window.UiState.set("composerViewMode", window._composerViewMode);
  const btn = document.getElementById("viewToggleBtn");
  if (btn) btn.textContent = window._composerViewMode === "column" ? "📐 行视图" : "📐 列视图";
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
};

// -------------------------------------------------------------------
// 固定 / 取消固定碎片类型
// -------------------------------------------------------------------
window.toggleFixFragmentType = function (type) {
  if (window._composerFixed[type]) {
    delete window._composerFixed[type];
    window.showToast(`已取消固定「${type}」`, "info");
  } else {
    // 固定前必须已选该类型
    if (!window._composerSelection[type]) {
      window.showToast(`请先选择「${type}」的碎片再固定`, "warn");
      return;
    }
    window._composerFixed[type] = true;
    window.showToast(`已固定「${type}」：随机时不再变动`, "success");
  }
  // 更新列头固定按钮样式
  window._updateColumnFixUI(type);
  window._updateBatchRandomUI();
};

window._updateColumnFixUI = function (type) {
  // 更新列头固定按钮
  const header = document.querySelector(`#composerList_${type}`)?.previousElementSibling;
  if (!header) return;
  let fixBtn = header.querySelector(".col-fix-btn");
  const isFixed = !!window._composerFixed[type];
  if (!fixBtn) {
    // 动态创建固定按钮
    fixBtn = document.createElement("span");
    fixBtn.className = "col-fix-btn";
    fixBtn.style.cssText = "cursor:pointer;font-size:12px;margin-left:4px;user-select:none;";
    header.appendChild(fixBtn);
  }
  fixBtn.textContent = isFixed ? "📌 已固定" : "📌 固定";
  fixBtn.style.color = isFixed ? "var(--warning)" : "var(--muted)";
  fixBtn.onclick = (e) => { e.stopPropagation(); window.toggleFixFragmentType(type); };
};

// 更新批量随机跑图按钮提示
window._updateBatchRandomUI = function () {
  const btn = document.getElementById("composerBatchRunBtn");
  if (!btn) return;
  const fixedCount = Object.keys(window._composerFixed).length;
  if (fixedCount > 0) {
    btn.title = `固定了 ${fixedCount} 个类型，其余随机匹配`;
  } else {
    btn.title = "";
  }
};

// 更新单列选中状态
window._updateColumnSelectionUI = function (type) {
  const list = document.getElementById(`composerList_${type}`);
  if (!list) return;
  const cards = list.querySelectorAll(".composer-frag-card");
  for (const card of cards) {
    const f = {
      prompt_id: parseInt(card.dataset.promptId),
      content: card.dataset.content,
    };
    const selected = window._isFragmentSelected(type, f);
    card.classList.toggle("selected", selected);
    // 更新勾选标记
    let check = card.querySelector(".frag-check");
    if (selected) {
      if (!check) {
        check = document.createElement("div");
        check.className = "frag-check";
        check.textContent = "✓";
        card.appendChild(check);
      }
    } else {
      if (check) check.remove();
    }
  }
};

// -------------------------------------------------------------------
// 渲染组装工作台
// -------------------------------------------------------------------
window.renderComposerWorkbench = function () {
  const workbench = document.getElementById("composerWorkbench");
  if (!workbench) return;

  const selectedTypes = FRAGMENT_TYPES.filter(ft => window._composerSelection[ft.key]);

  if (selectedTypes.length === 0) {
    workbench.innerHTML = `
      <div class="workbench-empty">
        <div class="workbench-empty-icon">🧩</div>
        <div>从上方各列点击碎片，自由组合提示词</div>
        <div class="workbench-empty-hint">每列最多选一个碎片，选中的碎片会在这里拼接</div>
      </div>
    `;
    document.getElementById("composerRunBtn").disabled = true;
    return;
  }

  let html = "";
  for (const ft of FRAGMENT_TYPES) {
    const sel = window._composerSelection[ft.key];
    if (!sel) continue;
    const sourceLabel = sel.source === "library"
      ? `📦 ${window.escHtml(sel.prompt_name || "碎片库")}`
      : `来源：${window.escHtml(sel.prompt_name || `#${sel.prompt_id}`)}`;
    const isFixed = !!window._composerFixed[ft.key];
    const fixLabel = isFixed ? '<span class="wb-fix-badge" title="批量随机时固定此类型">📌 已固定</span>' : '';
    html += `
      <div class="workbench-frag" style="border-left: 3px solid ${ft.color}">
        <div class="workbench-frag-header">
          <span class="workbench-frag-type" style="color:${ft.color}" title="${sourceLabel}">${ft.icon} ${ft.key} ${fixLabel}</span>
          <div class="workbench-frag-actions">
            <button class="wfa-btn wfa-copy" onclick="window.copyComposerFragment('${ft.key.replace(/'/g, "\\'")}')" title="复制此碎片">📋</button>
            <button class="wfa-btn ${isFixed ? 'wfa-fix' : 'wfa-fix-off'}" onclick="window.toggleFixFragmentType('${ft.key.replace(/'/g, "\\'")}')" title="${isFixed ? '取消固定' : '固定此类型（批量随机时不再变动）'}">${isFixed ? '📌' : '📌'}</button>
            <button class="wfa-btn wfa-del" onclick="window.removeComposerFragment('${ft.key}')" title="移除">✕</button>
          </div>
        </div>
        <textarea class="workbench-frag-body" data-frag-type="${ft.key}" oninput="window._onFragEdit(this)" placeholder="✏️ 点击编辑此碎片...">${window.escHtml(sel.content)}</textarea>
      </div>
    `;
  }

  workbench.innerHTML = html;

  // 所有 textarea 执行自动增高
  workbench.querySelectorAll(".workbench-frag-body").forEach(ta => {
    ta.style.height = "auto";
    ta.style.height = (ta.scrollHeight + 2) + "px";
  });

  // 更新按钮状态
  const composed = window.getComposedPrompt();
  document.getElementById("composerRunBtn").disabled = !composed;
  const wbBtn = document.getElementById("wbModalBtn");
  if (wbBtn) wbBtn.disabled = !composed;
};


// -------------------------------------------------------------------
// 组装完整的提示词文本
// -------------------------------------------------------------------
window.getComposedPrompt = function () {
  const parts = [];
  for (const ft of FRAGMENT_TYPES) {
    const sel = window._composerSelection[ft.key];
    if (sel && sel.content) {
      parts.push(`【${ft.key}】${sel.content}`);
    }
  }
  return parts.join("\n");
};

// -------------------------------------------------------------------
// 一键复制（完整组合 + 单碎片）
// -------------------------------------------------------------------
window.copyComposedPrompt = function () {
  const text = window.getComposedPrompt();
  if (!text) { window.showToast("还没有组合任何碎片", "warn"); return; }
  navigator.clipboard.writeText(text).then(() => {
    window.showToast("完整提示词已复制", "success");
  }).catch(() => {
    window.showToast("复制失败", "error");
  });
};

window.copyComposerFragment = function (type) {
  const sel = window._composerSelection[type];
  if (!sel || !sel.content) { window.showToast("该碎片无内容", "warn"); return; }
  navigator.clipboard.writeText(sel.content).then(() => {
    window.showToast(`${type} 碎片已复制`, "success");
  }).catch(() => {
    window.showToast("复制失败", "error");
  });
};

// -------------------------------------------------------------------
// 清空所有选择
// -------------------------------------------------------------------
window.clearComposerSelection = function () {
  window._composerSelection = {};
  window._composerFixed = {};
  // 更新所有列 UI
  for (const ft of FRAGMENT_TYPES) {
    window._updateColumnSelectionUI(ft.key);
    window._updateColumnFixUI(ft.key);
  }
  window.renderComposerWorkbench();
  window._saveComposerState();
  window._updateBatchRandomUI();
};

// -------------------------------------------------------------------
// 随机组合（保留固定类型不变）
// -------------------------------------------------------------------
window.randomComposer = function () {
  if (!window._composerFragmentData) {
    window.showToast("请先加载碎片数据", "warn");
    return;
  }
  const grouped = window._composerFragmentData.grouped;
  // 只随机未固定的类型，固定类型保持不变
  for (const ft of FRAGMENT_TYPES) {
    if (window._composerFixed[ft.key] && window._composerSelection[ft.key]) {
      continue; // 跳过固定类型
    }
    const frags = grouped[ft.key] || [];
    if (frags.length > 0) {
      const pick = frags[Math.floor(Math.random() * frags.length)];
      window._composerSelection[ft.key] = {
        content: pick.content,
        prompt_id: pick.prompt_id,
        prompt_name: pick.prompt_name,
        type: ft.key,
      };
    }
  }
  for (const ft of FRAGMENT_TYPES) {
    window._updateColumnSelectionUI(ft.key);
  }
  window.renderComposerWorkbench();
  window._saveComposerState();

  // 滚动每列到已选卡片（列视图：滚动各列内部；行视图：滚动整个列表容器）
  setTimeout(() => {
    try {
      if (window._composerViewMode === "list") {
        // 行视图：滚动整个列表容器到第一个选中项
        const first = document.querySelector(".composer-list-card.selected");
        if (first) {
          first.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      } else {
        // 列视图：逐列滚动到该列的选中项
        for (const ft of FRAGMENT_TYPES) {
          const list = document.getElementById(`composerList_${ft.key}`);
          if (!list) continue;
          const sel = list.querySelector(".composer-frag-card.selected");
          if (sel) {
            // 精确计算：让选中项在列表可视区域中间
            const listRect = list.getBoundingClientRect();
            const selRect = sel.getBoundingClientRect();
            const relativeTop = sel.offsetTop - list.offsetTop;
            const targetScroll = relativeTop - list.clientHeight / 2 + sel.offsetHeight / 2;
            list.scrollTo({ top: Math.max(0, targetScroll), behavior: "smooth" });
          }
        }
      }
    } catch(e) {}
  }, 150);

  window.showToast("已随机组合", "info");
};

// -------------------------------------------------------------------
// 批量随机组合跑图
// -------------------------------------------------------------------
window.composerBatchRandomRun = async function () {
  const count = parseInt(document.getElementById("composerBatchCount")?.value || "1");
  const workflowPath = window.currentWorkflowPath();
  if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }

  // 收集固定碎片
  const fixedFragments = {};
  for (const ft of FRAGMENT_TYPES) {
    if (window._composerFixed[ft.key] && window._composerSelection[ft.key]) {
      fixedFragments[ft.key] = window._composerSelection[ft.key].content;
    }
  }

  const btn = document.getElementById("composerBatchRunBtn");
  if (btn) { btn.disabled = true; btn.textContent = "发送中..."; }

  try {
    const body = Object.assign({
      count: count,
      workflow_path: workflowPath,
      orientation: window.currentOrientation,
      quality: window.getQuality(),
      negative_prompt: "",
      fixed_fragments: fixedFragments,
    }, window.workflowExtraBody());
    const data = await window.api("/api/composer/batch_random_run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const fixedMsg = Object.keys(fixedFragments).length > 0
      ? `（固定 ${Object.keys(fixedFragments).length} 个类型）`
      : "";
    window.showToast(`批量随机组合已推送 (job ${data.job_id})${fixedMsg}`, "success");
    window.trackJob(data.job_id);
  } catch (e) {
    window.showToast("批量随机跑图失败: " + e.message, "error");
  } finally {
    if (btn) { btn.textContent = "🎲 批量随机跑图"; btn.disabled = false; }
  }
};

// -------------------------------------------------------------------
// 随机组合提示词详情弹窗
// -------------------------------------------------------------------
window.showRandomPromptDetail = function(itemId) {
  const item = window._historyItems?.find(it => it.id === itemId);
  if (!item || !item.prompt_params) { window.showToast("未找到提示词详情", "error"); return; }
  const pp = typeof item.prompt_params === "string" ? JSON.parse(item.prompt_params) : item.prompt_params;
  if (pp.source !== "composer_random") return;

  const selection = pp.selection || {};
  const fixedTypes = pp.fixed_types || [];
  const seed = pp.seed || 0;
  const prompt = pp.prompt || "";
  const negative = pp.negative_prompt || "";

  // 构建碎片卡片列表
  let cardsHtml = "";
  for (const [ft, content] of Object.entries(selection)) {
    const isFixed = fixedTypes.includes(ft);
    const typeColor = isFixed ? "var(--warning)" : "var(--primary)";
    const typeIcon = isFixed ? "📌" : "🎲";
    const escapedContent = window.escHtml(content);
    cardsHtml += `
      <div style="background:var(--panel-2);border-radius:8px;padding:10px 14px;border-left:3px solid ${typeColor}">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
          <span style="font-size:11px;color:${typeColor};font-weight:600;flex:1">${typeIcon} ${window.escHtml(ft)}</span>
          ${isFixed ? '<span style="font-size:10px;background:rgba(245,158,11,0.15);color:var(--warning);padding:1px 6px;border-radius:4px">固定</span>' : ""}
          <button style="background:transparent;border:1px solid var(--border-soft);color:var(--muted);font-size:11px;padding:2px 8px;border-radius:4px;cursor:pointer" onclick="window.copyText('${escapedContent.replace(/'/g, "\\'")}')">📋 复制</button>
        </div>
        <div style="font-size:12.5px;color:var(--text);line-height:1.6;white-space:pre-wrap;max-height:80px;overflow-y:auto">${escapedContent}</div>
      </div>`;
  }

  const bodyHtml = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <!-- 种子 -->
      <div style="display:flex;align-items:center;gap:8px">
        <label style="font-size:11px;color:var(--muted);min-width:40px">种子</label>
        <code style="background:var(--bg);padding:3px 10px;border-radius:6px;font-size:13px;color:var(--text);border:1px solid var(--border-soft)">${seed}</code>
      </div>

      <!-- 碎片列表 -->
      <div>
        <div style="font-size:11px;color:var(--muted);margin-bottom:8px">碎片选取（${Object.keys(selection).length} 个类型）</div>
        <div style="display:flex;flex-direction:column;gap:8px;max-height:260px;overflow-y:auto;padding-right:4px">${cardsHtml}</div>
      </div>

      <!-- 完整提示词（可折叠） -->
      <details style="border:1px solid var(--border-soft);border-radius:8px;overflow:hidden">
        <summary style="cursor:pointer;padding:8px 14px;background:var(--panel-2);font-size:12px;color:var(--muted);user-select:none;display:flex;align-items:center;gap:6px">
          📄 完整提示词
          <button style="margin-left:auto;background:transparent;border:1px solid var(--border-soft);color:var(--muted);font-size:11px;padding:2px 8px;border-radius:4px;cursor:pointer" onclick="event.stopPropagation();window.copyRandomPrompt()">📋 复制</button>
        </summary>
        <div style="padding:10px 14px">
          <textarea id="randomPromptText" readonly style="width:100%;min-height:100px;background:var(--bg);color:var(--text);border:1px solid var(--border-soft);border-radius:6px;padding:8px;font-size:12px;resize:vertical;line-height:1.6">${window.escHtml(prompt)}</textarea>
        </div>
      </details>

      <!-- 负面提示词（如果有） -->
      ${negative ? `<details style="border:1px solid var(--border-soft);border-radius:8px;overflow:hidden">
        <summary style="cursor:pointer;padding:8px 14px;background:var(--panel-2);font-size:12px;color:var(--muted);user-select:none">⚠️ 负面提示词</summary>
        <div style="padding:10px 14px;font-size:12px;color:var(--text-secondary);white-space:pre-wrap">${window.escHtml(negative)}</div>
      </details>` : ""}
    </div>`;

  let overlay = document.getElementById("randomPromptModal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "randomPromptModal";
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal" style="max-width:810px;width:92%">
        <div class="modal-header">
          <h2>🎲 随机组合提示词</h2>
          <button class="close-btn" onclick="document.getElementById('randomPromptModal').classList.remove('active')">✕</button>
        </div>
        <div class="modal-body" id="randomPromptModalBody"></div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="document.getElementById('randomPromptModal').classList.remove('active')">关闭</button>
          <button class="btn btn-primary" onclick="window.copyRandomPrompt()">📋 复制提示词</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
  }
  document.getElementById("randomPromptModalBody").innerHTML = bodyHtml;
  overlay.classList.add("active");
};

window.copyRandomPrompt = function() {
  const textarea = document.getElementById("randomPromptText");
  if (!textarea) return;
  navigator.clipboard.writeText(textarea.value).then(() => {
    window.showToast("提示词已复制", "success");
  }).catch(() => {
    textarea.select();
    document.execCommand("copy");
    window.showToast("提示词已复制", "success");
  });
};

window.copyText = function(text) {
  navigator.clipboard.writeText(text).then(() => {
    window.showToast("已复制", "success");
  }).catch(() => {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    window.showToast("已复制", "success");
  });
};

// -------------------------------------------------------------------
// 跑图
// -------------------------------------------------------------------
window.composerRun = async function () {
  const prompt = window.getComposedPrompt();
  if (!prompt) { window.showToast("请先组合提示词", "warn"); return; }

  const workflowPath = window.currentWorkflowPath();
  if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }

  const btn = document.getElementById("composerRunBtn");
  if (btn) { btn.disabled = true; btn.textContent = "发送中..."; }

  try {
    const body = Object.assign({
      prompt: prompt,
      negative_prompt: "",
      workflow_path: workflowPath,
      orientation: window.currentOrientation,
      quality: window.getQuality(),
    }, window.workflowExtraBody());
    const data = await window.api("/api/composer/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    window.showToast(`组合提示词已推送 (job ${data.job_id})`, "success");
    window.trackJob(data.job_id);
  } catch (e) {
    window.showToast("跑图失败: " + e.message, "error");
  } finally {
    if (btn) { btn.textContent = "🚀 跑图"; btn.disabled = false; }
  }
};

// -------------------------------------------------------------------
// 另存为普通提示词
// -------------------------------------------------------------------
window.composerSaveAsPrompt = async function () {
  const prompt = window.getComposedPrompt();
  if (!prompt) { window.showToast("请先组合提示词", "warn"); return; }

  const name = prompt("请输入提示词名称：", `组合 ${new Date().toLocaleString()}`);
  if (!name) return;

  try {
    const data = await window.api("/api/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        prompt: prompt,
        negative_prompt: "",
        tags: "组合创作",
      }),
    });
    window.showToast(`已另存为提示词 #${data.id}（${name}）`, "success");

    // 跳转到提示词 Tab，刷新列表并选中新提示词
    window._pendingSelectPromptId = data.id;
    // 切回全部分类
    window._currentCategoryId = null;
    window.UiState.set("categoryFilter", "");
    const btn = document.querySelector('.tab-btn[data-tab="promptTab"]');
    if (btn) {
      window.switchTab("promptTab", btn);
      // 重新加载列表并选中新条目
      window._promptPage = 1;
      window.loadPrompts();
    }
  } catch (e) {
    window.showToast("另存失败: " + e.message, "error");
  }
};

// -------------------------------------------------------------------
// 统计信息
// -------------------------------------------------------------------
window.updateComposerStats = function (data) {
  const el = document.getElementById("composerStats");
  if (!el) return;
  el.textContent = `来自 ${data.total_prompts} 条提示词 · 共 ${data.fragment_count} 个碎片`;
};

// -------------------------------------------------------------------
// 模板管理（localStorage）
// -------------------------------------------------------------------
window.saveComposerTemplate = async function () {
  const selected = window._composerSelection;
  const keys = Object.keys(selected);
  if (keys.length === 0) {
    window.showToast("请先选择至少一个碎片", "warn");
    return;
  }

  // 弹出命名对话框
  const name = prompt("请输入模板名称：", `模板 ${window._composerTemplates.length + 1}`);
  if (!name) return;

  // 组装碎片引用列表
  const fragments = [];
  for (const ft of FRAGMENT_TYPES) {
    const sel = selected[ft.key];
    if (sel && sel.prompt_id) {
      fragments.push({ prompt_id: sel.prompt_id, fragment_type: ft.key });
    }
  }

  // 可选的分类
  let category_id = null;
  // 简单版本：先不弹分类选择，留待后续 UI 扩展

  try {
    await window.api("/api/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, category_id, fragments }),
    });
    window.showToast(`模板"${name}"已保存`, "success");
    window._loadTemplates();
  } catch (e) {
    window.showToast("保存模板失败: " + e.message, "error");
  }
};

window.loadComposerTemplate = async function (index) {
  const tpl = window._composerTemplates[index];
  if (!tpl) return;
  try {
    // 从 API 获取完整解析（包含实时内容）
    const data = await window.api(`/api/templates/${tpl.id}/resolve`);
    const detail = data.template;
    if (!detail || !detail.fragments) return;

    // 重建选择状态
    const selection = {};
    let hasMissing = false;
    for (const frag of detail.fragments) {
      if (frag.content) {
        selection[frag.fragment_type] = {
          content: frag.content,
          prompt_id: frag.prompt_id,
          prompt_name: frag.source_name || "",
          type: frag.fragment_type,
        };
        if (!frag.source_exists) hasMissing = true;
      }
    }
    window._composerSelection = selection;
    // 同步列 UI
    for (const ft of FRAGMENT_TYPES) {
      window._updateColumnSelectionUI(ft.key);
    }
    window.renderComposerWorkbench();
    window._saveComposerState();
    const msg = `已加载模板"${detail.name}"`;
    window.showToast(hasMissing ? msg + "（部分来源已删除，显示缓存内容）" : msg, "info");
  } catch (e) {
    window.showToast("加载模板失败: " + e.message, "error");
  }
};

// 按 ID 直接加载模板（在模板列表还没加载时使用）
window.loadComposerTemplateById = async function (templateId) {
  try {
    const data = await window.api(`/api/templates/${templateId}/resolve`);
    const detail = data.template;
    if (!detail || !detail.fragments) return;
    const selection = {};
    let hasMissing = false;
    for (const frag of detail.fragments) {
      if (frag.content) {
        selection[frag.fragment_type] = {
          content: frag.content,
          prompt_id: frag.prompt_id,
          prompt_name: frag.source_name || "",
          type: frag.fragment_type,
        };
        if (!frag.source_exists) hasMissing = true;
      }
    }
    window._composerSelection = selection;
    for (const ft of FRAGMENT_TYPES) {
      window._updateColumnSelectionUI(ft.key);
    }
    window.renderComposerWorkbench();
    window._saveComposerState();
    window.showToast(hasMissing ? `已加载"${detail.name}"（部分来源已删除）` : `已加载"${detail.name}"`, "info");
  } catch (e) {
    window.showToast("加载模板失败: " + e.message, "error");
  }
};

window.deleteComposerTemplate = async function (index) {
  const tpl = window._composerTemplates[index];
  if (!tpl) return;
  if (!confirm(`删除模板"${tpl.name}"？`)) return;
  try {
    await window.api(`/api/templates/${tpl.id}`, { method: "DELETE" });
    window._composerTemplates.splice(index, 1);
    window.renderTemplateList();
    window.showToast(`模板"${tpl.name}"已删除`, "info");
  } catch (e) {
    window.showToast("删除失败: " + e.message, "error");
  }
};

window._renderTemplateListTo = function (containerId, countId) {
  const list = document.getElementById(containerId);
  const countEl = countId ? document.getElementById(countId) : null;
  if (!list) return;
  const templates = window._composerTemplates;
  if (countEl) countEl.textContent = templates.length;
  if (!templates || templates.length === 0) {
    list.innerHTML = '<div class="template-empty">暂无保存的模板</div>';
    return;
  }
  let html = "";
  for (let i = 0; i < templates.length; i++) {
    const t = templates[i];
    const syncOk = (t.fragments || []).every(f => f.source_exists !== false);
    const syncIcon = syncOk
      ? '<span class="template-sync-ok" title="所有碎片来源正常">●</span>'
      : '<span class="template-sync-warn" title="部分来源已删除">○</span>';
    const typeStr = (t.fragments || []).map(f => f.fragment_type).filter(Boolean).join(" · ");
    html += `
      <div class="template-item">
        <div class="template-item-info" onclick="window.loadComposerTemplate(${i})">
          <div class="template-item-name">${syncIcon} ${window.escHtml(t.name)}</div>
          <div class="template-item-types">${window.escHtml(typeStr)}</div>
        </div>
        <button class="btn-sm btn-ghost template-item-del" onclick="window.deleteComposerTemplate(${i})" title="删除">✕</button>
      </div>
    `;
  }
  list.innerHTML = html;
};

window.renderTemplateList = function () {
  window._renderTemplateListTo("templateList", "templateCount");
  if (document.getElementById("templateModalOverlay").classList.contains("active")) {
    window._renderTemplateListTo("templateModalList", "templateModalCount");
  }
};

window.openTemplateModal = function () {
  window._loadTemplates();
  document.getElementById("templateModalOverlay").classList.add("active");
  window._renderTemplateListTo("templateModalList", "templateModalCount");
};
window.closeTemplateModal = function () {
  document.getElementById("templateModalOverlay").classList.remove("active");
};

// -------------------------------------------------------------------
// 模板面板拖拽缩放
// -------------------------------------------------------------------
window.setupTemplatePanelResize = function () {
  // 模板已改为弹窗
};

// -------------------------------------------------------------------
// 碎片库面板
// -------------------------------------------------------------------
window.toggleFragmentLibrary = function () {
  const panel = document.getElementById("fragmentLibraryPanel");
  if (!panel) return;
  const showing = panel.style.display !== "none";
  if (showing) {
    window.hideFragmentLibrary();
  } else {
    panel.style.display = "flex";
    if (window.initFragmentLibrary) window.initFragmentLibrary();
  }
};

window.hideFragmentLibrary = function () {
  const panel = document.getElementById("fragmentLibraryPanel");
  if (panel) panel.style.display = "none";
  // 关闭后刷新 Composer
  window._composerDataStale = true;
  window.refreshComposer();
};

// 查看碎片完整内容（弹窗）
window._showFullFrag = function (type, promptId) {
  const grouped = window._composerFragmentData?.grouped;
  if (!grouped || !grouped[type]) return;
  const frag = grouped[type].find(f => {
    if (f.fragment_id) return f.fragment_id === promptId;
    return f.prompt_id === promptId;
  });
  if (!frag) return;

  document.getElementById("fragFullContent").textContent = frag.content;
  document.getElementById("fragFullType").textContent = type;

  // 来源显示为可点击链接
  const sourceEl = document.getElementById("fragFullSource");
  if (frag.source_names && frag.source_names.length > 1) {
    const links = frag.source_names.map(s => {
      // 从 "古风窗边·逆光回眸 (ID:116)" 提取 ID
      const m = s.match(/ID:(\d+)/);
      const name = s.replace(/\s*\(ID:\d+\)/, "");
      if (m) {
        return `<a href="#" onclick="event.preventDefault();window._closeFullFrag();window.jumpToPrompt(${m[1]})" style="color:var(--primary);text-decoration:none" title="跳转到此提示词">${window.escHtml(name)}</a>`;
      }
      return window.escHtml(s);
    });
    sourceEl.innerHTML = `出现在 <strong>${frag.dup_count}</strong> 条提示词中:<br>${links.join("、")}`;
  } else if (frag.prompt_id && frag.prompt_id > 0) {
    sourceEl.innerHTML = `来源: <a href="#" onclick="event.preventDefault();window._closeFullFrag();window.jumpToPrompt(${frag.prompt_id})" style="color:var(--primary);text-decoration:none">${window.escHtml(frag.prompt_name || `#${frag.prompt_id}`)}</a>`;
  } else if (frag.source === "library") {
    sourceEl.innerHTML = `来源: 📦 碎片库`;
  } else {
    sourceEl.textContent = `来源: ${frag.prompt_name || ""}`;
  }

  document.getElementById("fragFullModal").classList.add("active");
};
window._closeFullFrag = function () {
  document.getElementById("fragFullModal").classList.remove("active");
};

// 工作台碎片编辑：实时更新选中内容 + 自动增高
window._onFragEdit = function (el) {
  const type = el.dataset.fragType;
  if (window._composerSelection[type]) {
    window._composerSelection[type].content = el.value;
    window._saveComposerState();
  }
  // 自动增高：重置高度再设为 scrollHeight + 2px 补偿
  el.style.height = "auto";
  el.style.height = (el.scrollHeight + 2) + "px";
};

window._detectConflicts = function (promptText) {
  const warnings = [];

  // 提取各碎片内容
  const frags = {};
  const pattern = /【([^】]+)】\s*(.*?)(?=\n【|$)/g;
  let m;
  while ((m = pattern.exec(promptText)) !== null) {
    frags[m[1].trim()] = m[2].trim();
  }

  // 1. 服装矛盾检测
  const clothTypes = [];
  if (frags["人物服饰"]) {
    const cloth = frags["人物服饰"];
    if (/抹胸|吊带|背心/.test(cloth)) clothTypes.push("露肩上衣");
    if (/毛衣|外套|开衫/.test(cloth)) clothTypes.push("外套");
    if (/短袖|T恤/.test(cloth)) clothTypes.push("短袖");
    if (/长裙|连衣裙/.test(cloth)) clothTypes.push("长裙");
    if (/短裤|裙子/.test(cloth)) clothTypes.push("下装");
    if (clothTypes.length >= 2 && clothTypes.includes("露肩上衣") && clothTypes.includes("外套")) {
      warnings.push("【人物服饰】可能同时描述多件上衣（抹胸/吊带 + 毛衣/外套），请确认");
    }
  }

  // 2. 姿态动作中引用的衣物与人物服饰是否一致
  if (frags["姿态动作"] && frags["人物服饰"]) {
    const pose = frags["姿态动作"];
    const cloth = frags["人物服饰"];
    // 检查姿态中提到的衣物类型是否与服饰一致
    if (/毛衣/.test(pose) && /抹胸|吊带/.test(cloth)) {
      warnings.push('【姿态动作】提到"毛衣"但【人物服饰】描述的是抹胸/吊带，请统一');
    }
    if (/外套/.test(pose) && !/外套/.test(cloth)) {
      warnings.push('【姿态动作】提到"外套"但【人物服饰】未描述外套');
    }
  }

  // 3. 画风冲突检测
  if (frags["画风技术"]) {
    const style = frags["画风技术"];
    const styleGroups = [
      { type: "写实", keywords: ["真人", "写实", "照片", "摄影", "胶片", "写真"] },
      { type: "动漫", keywords: ["动漫", "二次元", "插画", "CG", "厚涂", "赛璐璐"] },
      { type: "情绪", keywords: ["治愈", "温馨", "甜美", "柔和"] },
      { type: "压迫", keywords: ["压迫感", "张力", "冲击力", "激烈"] },
    ];

    const matched = styleGroups.filter(g => g.keywords.some(k => style.includes(k)));
    // 写实与动漫冲突
    const isReal = matched.some(g => g.type === "写实");
    const isAnime = matched.some(g => g.type === "动漫");
    if (isReal && isAnime) {
      warnings.push("【画风技术】同时包含写实和动漫关键词，风格矛盾。请二选一");
    }
    // 情绪冲突
    const isHealing = matched.some(g => g.type === "情绪");
    const isIntense = matched.some(g => g.type === "压迫");
    if (isHealing && isIntense) {
      warnings.push('【画风技术】"治愈"和"压迫感"情绪矛盾，请统一');
    }
  }

  // 4. 人物身材与人物面部重复检测
  if (frags["人物身材"] && frags["人物面部"]) {
    const body = frags["人物身材"];
    const face = frags["人物面部"];
    // 检测身材中是否混入了面容描述
    const faceKeywords = ["清纯", "可爱", "面容", "长相", "甜美", "大眼睛", "五官"];
    const overlaps = faceKeywords.filter(k => body.includes(k));
    if (overlaps.length > 0) {
      warnings.push(`【人物身材】中包含面容描述词"${overlaps.join("、")}"，建议移到【人物面部】`);
    }
  }

  return warnings;
};


