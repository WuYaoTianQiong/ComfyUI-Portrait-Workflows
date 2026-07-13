// 跑图
// -------------------------------------------------------------------
window.composerRun = async function () {
  return window.withLock("composerRun", async () => {
    const prompt = window.getComposedPrompt();
    if (!prompt) { window.showToast("请先组合提示词", "warn"); return; }
    const workflowPath = window.currentWorkflowPath();
    if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }
    const btnState = window._runBtnState(document.getElementById("composerRunBtn"), "发送中...");
    btnState.loading();
    try {
      const body = Object.assign({
        prompt, negative_prompt: "",
        workflow_path: workflowPath,
        orientation: window.currentOrientation,
        quality: window.getQuality(),
      }, window.workflowExtraBody());
      const data = await window.api("/api/composer/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      window.showToast(`组合提示词已推送 (job ${data.job_id})`, "success");
      window._showPendingProgress("组合创作生成中");
      window.trackJob(data.job_id);
    } catch (e) {
      window.showToast("跑图失败: " + e.message, "error");
    } finally {
      btnState.restore();
    }
  });
};

// -------------------------------------------------------------------
// 另存为普通提示词
// -------------------------------------------------------------------
window.composerSaveAsPrompt = async function () {
  const composed = window.getComposedPrompt();
  if (!composed) { window.showToast("请先组合提示词", "warn"); return; }

  // 复用编辑弹窗，预填组合内容
  window._fragmentEditMode = false;
  window._promptFormSnapshot = null;
  window._customFragmentKeys = [];

  document.getElementById("f_id").value = "";
  document.getElementById("trialRunBtn").style.display = "none";  // 另存为模式不显示试跑
  document.getElementById("modalTitle").textContent = "💾 另存为提示词";
  document.getElementById("f_name").value = `组合 ${new Date().toLocaleString()}`;
  document.getElementById("f_prompt").value = composed;
  document.getElementById("f_neg").value = "";
  ["f_steps", "f_cfg", "f_sampler", "f_seed", "f_model", "f_note"].forEach(fid => document.getElementById(fid).value = "");
  document.getElementById("f_tags").value = "组合创作";
  window.setRating(0);

  const fc = document.getElementById("f_fragments");
  const btn = document.getElementById("f_toggleFragBtn");
  const ta = document.getElementById("f_prompt");
  if (fc) fc.style.display = "none";
  if (btn) { btn.style.display = ""; btn.textContent = "📝 切换到分段编辑"; }
  if (ta) ta.style.display = "";

  await window.loadCategoriesForSelect();
  await window.loadTagsForSelect();

  document.getElementById("modalOverlay").classList.add("active");
};



// -------------------------------------------------------------------
// 保存模板（添加按钮反馈）
// -------------------------------------------------------------------
window.saveComposerTemplateWithFeedback = async function () {
  const btn = event.target;
  if (btn) window.showButtonFeedback(btn, '💾 保存中...', 2000);
  await window.saveComposerTemplate();
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
  return window.withLock("saveComposerTemplate", async () => {
    const selected = window._composerSelection;
    if (Object.keys(selected).length === 0) {
      window.showToast("请先选择至少一个碎片", "warn");
      return;
    }
    const name = prompt("请输入模板名称：", `模板 ${window._composerTemplates.length + 1}`);
    if (!name) return;

    const fragments = [];
    for (const ft of FRAGMENT_TYPES) {
      const sel = selected[ft.key];
      if (sel && sel.prompt_id) fragments.push({ prompt_id: sel.prompt_id, fragment_type: ft.key });
    }

    try {
      await window.api("/api/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, category_id: null, fragments }),
      });
      window.showToast(`模板"${name}"已保存`, "success");
      window._loadTemplates();
    } catch (e) {
      window.showToast("保存模板失败: " + e.message, "error");
    }
  });
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
  return window.withLock("deleteComposerTemplate", async () => {
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
  });
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