// generator.js - 生成控制模块
// 依赖：utils.js, workflow.js, prompt.js

// -------------------------------------------------------------------
// 生成控制
// -------------------------------------------------------------------

window.runPrompt = async function(id) {
  return window.withLock("runPrompt", async () => {
    id = id || window.selectedId;
    if (!id) return;
    const workflowPath = window.currentWorkflowPath();
    if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }
    const btn = document.getElementById("runBtn");
    btn.disabled = true; btn.textContent = "发送中...";
    try {
      const body = Object.assign({
        id,
        workflow_path: workflowPath,
        orientation: window.currentOrientation,
        quality: window.getQuality()
      }, window.workflowExtraBody());
      const data = await window.api("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      window.showToast(`已推送 ${data.dimensions || ""} (job ${data.job_id})`, "success");
      
      await window.markPromptUsed(id);
      
      window.trackJob(data.job_id);
    } catch (e) {
      window.showToast("跑图失败: " + e.message, "error");
    } finally {
      btn.textContent = "🚀 跑图";
      window.updateRunBtn();
    }
  });
};

window.batchRun = async function() {
  return window.withLock("batchRun", async () => {
    if (!window.selectedIds.size) return;
    const workflowPath = window.currentWorkflowPath();
    if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }
    const btn = document.getElementById("runBtn");
    if (btn) btn.disabled = true;
    const ids = Array.from(window.selectedIds);
    const items = ids.map(id => ({ prompt_id: id, seed: 0 }));
    try {
      const body = Object.assign({
        items,
        workflow_path: workflowPath,
        orientation: window.currentOrientation,
        quality: window.getQuality(),
        title: `批量跑图 (${items.length} 张)`
      }, window.workflowExtraBody());
      const data = await window.api("/api/batch_generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (data.errors && data.errors.length) {
        window.showToast(`${data.errors.length} 个任务提交失败`, "error");
      }
      
      for (const id of ids) {
        await window.markPromptUsed(id);
      }
      
      window.trackJob(data.job_id);
    } catch (e) {
      window.showToast("批量提交失败: " + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  });
};

window.openVariationDialog = function() { document.getElementById("varModalOverlay").classList.add("active"); };
window.closeVarModal = function() { document.getElementById("varModalOverlay").classList.remove("active"); };

window.startVariationRun = async function() {
  return window.withLock("startVariationRun", async () => {
    if (!window.selectedId) return;
    const workflowPath = window.currentWorkflowPath();
    if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }
    const confirmBtn = document.getElementById("varConfirmBtn");
    if (confirmBtn) confirmBtn.disabled = true;
    const count = parseInt(document.getElementById("varCount").value) || 4;
    const startSeed = document.getElementById("varStartSeed").value;
    window.closeVarModal();
    const items = [];
    for (let i = 0; i < count; i++) {
      const seed = startSeed ? parseInt(startSeed) + i : Math.floor(Math.random() * 999999999999999);
      items.push({ prompt_id: window.selectedId, seed });
    }
    try {
      const body = Object.assign({
        items,
        workflow_path: workflowPath,
        orientation: window.currentOrientation,
        quality: window.getQuality(),
        title: `变体生成 (${items.length} 张)`
      }, window.workflowExtraBody());
      const data = await window.api("/api/batch_generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      window.trackJob(data.job_id);
    } catch (e) {
      window.showToast("变体生成失败: " + e.message, "error");
    } finally {
      if (confirmBtn) confirmBtn.disabled = false;
    }
  });
};

window.onMainAction = function() {
  if (window.selectedIds.size >= 2) return window.batchRun();
  if (window.selectedIds.size === 1) {
    const id = window.selectedIds.values().next().value;
    return window.runPrompt(id);
  }
  if (window.selectedId) return window.runPrompt(window.selectedId);
};

// -------------------------------------------------------------------
// 选择控制
// -------------------------------------------------------------------

window.toggleItemSelect = function(id, checked) {
  if (checked) window.selectedIds.add(id); else window.selectedIds.delete(id);
  window.lastClickedId = id;
  window.UiState.set("selectedIds", Array.from(window.selectedIds));
  window.updateRunBtn();
  window.updateSelectionBar();
};

window.toggleSelectAll = function(checked) {
  if (checked) window.allPrompts.forEach(p => window.selectedIds.add(p.id));
  else window.selectedIds.clear();
  window.renderList(window.allPrompts);
  window.updateRunBtn();
  window.updateSelectionBar();
  window.UiState.set("selectedIds", Array.from(window.selectedIds));
};

window.updateSelectionBar = function() {
  const bar = document.getElementById("selectionBar");
  const info = document.getElementById("selectionInfo");
  const allCheck = document.getElementById("selectAllCheck");
  const count = window.selectedIds.size;
  bar.classList.toggle("show", count > 0);
  info.textContent = `已选 ${count} 项`;
  allCheck.checked = count > 0 && window.allPrompts.length > 0 && window.allPrompts.every(p => window.selectedIds.has(p.id));
};

window.clearSelection = function() {
  window.selectedIds.clear();
  window.renderList(window.allPrompts);
  window.updateRunBtn();
  window.updateSelectionBar();
  window.UiState.set("selectedIds", []);
};

// -------------------------------------------------------------------
// 运行按钮更新
// -------------------------------------------------------------------

window.updateRunBtn = function() {
  const wf = window.currentWorkflowPath();
  const online = window.comfyStatus === "online" && wf;
  const btn = document.getElementById("runBtn");
  if (window.selectedIds.size >= 2) {
    btn.textContent = `🚀 批量跑图 (${window.selectedIds.size})`;
    btn.disabled = !online;
  } else if (window.selectedIds.size === 1) {
    btn.textContent = "🚀 跑图";
    btn.disabled = !online;
  } else if (window.selectedId) {
    btn.textContent = "🚀 跑图";
    btn.disabled = !online;
  } else {
    btn.textContent = "🚀 跑图";
    btn.disabled = true;
  }
};

// -------------------------------------------------------------------
// 方向和质量
// -------------------------------------------------------------------

window.toggleOrientation = function() {
  window.currentOrientation = window.currentOrientation === "portrait" ? "landscape" : "portrait";
  document.getElementById("orientBtn").textContent = window.currentOrientation === "portrait" ? "📱" : "🖥️";
  document.getElementById("orientBtn").title = window.currentOrientation === "portrait" ? "竖屏" : "横屏";
  window.UiState.set("orientation", window.currentOrientation);
};

window.getQuality = function() { return document.getElementById("qualitySelect").value; };
window.onQualityChange = function() { window.UiState.set("quality", window.getQuality()); };
