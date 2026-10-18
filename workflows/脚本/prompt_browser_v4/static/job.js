// job.js - 任务追踪模块
// 依赖：utils.js

window.activeJobId = null;
window.jobPollTimer = null;
window.activeJobs = new Set();
window._trialWatchers = new Map();  // trial run callbacks: jobId → callback(job)

// -------------------------------------------------------------------
// 任务跟踪：优先 SSE，不可用时自动降级为 1s 轮询
// -------------------------------------------------------------------
// 关闭方式：localStorage.pbSse = "0"，或 URL 加 ?sse=0
window.PB_SSE = localStorage.getItem("pbSse") !== "0";
window._jobSource = null;
window._sseReady = false;
window._sseDisabled = false;
window._sseRestartTimer = null;
window._sseFallbackTimer = null;

window.trackJob = function(jobId) {
  window.activeJobId = jobId;
  window.activeJobs.add(jobId);
  // 新任务开始时重置面板关闭状态，确保新任务能正常展示
  window.UiState.set("batchPanelDismissed", false);
  window._ensureJobTracking();
};

window._ensureJobTracking = function() {
  if (window._sseDisabled || !window.PB_SSE || typeof EventSource === "undefined") {
    if (window.activeJobId) window._startPolling(window.activeJobId);
    return;
  }
  // 多个任务在短时间内连续注册时，只重连一次
  clearTimeout(window._sseRestartTimer);
  window._sseRestartTimer = setTimeout(window._connectJobEvents, 120);
};

window._connectJobEvents = function() {
  if (!window.activeJobs.size) return;
  if (window._jobSource) {
    try { window._jobSource.close(); } catch (_) {}
    window._jobSource = null;
  }
  const ids = Array.from(window.activeJobs);
  const es = new EventSource("/api/jobs/events?ids=" + ids.join(","));
  window._jobSource = es;
  window._sseReady = false;

  const onEvent = (ev) => {
    window._sseReady = true;
    let job;
    try { job = JSON.parse(ev.data); } catch (_) { return; }
    window._onJobEvent(job);
  };
  es.addEventListener("snapshot", onEvent);
  es.addEventListener("job", onEvent);
  es.onerror = () => {
    // EventSource 自带重连；真正的降级交给下面的 3 秒看门狗
  };

  clearTimeout(window._sseFallbackTimer);
  window._sseFallbackTimer = setTimeout(() => {
    if (window._sseReady) return;
    console.warn("[SSE] 3 秒内未收到事件，降级为轮询");
    window._sseDisabled = true;   // 本会话不再尝试 SSE
    try { es.close(); } catch (_) {}
    window._jobSource = null;
    if (window.activeJobId) window._startPolling(window.activeJobId);
  }, 3000);
};

window._stopJobEvents = function() {
  if (window._jobSource) {
    try { window._jobSource.close(); } catch (_) {}
    window._jobSource = null;
  }
  clearTimeout(window._sseFallbackTimer);
  window._sseReady = false;
};

window._startPolling = function(jobId) {
  if (!jobId) return;
  if (window.jobPollTimer) clearInterval(window.jobPollTimer);
  window.jobPollTimer = setInterval(() => window.pollJob(jobId), 1000);
  window.pollJob(jobId);
};

window._isTerminalJob = function(job) {
  return ["done", "error", "stopped", "cancelled"].includes(job.status);
};

/**
 * 统一提交入口：离线拦截 → 占位进度 → 提交 → trackJob。
 * 各页面只负责构造 payload 与自己的成功提示，不再各自拼 "POST + trackJob"。
 * 返回后端响应；被离线拦截时返回 null。
 */
