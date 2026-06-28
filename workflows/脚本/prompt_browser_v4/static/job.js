// job.js - 任务追踪模块
// 依赖：utils.js

window.activeJobId = null;
window.jobPollTimer = null;
window.activeJobs = new Set();

// -------------------------------------------------------------------
// 任务追踪
// -------------------------------------------------------------------

window.trackJob = function(jobId) {
  window.activeJobId = jobId;
  window.activeJobs.add(jobId);
  if (window.jobPollTimer) clearInterval(window.jobPollTimer);
  window.jobPollTimer = setInterval(() => window.pollJob(jobId), 1000);
  window.pollJob(jobId);
  // 新任务开始时重置面板关闭状态，确保新任务能正常展示
  window.UiState.set("batchPanelDismissed", false);
};

window.loadActiveJobs = async function() {
  try {
    // 先查活跃任务
    let data = await window.api("/api/jobs?active=1");
    let jobs = data.jobs || [];

    // 如果没有活跃任务，查最近 5 条完成任务（页面刷新后任务可能已完成）
    if (jobs.length === 0) {
      data = await window.api("/api/jobs?limit=5");
      jobs = (data.jobs || []).filter(j => j.job_type === "batch" || j.items?.length > 1);
    }

    // 如果用户之前关闭了批量面板，不再重新展示已完成的任务
    if (window.UiState.get("batchPanelDismissed", false)) {
      jobs = jobs.filter(j => !["done", "error", "stopped"].includes(j.status));
    }

    jobs.forEach(job => {
      if (!window.activeJobs.has(job.id)) window.trackJob(job.id);
    });
  } catch (_) {}
};

window.pollJob = async function(jobId) {
  try {
    const job = await window.api(`/api/jobs/${jobId}`);
    if (job.job_type === "batch") window.renderBatchJob(job);
    else window.renderSingleJob(job);
    if (["done", "error", "stopped"].includes(job.status)) {
      clearInterval(window.jobPollTimer);
      window.jobPollTimer = null;
      window.activeJobs.delete(jobId);
      window.loadHistory(false);
    }
  } catch (e) {
    console.error("pollJob", e);
  }
};

// -------------------------------------------------------------------
// 单任务渲染
// -------------------------------------------------------------------

window.renderSingleJob = function(job) {
  const area = document.getElementById("outputArea");
  area.classList.add("show");
  const item = job.items[0] || {};
  const title = document.getElementById("outputTitle");
  const fill = document.getElementById("progressFill");
  const info = document.getElementById("progressInfo");
  const body = document.getElementById("outputBody");
  if (item.status === "pending") {
    fill.style.width = "0%";
    info.textContent = "排队中...";
    title.textContent = "生成中";
  } else if (item.status === "running") {
    const prog = item.progress || {};
    const pct = prog.max > 0 ? Math.round(prog.progress / prog.max * 100) : -1;
    fill.style.width = pct >= 0 ? pct + "%" : "30%";
    info.textContent = pct >= 0 ? `${pct}% ${prog.current_node || ""}`.trim() : "模型加载中...";
    title.textContent = pct >= 0 ? `生成中 ${pct}%` : "生成中";
  } else if (item.status === "done") {
    fill.style.width = "100%";
    info.textContent = "完成";
    title.textContent = "生成结果";
    body.innerHTML = "";
    if (item.images && item.images.length) {
      const grid = item.images.length > 1;
      body.className = grid ? "output-body img-grid" : "output-body";
      item.images.forEach(img => body.appendChild(window.createImageWrap(img)));
    } else {
      body.className = "output-body";
      body.innerHTML = '<div class="empty-tip">完成但未找到输出图片</div>';
    }
  } else if (item.status === "error" || item.status === "cancelled") {
    fill.style.width = "0%";
    info.textContent = item.status === "cancelled" ? "已取消" : "失败";
    title.textContent = item.status === "cancelled" ? "已取消" : "生成失败";
    body.className = "output-body";
    body.innerHTML = `<div class="empty-tip" style="color:var(--danger)">${window.escHtml(item.error || "失败")}</div>`;
  }
};

// -------------------------------------------------------------------
// 批量任务渲染
// -------------------------------------------------------------------

