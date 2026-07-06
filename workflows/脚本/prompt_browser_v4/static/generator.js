// generator.js - 生成控制模块
// 依赖：utils.js, workflow.js, prompt.js

// -------------------------------------------------------------------
// 跑图辅助：统一锁 + 按钮状态
// -------------------------------------------------------------------
window._runBtnState = function(btn, loadingText) {
  const orig = btn ? btn.innerHTML : '';
  return {
    loading() { if (btn) { btn.disabled = true; btn.textContent = loadingText; } },
    restore() { if (btn) { btn.disabled = false; btn.innerHTML = orig; } },
  };
};

// 占位进度：在 trackJob 第一次轮询返回前，立即显示"排队中..."避免空窗期
window._showPendingProgress = function(title) {
  const area = document.getElementById("outputArea");
  if (!area) return;
  area.classList.add("show");
  document.getElementById("outputTitle").textContent = title || "生成中";
  document.getElementById("progressFill").style.width = "0%";
  document.getElementById("progressInfo").textContent = "排队中...";
};

// -------------------------------------------------------------------
// 生成控制
// -------------------------------------------------------------------

window.runPrompt = async function(id) {
  return window.withLock("runPrompt", async () => {
    id = id || window.selectedId;
    if (!id) return;
    const workflowPath = window.currentWorkflowPath();
    if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }
    const btnState = window._runBtnState(document.getElementById("runBtn"), "发送中...");
    btnState.loading();
    try {
      const body = Object.assign({
        id, workflow_path: workflowPath,
        orientation: window.currentOrientation,
        quality: window.getQuality(),
      }, window.workflowExtraBody());
      const data = await window.api("/api/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      window.showToast(`已推送 ${data.dimensions || ""} (job ${data.job_id})`, "success");
      await window.markPromptUsed(id);
      window._showPendingProgress("生成中");
      window.trackJob(data.job_id);
    } catch (e) {
      window.showToast("跑图失败: " + e.message, "error");
    } finally {
      btnState.restore();
      window.updateRunBtn();
    }
  });
};

window.batchRun = async function() {
  return window.withLock("batchRun", async () => {
    if (!window.selectedIds.size) return;
    const workflowPath = window.currentWorkflowPath();
    if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }
    const ids = Array.from(window.selectedIds);
    const btnState = window._runBtnState(document.getElementById("runBtn"), `批量 (${ids.length})...`);
    btnState.loading();
    try {
      const body = Object.assign({
        items: ids.map(id => ({ prompt_id: id, seed: 0 })),
        workflow_path: workflowPath,
        orientation: window.currentOrientation,
        quality: window.getQuality(),
        title: `批量跑图 (${ids.length} 张)`,
      }, window.workflowExtraBody());
      const data = await window.api("/api/batch_generate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (data.errors?.length) window.showToast(`${data.errors.length} 个任务提交失败`, "error");
      for (const id of ids) await window.markPromptUsed(id);
      window._showPendingProgress(`批量生成 (${ids.length} 张)`);
      window.trackJob(data.job_id);
    } catch (e) {
      window.showToast("批量提交失败: " + e.message, "error");
    } finally {
      btnState.restore();
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
    const btnState = window._runBtnState(document.getElementById("varConfirmBtn"), "提交中...");
    btnState.loading();
    const count = parseInt(document.getElementById("varCount").value) || 4;
    const startSeed = document.getElementById("varStartSeed").value;
    window.closeVarModal();
    try {
      const items = [];
      for (let i = 0; i < count; i++) {
        items.push({
          prompt_id: window.selectedId,
          seed: startSeed ? parseInt(startSeed) + i : Math.floor(Math.random() * 999999999999999),
        });
      }
      const body = Object.assign({
        items, workflow_path: workflowPath,
        orientation: window.currentOrientation,
        quality: window.getQuality(),
        title: `变体生成 (${count} 张)`,
      }, window.workflowExtraBody());
      const data = await window.api("/api/batch_generate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      window._showPendingProgress(`变体生成 (${count} 张)`);
      window.trackJob(data.job_id);
      await window.markPromptUsed(window.selectedId);
    } catch (e) {
      window.showToast("变体生成失败: " + e.message, "error");
    } finally {
      btnState.restore();
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
  const allChecked = count > 0 && window.allPrompts.length > 0 && window.allPrompts.every(p => window.selectedIds.has(p.id));
  allCheck.checked = allChecked;
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
  const hasActiveJobs = window.activeJobs && window.activeJobs.size > 0;
  const online = window.comfyStatus === "online" && wf && !hasActiveJobs;
  const btn = document.getElementById("runBtn");
  if (hasActiveJobs) {
    btn.textContent = "⏳ 生成中...";
    btn.disabled = true;
  } else if (window.selectedIds.size >= 2) {
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

  // 同步 Composer 按钮
  const composerBtn = document.getElementById("composerRunBtn");
  if (composerBtn) {
    composerBtn.disabled = !wf || hasActiveJobs;
    if (hasActiveJobs) composerBtn.textContent = "⏳ 生成中...";
  }
  const composerBatchBtn = document.getElementById("composerBatchRunBtn");
  if (composerBatchBtn) {
    composerBatchBtn.disabled = !wf || hasActiveJobs;
    if (hasActiveJobs) composerBatchBtn.textContent = "⏳ 生成中...";
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