window.submitTask = async function(opts) {
  const {
    endpoint, payload, title = "提交任务",
    errorPrefix = "提交失败", requireOnline = true, timeout,
  } = opts || {};
  if (requireOnline && window.comfyStatus !== "online") {
    window.showToast("ComfyUI 未连接，已取消提交", "error");
    return null;
  }
  if (typeof window._showPendingProgress === "function") {
    window._showPendingProgress(title);
  }
  try {
    const data = await window.api(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
      ...(timeout ? { timeout } : {}),
    });
    if (data && data.job_id) window.trackJob(data.job_id);
    else window.hideJobHud();
    return data;
  } catch (e) {
    window.hideJobHud();
    window.showToast(errorPrefix + ": " + e.message, "error");
    throw e;
  }
};

/** 收起任务 HUD（提交失败或没有产生任务时用，避免一直停在"排队中"） */
window.hideJobHud = function() {
  const hud = document.getElementById("jobHud");
  if (hud) hud.classList.remove("show");
};

window._onJobEvent = function(job) {
  if (!job || !job.id) return;
  if (window._isTerminalJob(job) && !window.activeJobs.has(job.id)) return;
  if (typeof window.updateJobHud === "function") window.updateJobHud(job);
  if (job.job_type === "batch") window.renderBatchJob(job);
  else window.renderSingleJob(job);
  if (window._isTerminalJob(job)) window._finalizeJob(job);
};

window.loadActiveJobs = async function() {
  try {
    // 先查活跃任务
    let data = await window.api("/api/jobs?active=1");
    let jobs = data.jobs || [];

    // 如果没有活跃任务，查最近 5 条任务（页面刷新后任务可能仍在运行）
    if (jobs.length === 0) {
      data = await window.api("/api/jobs?limit=5");
      // 仅追踪仍处于 pending/running 状态的任务，避免把旧任务的错误/空结果展示到界面
      jobs = (data.jobs || []).filter(j =>
        (j.job_type === "batch" || j.items?.length > 1) &&
        ["pending", "running"].includes(j.status)
      );
    }

    // 如果用户之前关闭了批量面板，不再重新展示已完成的任务
    if (window.UiState.get("batchPanelDismissed", false)) {
      jobs = jobs.filter(j => !["done", "error", "stopped"].includes(j.status));
    }

    if (jobs.length) {
      jobs.forEach(job => window.activeJobs.add(job.id));
      window.activeJobId = jobs[jobs.length - 1].id;
      window._ensureJobTracking();
    }
  } catch (_) {}
};

window.pollJob = async function(jobId) {
  try {
    const job = await window.api(`/api/jobs/${jobId}`);
    // 任意 Tab 都能看到的常驻进度（B4 会用任务抽屉替换它）
    if (typeof window.updateJobHud === "function") window.updateJobHud(job);
    if (job.job_type === "batch") window.renderBatchJob(job);
    else window.renderSingleJob(job);
    if (window._isTerminalJob(job)) window._finalizeJob(job);
  } catch (e) {
    // 超时是预期行为（后端正在处理），不打印错误
    if (e.message && e.message.includes("请求超时")) return;
    console.error("pollJob", e);
  }
};

// 终态处理：SSE 与轮询共用，确保两条路径行为完全一致
window._finalizeJob = function(job) {
  const jobId = job.id;
  if (window.activeJobs.has(jobId)) window.activeJobs.delete(jobId);
  if (window.activeJobId === jobId) window.activeJobId = null;
  if (window.jobPollTimer) {
    clearInterval(window.jobPollTimer);
    window.jobPollTimer = null;
  }
  if (window.activeJobs.size === 0) window._stopJobEvents();

  // 恢复跑图按钮
  if (typeof window.updateRunBtn === "function") window.updateRunBtn();
  if (typeof window.loadHistory === "function") {
    window.loadHistory(false);
  }
  // 完成反馈：给出"查看"入口，而不是 3.5 秒后无痕消失
  const newImages = (job.items || []).reduce(
    (n, it) => n + (Array.isArray(it.images) ? it.images.length : 0), 0
  );
  if (job.status === "done" && newImages > 0) {
    window.showToast(
      `完成：新增 ${newImages} 张图片`, "success", "查看",
      () => window.switchTabByRoute && window.switchTabByRoute("galleryTab")
    );
  }
  // 防抖刷新当前选中提示词的生成历史
  clearTimeout(window._refreshHistoryTimer);
  window._refreshHistoryTimer = setTimeout(() => {
    if (typeof window.selectedId === "number" && window.selectedId > 0
        && typeof window.loadPromptHistory === "function") {
      window.loadPromptHistory(window.selectedId);
    }
  }, 300);
  // 试跑任务完成回调：通知编辑弹窗更新试跑记录
  if (window._trialWatchers && window._trialWatchers.has(jobId)) {
    const cb = window._trialWatchers.get(jobId);
    try { cb(job); } catch (_) {}
    window._trialWatchers.delete(jobId);
  }
  // 还有别的任务在跑：继续订阅
  if (window.activeJobs.size > 0) window._ensureJobTracking();
};