window.renderBatchJob = function(job) {
  const panel = document.getElementById("batchPanel");
  panel.classList.add("show");
  // 恢复折叠状态
  if (window.UiState.get("batchPanelCollapsed", false)) {
    panel.classList.add("collapsed");
    const t = document.getElementById("batchPanelToggle");
    if (t) t.textContent = "▶";
  }
  document.getElementById("batchPanelTitle").textContent = job.title || "批量任务";
  document.getElementById("batchPanelStop").style.display = ["pending", "running"].includes(job.status) ? "" : "none";
  const pct = job.total ? Math.round((job.done_count / job.total) * 100) : 0;
  document.getElementById("batchBarFill").style.width = pct + "%";
  document.getElementById("batchProgressText").textContent = `${job.done_count}/${job.total} (${job.error_count} 失败)`;
  const list = document.getElementById("batchItems");
  list.innerHTML = "";
  job.items.forEach((item, idx) => {
    const div = document.createElement("div");
    div.className = "batch-item";
    div.innerHTML = `<span class="batch-item-status ${item.status || "pending"}"></span>` +
      `<span class="batch-item-name">#${idx + 1} ${window.escHtml(item.prompt_preview || "提示词 " + item.prompt_id)}</span>` +
      `<span style="color:var(--muted)">${window.statusText(item.status)}</span>`;
    if (item.error) {
      div.innerHTML += `<span class="batch-item-error">${window.escHtml(item.error)}</span>`;
    }
    list.appendChild(div);
  });
  if (["done", "error", "stopped"].includes(job.status)) {
    window.showBatchResults(job);
  }
};

window.showBatchResults = function(job) {
  const area = document.getElementById("outputArea");
  area.classList.add("show");
  document.getElementById("outputTitle").textContent = job.title || "批量结果";
  document.getElementById("progressFill").style.width = "100%";
  document.getElementById("progressInfo").textContent = `${job.done_count} 完成 / ${job.error_count} 失败`;
  const body = document.getElementById("outputBody");
  body.innerHTML = "";
  let images = [];
  job.items.forEach(item => { if (item.images) images = images.concat(item.images); });
  if (!images.length) {
    body.className = "output-body";
    body.innerHTML = '<div class="empty-tip">无输出图片</div>';
    return;
  }
  const grid = images.length > 1;
  body.className = grid ? "output-body img-grid" : "output-body";
  images.forEach(img => body.appendChild(window.createImageWrap(img)));
};

// -------------------------------------------------------------------
// 图片包装
// -------------------------------------------------------------------

window.createImageWrap = function(img) {
  const wrap = document.createElement("div");
  const el = document.createElement("img");
  el.src = window.imageUrl(img);
  el.alt = img.filename;
  el.onclick = () => window.openLightbox(window.imageUrl(img));
  wrap.appendChild(el);
  const cap = document.createElement("div");
  cap.className = "img-caption";
  cap.textContent = img.filename;
  wrap.appendChild(cap);
  return wrap;
};

window.imageUrl = function(img) {
  return `/api/image?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || "")}&type=${encodeURIComponent(img.type || "output")}`;
};

window.statusText = function(status) {
  const map = { pending: "排队", running: "生成中", done: "完成", error: "失败", cancelled: "已取消", unknown: "未知" };
  return map[status] || status;
};

// -------------------------------------------------------------------
// 停止和关闭
// -------------------------------------------------------------------

// 批量面板折叠/展开
window.toggleBatchPanel = function() {
  const panel = document.getElementById("batchPanel");
  const toggle = document.getElementById("batchPanelToggle");
  if (!panel || !toggle) return;
  const collapsed = panel.classList.toggle("collapsed");
  toggle.textContent = collapsed ? "▶" : "▼";
  window.UiState.set("batchPanelCollapsed", collapsed);
};

window.closeOutput = function() {
  document.getElementById("outputArea").classList.remove("show");
  document.getElementById("batchPanel").classList.remove("show");
  if (window.jobPollTimer) { clearInterval(window.jobPollTimer); window.jobPollTimer = null; }
  window.activeJobId = null;
  window.UiState.set("batchPanelDismissed", true);
};

window.batchStop = async function() {
  return window.withLock("batchStop", async () => {
    if (!window.activeJobId) return;
    try {
      await window.api(`/api/jobs/${window.activeJobId}/cancel`, { method: "POST" });
      window.showToast("已停止", "info");
      window.pollJob(window.activeJobId);
    } catch (e) {
      window.showToast("停止失败: " + e.message, "error");
    }
  });
};
