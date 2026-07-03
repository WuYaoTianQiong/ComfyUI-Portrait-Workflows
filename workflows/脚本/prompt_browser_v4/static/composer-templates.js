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

  // 使用自定义模态框替代原生 prompt
  const defaultName = `组合 ${new Date().toLocaleString()}`;
  const html = `
    <div class="modal-header">
      <h2>💾 另存为提示词</h2>
    </div>
    <div class="modal-body">
      <p style="font-size:12px;color:var(--muted);margin-bottom:12px">将当前组合的提示词保存到提示词库，可在"提示词"标签页的"🔧 组合创作"分类中查看</p>
      <div class="form-group">
        <label>提示词名称</label>
        <input type="text" id="saveAsPromptName" class="form-input" value="${defaultName}" style="width:100%" autofocus>
      </div>
      <div class="form-group" style="margin-top:8px">
        <label>标签（可选，逗号分隔）</label>
        <input type="text" id="saveAsPromptTags" class="form-input" value="组合创作" style="width:100%">
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-sm btn-primary" onclick="window._doSaveAsPrompt()">保存</button>
      <button class="btn btn-sm btn-ghost" onclick="window.closeModal()">取消</button>
    </div>
  `;
  window.showModal(html);
  // 自动选中名称输入框的全部文本
  setTimeout(() => {
    const input = document.getElementById("saveAsPromptName");
    if (input) { input.focus(); input.select(); }
  }, 100);
};

window._doSaveAsPrompt = async function () {
  const name = document.getElementById("saveAsPromptName")?.value?.trim();
  const tags = document.getElementById("saveAsPromptTags")?.value?.trim() || "组合创作";
  if (!name) { window.showToast("请输入提示词名称", "warn"); return; }

  const prompt = window.getComposedPrompt();
  try {
    const data = await window.api("/api/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        prompt: prompt,
        negative_prompt: "",
        tags: tags,
        auto_categorize: true,  // 新增：自动分类到"组合创作"
      }),
    });
    window.closeModal();
    window.showToast(`✅ 已保存到提示词库 #${data.id}（${name}）`, "success");

    // 跳转到提示词 Tab，并筛选"组合创作"分类
    const btn = document.querySelector('.tab-btn[data-tab="promptTab"]');
    if (btn) {
      window.switchTab("promptTab", btn);
      // 延迟加载确保 tab 切换完成，并自动筛选到"组合创作"分类
      setTimeout(() => {
        window._promptPage = 1;
        // 自动切换到"组合创作"分类（如果有）
        window._pendingCategoryFilter = "组合创作";
        window.loadPrompts();
      }, 200);
    }
  } catch (e) {
    window.showToast("另存失败: " + e.message, "error");
  }
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

  // 找到保存模板按钮并添加反馈
  const saveBtn = document.querySelector('.composer-toolbar-right .btn-ghost[onclick*="saveComposerTemplate"]');
  if (saveBtn) window.showButtonFeedback(saveBtn, '💾 保存中...', 2000);

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