// -------------------------------------------------------------------
// 全局任务 HUD —— 组合/批量提交后，无论当前在哪个 Tab 都能看到进度
// -------------------------------------------------------------------
window._ensureJobHud = function() {
  let hud = document.getElementById("jobHud");
  if (hud) return hud;
  hud = document.createElement("div");
  hud.id = "jobHud";
  hud.className = "job-hud";
  hud.innerHTML =
    '<div class="job-hud-head">' +
      '<span class="job-hud-title" id="jobHudTitle">生成中</span>' +
      '<button class="job-hud-close" id="jobHudClose" title="收起（任务继续在后台跑）">×</button>' +
    '</div>' +
    '<div class="job-hud-bar"><div class="job-hud-fill" id="jobHudFill"></div></div>' +
    '<div class="job-hud-info"><span id="jobHudInfo">排队中…</span>' +
      '<button class="btn btn-xs btn-danger-ghost" id="jobHudStop">停止</button></div>';
  document.body.appendChild(hud);
  hud.querySelector("#jobHudClose").onclick = () => {
    hud.classList.remove("show");
    // 记住"这一单被用户收起了"，否则 1 秒后的下一次轮询又把它弹出来
    window._jobHudDismissedFor = window._jobHudCurrentId || null;
  };
  hud.querySelector("#jobHudStop").onclick = () => window.batchStop();
  return hud;
};

window.updateJobHud = function(job) {
  const hud = window._ensureJobHud();
  if (job.id) window._jobHudCurrentId = job.id;
  if (job.id && window._jobHudDismissedFor === job.id) return;

  const total = job.total || 0;
  const pct = total ? Math.round((job.done_count || 0) / total * 100) : (job.status === "running" ? 30 : 0);
  hud.querySelector("#jobHudTitle").textContent = job.title || "生成中";
  hud.querySelector("#jobHudFill").style.width = pct + "%";
  const info = total
    ? `${job.done_count || 0}/${total}（${job.error_count || 0} 失败）`
    : (job.status === "running" ? "生成中…" : "排队中…");
  hud.querySelector("#jobHudInfo").textContent = info;
  const active = ["pending", "running"].includes(job.status);
  hud.querySelector("#jobHudStop").style.display = active ? "" : "none";
  hud.classList.add("show");
  if (!active) {
    clearTimeout(window._jobHudHide);
    window._jobHudHide = setTimeout(() => hud.classList.remove("show"), 6000);
  }
};

// -------------------------------------------------------------------
// 单任务渲染
// -------------------------------------------------------------------

