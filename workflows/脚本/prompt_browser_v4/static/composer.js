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
window._composerFragmentData = null; // 缓存碎片数据
window._composerTemplates = [];
window._templateCategories = [];

// -------------------------------------------------------------------
// 初始化
// -------------------------------------------------------------------
window.initComposer = function () {
  window._restoreComposerState();
  // 恢复工作台折叠状态
  const bottomCollapsed = window.UiState.get("composerBottomCollapsed", true);
  window._applyComposerBottomState(bottomCollapsed);
  // 从 DB 加载模板
  window._loadTemplates().then(() => {
    // 首次加载时尝试迁移 localStorage 旧模板
    window._migrateLocalTemplates();
  });
  window.setupTemplatePanelResize();
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

// 工作台折叠/展开
window._applyComposerBottomState = function (collapsed) {
  const bottom = document.getElementById("composerBottom");
  const arrow = document.getElementById("composerBottomArrow");
  if (!bottom || !arrow) return;
  if (collapsed) {
    bottom.classList.add("collapsed");
    arrow.textContent = "▼";
  } else {
    bottom.classList.remove("collapsed");
    arrow.textContent = "▲";
  }
};

window.toggleComposerBottom = function () {
  const bottom = document.getElementById("composerBottom");
  if (!bottom) return;
  const nowCollapsed = !bottom.classList.contains("collapsed");
  window._applyComposerBottomState(nowCollapsed);
  window.UiState.set("composerBottomCollapsed", nowCollapsed);
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
    window.renderComposerColumns(data.grouped);
    window.updateComposerStats(data);
    // 保留已选碎片（如果来源提示词仍在结果中）
    window._syncComposerSelection(data.grouped);
    // 确保工作台与 restored state 同步
    window.renderComposerWorkbench();
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

// 同步已选：如果某个碎片来源的提示词不在当前筛选范围，自动移除
window._syncComposerSelection = function (grouped) {
  let changed = false;
  for (const type of Object.keys(window._composerSelection)) {
    const sel = window._composerSelection[type];
    if (!sel) continue;
    const available = (grouped[type] || []).some(
      f => f.prompt_id === sel.prompt_id && f.content === sel.content
    );
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
    header.innerHTML = `
      <span class="composer-col-icon">${ft.icon}</span>
      <span class="composer-col-title">${ft.label}</span>
      <span class="composer-col-count">${(grouped[ft.key] || []).length}</span>
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
        card.dataset.content = f.content;

        // 缩略内容
        const contentShort = f.content.length > 40 ? f.content.slice(0, 40) + "…" : f.content;
        card.innerHTML = `
          <div class="frag-content">${window.escHtml(contentShort)}</div>
          <div class="frag-source" title="来源: ${window.escHtml(f.prompt_name)}">${window.escHtml(f.prompt_name || `#${f.prompt_id}`)}</div>
          ${isSelected ? '<div class="frag-check">✓</div>' : ''}
        `;

        // 点击选择
        card.addEventListener("click", () => window.selectComposerFragment(ft.key, f));
        list.appendChild(card);
      }
    }

    col.appendChild(list);
    container.appendChild(col);
  }
};

// 判断碎片是否已被选中
window._isFragmentSelected = function (type, fragment) {
  const sel = window._composerSelection[type];
  if (!sel) return false;
  return sel.prompt_id === fragment.prompt_id && sel.content === fragment.content;
};

// -------------------------------------------------------------------
// 选择/取消碎片
// -------------------------------------------------------------------
window.selectComposerFragment = function (type, fragment) {
  // 如果已选同一碎片，则取消选择
  if (window._isFragmentSelected(type, fragment)) {
    delete window._composerSelection[type];
    window._updateColumnSelectionUI(type);
    window.renderComposerWorkbench();
    window._saveComposerState();
    return;
  }

  // 选择新碎片
  window._composerSelection[type] = {
    content: fragment.content,
    prompt_id: fragment.prompt_id,
    prompt_name: fragment.prompt_name,
    type: type,
  };
  window._updateColumnSelectionUI(type);
  window.renderComposerWorkbench();
  window._saveComposerState();
};

// 移除已选
window.removeComposerFragment = function (type) {
  delete window._composerSelection[type];
  window._updateColumnSelectionUI(type);
  window.renderComposerWorkbench();
  window._saveComposerState();
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
    html += `
      <div class="workbench-frag" style="border-left: 3px solid ${ft.color}">
        <div class="workbench-frag-header">
          <span class="workbench-frag-type" style="color:${ft.color}" title="来源：${window.escHtml(sel.prompt_name || `#${sel.prompt_id}`)}">${ft.icon} ${ft.key}</span>
          <div class="workbench-frag-actions">
            <button class="wfa-btn wfa-copy" onclick="window.copyComposerFragment('${ft.key.replace(/'/g, "\\'")}')" title="复制此碎片">📋</button>
            <button class="wfa-btn wfa-del" onclick="window.removeComposerFragment('${ft.key}')" title="移除">✕</button>
          </div>
        </div>
        <div class="workbench-frag-body">${window.escHtml(sel.content)}</div>
      </div>
    `;
  }

  workbench.innerHTML = html;

  // 更新跑图按钮状态
  const composed = window.getComposedPrompt();
  document.getElementById("composerRunBtn").disabled = !composed;
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
  // 更新所有列 UI
  for (const ft of FRAGMENT_TYPES) {
    window._updateColumnSelectionUI(ft.key);
  }
  window.renderComposerWorkbench();
  window._saveComposerState();
};

// -------------------------------------------------------------------
// 随机组合
// -------------------------------------------------------------------
window.randomComposer = function () {
  if (!window._composerFragmentData) {
    window.showToast("请先加载碎片数据", "warn");
    return;
  }
  const grouped = window._composerFragmentData.grouped;
  window._composerSelection = {};
  for (const ft of FRAGMENT_TYPES) {
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
  window.showToast("已随机组合", "info");
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
    const body = {
      prompt: prompt,
      negative_prompt: "",
      workflow_path: workflowPath,
      orientation: window.currentOrientation,
      quality: window.getQuality(),
    };
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

window.renderTemplateList = function () {
  const list = document.getElementById("templateList");
  const countEl = document.getElementById("templateCount");
  if (!list) return;
  const templates = window._composerTemplates;
  if (countEl) countEl.textContent = templates.length;
  if (!templates || templates.length === 0) {
    list.innerHTML = '<div class="template-empty">暂无保存的模板<br><small>组合好碎片后点击"保存模板"</small></div>';
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

// -------------------------------------------------------------------
// 模板面板拖拽缩放
// -------------------------------------------------------------------
window.setupTemplatePanelResize = function () {
  const handle = document.getElementById("templateResizeHandle");
  const sidebar = document.querySelector(".template-sidebar");
  if (!handle || !sidebar) return;

  // 恢复上次宽度
  const savedW = window.UiState.get("templateSidebarWidth", null);
  if (savedW) sidebar.style.width = savedW + "px";

  let dragging = false;
  handle.addEventListener("mousedown", (e) => {
    dragging = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const container = sidebar.parentElement;
    const rect = container.getBoundingClientRect();
    const maxW = rect.width * 0.4;
    const minW = 140;
    let w = rect.right - e.clientX;
    w = Math.max(minW, Math.min(maxW, w));
    sidebar.style.width = w + "px";
  });

  document.addEventListener("mouseup", () => {
    if (dragging) {
      dragging = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      // 保存宽度
      const w = parseFloat(sidebar.style.width);
      if (w) window.UiState.set("templateSidebarWidth", Math.round(w));
    }
  });
};
