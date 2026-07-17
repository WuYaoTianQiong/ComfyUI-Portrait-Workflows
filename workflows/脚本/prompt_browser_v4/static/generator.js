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

// 补全缺图：先拉缺图清单 -> 审核模态框（看清有哪些 + 可取消部分）-> 提交勾选子集
window.generateMissing = async function() {
  return window.withLock("generateMissing", async () => {
    const workflowPath = window.currentWorkflowPath();
    if (!workflowPath) { window.showToast("请先选择工作文件", "error"); return; }
    if (window.comfyStatus !== "online") { window.showToast("ComfyUI 未连接", "error"); return; }
    if (window.activeJobs && window.activeJobs.size > 0) { window.showToast("有任务进行中，请等待完成后再补全", "error"); return; }
    let items = [];
    try {
      const data = await window.api("/api/generate_missing/list", { timeout: 30000 });
      items = data.items || [];
    } catch (e) { window.showToast("获取缺图清单失败: " + e.message, "error"); return; }
    if (!items.length) { window.showToast("没有缺图的提示词，全部已生成 ✅", "success"); return; }
    window._openMissingModal(items, workflowPath);
  });
};

// 审核模态框：展示缺图清单，默认全选，用户可取消部分或用搜索过滤
window._openMissingModal = function(items, workflowPath) {
  const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"']/g, (m) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]
  ));
  const rows = items.map((it) => {
    const ps = [];
    if (it.width && it.height) ps.push(it.width + "×" + it.height);
    if (it.model) ps.push(it.model);
    if (it.sampler) ps.push(it.sampler);
    if (it.steps) ps.push("步" + it.steps);
    if (it.cfg_scale != null && it.cfg_scale !== "") ps.push("cfg" + it.cfg_scale);
    const paramStr = ps.length ? ps.join(" · ") : "默认参数";
    return '<div class="mm-row" data-name="' + (it.name || "").toLowerCase() + '" data-cat="' + (it.category || "").toLowerCase() + '">'
      + '<label class="mm-check">'
      + '<input type="checkbox" class="mm-item" value="' + it.id + '" checked>'
      + '<span class="mm-title">' + esc(it.name || "(未命名)") + '</span>'
      + '<span class="mm-cat">' + esc(it.category || "") + '</span>'
      + '<span class="mm-params">' + esc(paramStr) + '</span>'
      + '</label></div>';
  }).join("");
  const html =
    '<div class="mm-head">'
    + '<div class="mm-count">补全缺图 · 共 <b id="mmTotal">' + items.length + '</b> 条 · 已选 <b id="mmSel">' + items.length + '</b> 条</div>'
    + '<div class="mm-tools">'
    + '<input id="mmSearch" class="mm-search" placeholder="搜索标题/分类…">'
    + '<button class="btn btn-sm" id="mmAll">全选</button>'
    + '<button class="btn btn-sm" id="mmNone">全不选</button>'
    + '<button class="btn btn-sm" id="mmInv">反选</button>'
    + '</div></div>'
    + '<div class="mm-list" id="mmList">' + rows + '</div>'
    + '<div class="mm-foot">'
    + '<button class="btn" id="mmCancel">取消</button>'
    + '<button class="btn btn-primary" id="mmOk">确定生成已选</button>'
    + '</div>';
  window.showModal(html);
  const list = document.getElementById("mmList");
  const selEl = document.getElementById("mmSel");
  const syncSel = () => { selEl.textContent = list.querySelectorAll(".mm-item:checked").length; };
  list.addEventListener("change", syncSel);
  document.getElementById("mmSearch").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    list.querySelectorAll(".mm-row").forEach((r) => {
      const hit = !q || r.dataset.name.indexOf(q) >= 0 || r.dataset.cat.indexOf(q) >= 0;
      r.style.display = hit ? "" : "none";
    });
  });
  document.getElementById("mmAll").onclick = () => { list.querySelectorAll(".mm-item").forEach((c) => { c.checked = true; }); syncSel(); };
  document.getElementById("mmNone").onclick = () => { list.querySelectorAll(".mm-item").forEach((c) => { c.checked = false; }); syncSel(); };
  document.getElementById("mmInv").onclick = () => { list.querySelectorAll(".mm-item").forEach((c) => { c.checked = !c.checked; }); syncSel(); };
  document.getElementById("mmCancel").onclick = () => window.closeModal();
  document.getElementById("mmOk").onclick = () => {
    const ids = [];
    list.querySelectorAll(".mm-item:checked").forEach((c) => ids.push(parseInt(c.value, 10)));
    window.closeModal();
    if (!ids.length) { window.showToast("未选择任何提示词", "error"); return; }
    window._submitMissing(ids, workflowPath);
  };
  syncSel();
};

// 提交用户勾选的缺图提示词子集
window._submitMissing = async function(ids, workflowPath) {
  const btn = document.getElementById("genMissingBtn");
  const btnState = btn && window._runBtnState ? window._runBtnState(btn, "提交中...") : null;
  if (btnState) btnState.loading();
  try {
    const body = Object.assign({
      workflow_path: workflowPath,
      orientation: window.currentOrientation,
      quality: window.getQuality(),
      prompt_ids: ids,
    }, window.workflowExtraBody());
    const data = await window.api("/api/generate_missing", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), timeout: 300000,
    });
    if (!data.count) { window.showToast("没有缺图的提示词，全部已生成 ✅", "success"); return; }
    if (data.errors && data.errors.length) window.showToast(ids.length + " 条待补全，" + data.errors.length + " 个提交失败", "error");
    else window.showToast("已提交 " + ids.length + " 条缺图提示词", "success");
    window._showPendingProgress("补全缺图 (" + ids.length + " 条)");
    window.trackJob(data.job_id);
  } catch (e) {
    window.showToast("补全缺图失败: " + e.message, "error");
  } finally {
    if (btnState) btnState.restore();
  }
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