window.renderSingleJob = function(job) {
  const area = document.getElementById("outputArea");
  area.classList.add("show");
  const item = job.items && job.items.length > 0 ? job.items[0] : null;
  const title = document.getElementById("outputTitle");
  const fill = document.getElementById("progressFill");
  const info = document.getElementById("progressInfo");
  const body = document.getElementById("outputBody");

  if (!item) {
    // items 为空时显示占位信息
    console.warn("[renderSingleJob] job has empty items, job:", job);
    fill.style.width = "0%";
    info.textContent = "等待中...";
    title.textContent = "任务 #" + (job.id || "?");
    return;
  }

  if (item.status === "pending") {
    fill.style.width = "0%";
    fill.style.background = "";
    info.textContent = "排队中...";
    title.textContent = "生成中";
  } else if (item.status === "running") {
    fill.style.background = "";
    const prog = item.progress || {};
    const pct = prog.max > 0 ? Math.round(prog.progress / prog.max * 100) : -1;
    fill.style.width = pct >= 0 ? pct + "%" : "30%";
    info.textContent = pct >= 0 ? `${pct}% ${prog.current_node || ""}`.trim() : "处理中...";
    title.textContent = pct >= 0 ? `生成中 ${pct}%` : "生成中";
  } else if (item.status === "done") {
    fill.style.width = "100%";
    fill.style.background = "";
    body.className = "output-body";
    const count = Array.isArray(item.images) ? item.images.length : 0;
    title.textContent = count > 1 ? `完成 · ${count} 张` : "生成完成";
    info.textContent = "✓ 已刷新到生成历史";
    body.innerHTML = "";  // 不展示大图，缩略图在生成历史区域
    // 3 秒后自动收起
    setTimeout(() => {
      const area = document.getElementById("outputArea");
      if (area && !window._outputPinned) area.classList.remove("show");
    }, 3000);
  } else if (item.status === "error" || item.status === "cancelled") {
    fill.style.width = "100%";
    fill.style.background = "var(--danger)";
    title.textContent = item.status === "cancelled" ? "已取消" : "生成失败";
    info.innerHTML = `<span style="color:var(--danger)">${window.escHtml(item.error || "失败")}</span>`;
  } else {
    // 未知状态
    console.warn("[renderSingleJob] unknown item status:", item.status, item);
    title.textContent = "生成中...";
    info.textContent = "状态: " + (item.status || "未知");
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
  document.getElementById("outputTitle").textContent = `批量完成 · ${job.done_count}/${job.total}`;
  document.getElementById("progressFill").style.width = "100%";
  document.getElementById("progressInfo").textContent = `${job.error_count} 失败`;
  document.getElementById("outputBody").className = "output-body";
  document.getElementById("outputBody").innerHTML = "";
};

// -------------------------------------------------------------------
// 图片包装
// -------------------------------------------------------------------

window.createImageWrap = function(img) {
  const wrap = document.createElement("div");
  wrap.style.position = "relative";

  const placeholder = document.createElement("div");
  placeholder.style.cssText = "width:120px;height:120px;background:#2a2a2a;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#666;font-size:12px";
  placeholder.textContent = "图片已删除";
  placeholder.style.display = "none";

  const el = document.createElement("img");
  const url = window.imageUrl(img);
  el.src = url;
  el.alt = img.filename;
  el.style.display = "none";
  el.onclick = () => window.openLightbox(url);

  el.onerror = () => {
    el.style.display = "none";
    placeholder.style.display = "flex";
  };

  el.onload = () => {
    el.style.display = "";
    placeholder.style.display = "none";
  };

  wrap.appendChild(placeholder);
  wrap.appendChild(el);

  const cap = document.createElement("div");
  cap.className = "img-caption";
  cap.textContent = img.filename;
  wrap.appendChild(cap);
  return wrap;
};

window.imageUrl = function(img) {
  // 尝试走静态文件直读；若后端发现文件不存在会返回优雅的占位图
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
  const hud = document.getElementById("jobHud");
  if (hud) hud.classList.remove("show");
  // 只隐藏界面，不动 jobPollTimer / activeJobs：
  // 旧代码在这里清掉轮询，任务就再也收不到终态，activeJobs 永远非空，
  // 头部"跑图"按钮从此一直显示"⏳ 生成中..."并禁用（任务其实早已结束）。
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
