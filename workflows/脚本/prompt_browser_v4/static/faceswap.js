// faceswap.js - 批量换脸工作台
// 依赖：utils.js（api/showToast/withLock/escHtml/UiState）、workflow.js（当前工作流）、history.js（loadHistory）、job.js（statusText）
//
// 左右两栏各自可以切「🖼️ 画廊」和「📁 文件夹」两种来源，且两栏互相独立：
//   画廊   —— 项目已有的历史图池（分页 + 搜索）
//   文件夹 —— 打开磁盘上任意文件夹选图（↑ 上一级 / 路径栏 / 快速跳转 / 子目录）
// 选中项用 key 记录（画廊 h:<id>，文件夹 f:<路径>），切模式不会丢选择，
// 提交时自动拆成 main_ids/main_paths 与 ref_ids/ref_paths 送给后端。

(function () {
  const PAGE_SIZES = [30, 60, 120];
  const ROLES = ["main", "ref"];
  const $ = (id) => document.getElementById(id);

  window._fsItems = window._fsItems || new Map();                 // historyId -> item
  window._fsSel = window._fsSel || { main: new Map(), ref: new Map() };  // key -> entry
  window._fsDir = window._fsDir || { main: null, ref: null };     // 文件夹模式当前目录
  window._fsMode = window._fsMode || { main: "gallery", ref: "gallery" };
  window._fsPageItems = window._fsPageItems || [];
  window._fsPage = 1;
  window._fsPageSize = 60;
  window._fsTotal = 0;
  window._fsInited = false;
  window._fsJobId = null;
  window._fsTimer = null;
  window._fsPanelCollapsed = window._fsPanelCollapsed || false;
  window._fsPromptExpanded = false;

  const stem = (name) => String(name || "").replace(/\.[^.]+$/, "");
  const enc = encodeURIComponent;

  // ------------------------------------------------------------------ 条目构造
  function entryFromHistory(it) {
    const sub = it.subfolder || "";
    const type = it.img_type || "output";
    const v = it.created_at || it.id || "";
    return {
      key: "h:" + it.id,
      kind: "history",
      id: it.id,
      label: stem(it.filename),
      filename: it.filename,
      image: `/api/image?filename=${enc(it.filename || "")}&subfolder=${enc(sub)}&type=${enc(type)}`,
      thumb: `/api/thumbnail?filename=${enc(it.filename || "")}&subfolder=${enc(sub)}&type=${enc(type)}&size=300&v=${enc(v)}`,
      title: (it.filename || "") + (it.prompt_name ? `\n📝 ${it.prompt_name}` : ""),
    };
  }

  function entryFromFile(f) {
    return {
      key: "f:" + String(f.path).toLowerCase(),
      kind: "file",
      path: f.path,
      label: stem(f.name),
      filename: f.name,
      image: `/api/fs/image?path=${enc(f.path)}`,
      thumb: `/api/fs/thumb?path=${enc(f.path)}&size=300`,
      title: f.path,
    };
  }

  window.fsCurrentEntries = function (role) {
    if (window._fsMode[role] === "folder") {
      const d = window._fsDir[role];
      return d ? (d.images || []).map(entryFromFile) : [];
    }
    return window._fsPageItems.map(entryFromHistory);
  };

  // ------------------------------------------------------------------ 初始化
  window.initFaceswap = function (force) {
    if (window._fsInited && !force) {
      window.fsUpdateCounts();
      window.fsRefreshWfName();
      return;
    }
    window._fsInited = true;
    ROLES.forEach((r) => {
      const saved = window.UiState.get("fsMode_" + r, "gallery");
      window._fsMode[r] = saved === "folder" ? "folder" : "gallery";
      applyModeUI(r);
      if (window._fsMode[r] === "folder" && !window._fsDir[r]) {
        window.fsDirOpen(r, window.UiState.get("fsDir_" + r, ""));
      }
    });
    // 恢复上次的折叠状态（每个折叠区都记住）
    window._fsColCollapsed = {
      main: !!window.UiState.get("fsCol_main", false),
      ref: !!window.UiState.get("fsCol_ref", false),
    };
    window._fsFooterCollapsed = !!window.UiState.get("fsFooterCollapsed", false);
    window._fsPanelCollapsed = !!window.UiState.get("fsPanelCollapsed", false);
    window.fsApplyLayout();

    // 提示词框：实时更新折叠摘要；Ctrl+Enter 放大/收起
    const ta = $("fsPrompt");
    if (ta) {
      ta.addEventListener("input", window.fsUpdateFooterSummary);
      ta.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          window.fsTogglePromptExpand();
        }
      });
    }
    if ($("fsSeed")) $("fsSeed").addEventListener("input", window.fsUpdateFooterSummary);
    if ($("fsSeedMode")) $("fsSeedMode").addEventListener("change", window.fsUpdateFooterSummary);

    window.fsSyncLayout();
    window.fsPopulatePageSize();
    window.fsRefreshWfName();
    window.fsLoadFilterOptions();
    window.fsLoadPage(1);
    window.fsDetectNodes(false);
    window.fsResumeActive();
  };

  // 分类/标签筛选下拉：复用同一套 taxonomy（图片口径）
  window.fsLoadFilterOptions = async function () {
    if (window._fsFiltersLoaded) return;
    try {
      const [catData, tagData] = await Promise.all([
        window.api("/api/categories?tree=true&count_scope=image"),
        window.api("/api/tags?count_scope=image"),
      ]);
      const catSel = $("fsCategory");
      if (catSel) {
        const opts = [];
        const walk = (nodes, depth) => (nodes || []).forEach((n) => {
          opts.push(
            `<option value="${n.id}">${"　".repeat(depth)}${window.escHtml(n.name)}</option>`
          );
          if (n.children && n.children.length) walk(n.children, depth + 1);
        });
        walk(catData.categories || [], 0);
        catSel.innerHTML = '<option value="">全部分类</option>' + opts.join("");
      }
      const tagSel = $("fsTag");
      if (tagSel) {
        const opts = (tagData.tags || []).map((t) =>
          `<option value="${t.id}">${window.escHtml(t.name)}</option>`);
        tagSel.innerHTML = '<option value="">全部标签</option>' + opts.join("");
      }
      window._fsFiltersLoaded = true;
    } catch (e) {
      console.warn("[faceswap] 加载筛选选项失败", e);
    }
  };

  window.routeFaceswap = function () {
    window.initFaceswap();
  };

  window.fsRefreshWfName = function () {
    const src = $("wfLabel");
    const node = $("fsWfName");
    if (node && src) node.textContent = src.textContent || "未选择";
  };

  // ------------------------------------------------------------------ 模式切换
  function applyModeUI(role) {
    const box = $(role === "main" ? "fsMainMode" : "fsRefMode");
    if (!box) return;
    const isGallery = window._fsMode[role] === "gallery";
    const btns = box.querySelectorAll(".fs-mode-btn");
    if (btns[0]) btns[0].classList.toggle("active", isGallery);
    if (btns[1]) btns[1].classList.toggle("active", !isGallery);
  }

  window.fsSyncLayout = function () {
    const anyGallery = ROLES.some((r) => window._fsMode[r] === "gallery");
    if ($("fsGalleryBar")) $("fsGalleryBar").style.display = anyGallery ? "" : "none";
    if ($("fsPager")) $("fsPager").style.display = anyGallery ? "" : "none";
  };

  window.fsSetMode = function (role, mode) {
    if (window._fsMode[role] === mode) return;
    window._fsMode[role] = mode;
    window.UiState.set("fsMode_" + role, mode);
    applyModeUI(role);
    window.fsSyncLayout();
    if (mode === "folder" && !window._fsDir[role]) {
      window.fsDirOpen(role, window.UiState.get("fsDir_" + role, ""));
      return;
    }
    window.fsRenderColumn(role);
  };

  // ------------------------------------------------------------------ 文件夹浏览
  window.fsDirOpen = async function (role, path) {
    const p = path === undefined || path === null ? "" : String(path).trim();
    window._fsMode[role] = "folder";
    window.UiState.set("fsMode_" + role, "folder");
    applyModeUI(role);
    window.fsSyncLayout();
    const grid = $(role === "main" ? "fsMainGrid" : "fsRefGrid");
    if (grid) grid.innerHTML = '<div class="fs-empty">读取中…</div>';
    try {
      const d = await window.api("/api/fs/list?path=" + enc(p));
      window._fsDir[role] = d;
      if (d.path) window.UiState.set("fsDir_" + role, d.path);
      fillRoots($(role === "main" ? "fsMainRoots" : "fsRefRoots"), d.roots || []);
      window.fsRenderColumn(role);
      if (d.truncated) window.showToast("该目录内容过多，只显示前 800 项", "info");
    } catch (e) {
      window._fsDir[role] = null;
      window.fsRenderColumn(role);
      window.showToast("打开文件夹失败：" + e.message, "error");
    }
  };

  window.fsDirUp = function (role) {
    const d = window._fsDir[role];
    if (d && d.parent) window.fsDirOpen(role, d.parent);
    else window.fsDirOpen(role, "");   // 已经在盘符层 → 重新列出盘符
  };

  window.fsDirRefresh = function (role) {
    const d = window._fsDir[role];
    window.fsDirOpen(role, d ? d.path : "");
  };

  function fillRoots(select, roots) {
    if (!select || select.dataset.filled === "1") return;
    select.dataset.filled = "1";
    roots.forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r.path;
      opt.textContent = r.name;
      select.appendChild(opt);
    });
  }

  // ------------------------------------------------------------------ 渲染
  window.fsRenderColumn = function (role) {
    const gridId = role === "main" ? "fsMainGrid" : "fsRefGrid";
    const barId = role === "main" ? "fsMainDirBar" : "fsRefDirBar";
    const dirsId = role === "main" ? "fsMainDirs" : "fsRefDirs";
    const pathId = role === "main" ? "fsMainPath" : "fsRefPath";
    const grid = $(gridId);
    const folder = window._fsMode[role] === "folder";

    if ($(barId)) $(barId).style.display = folder ? "" : "none";
    if (folder) {
      const d = window._fsDir[role];
      if ($(pathId)) $(pathId).value = d ? (d.path || "") : "";
      renderDirs($(dirsId), role, d);
    } else if ($(dirsId)) {
      $(dirsId).innerHTML = "";
    }

    if (!grid) return;
    const entries = window.fsCurrentEntries(role);
    grid.innerHTML = "";
    if (!entries.length) {
      const tip = document.createElement("div");
      tip.className = "fs-empty";
      tip.textContent = folder
        ? (window._fsDir[role] ? "这个文件夹里没有图片" : "还没打开文件夹：用上面的路径栏或「快速跳转」选一个")
        : "没有图片（换个搜索词，或去画廊同步一次）";
      grid.appendChild(tip);
      window.fsRefreshSelectionUI(role);
      return;
    }
    entries.forEach((e) => grid.appendChild(makeTile(e, role, folder)));
    window.fsRefreshSelectionUI(role);
  };

  function renderDirs(box, role, d) {
    if (!box) return;
    box.innerHTML = "";
    if (!d || !(d.dirs || []).length) return;
    (d.dirs || []).forEach((dir) => {
      const chip = document.createElement("button");
      chip.className = "fs-dir-chip";
      chip.textContent = "📁 " + dir.name;
      chip.title = dir.path;
      chip.onclick = () => window.fsDirOpen(role, dir.path);
      box.appendChild(chip);
    });
  }

  function makeTile(e, role, folder) {
    const div = document.createElement("div");
    div.className = "fs-item";
    div.dataset.key = e.key;
    div.title = e.title;

    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = e.thumb;
    img.alt = "";
    img.onerror = () => {
      div.innerHTML = "";
      const fail = document.createElement("div");
      fail.className = "fs-item-fail";
      fail.textContent = "读不到图";
      div.appendChild(fail);
    };
    div.appendChild(img);

    const badge = document.createElement("span");
    badge.className = "fs-item-sel";
    div.appendChild(badge);

    const zoom = document.createElement("button");
    zoom.className = "fs-item-zoom";
    zoom.textContent = "🔍";
    zoom.title = "新窗口看原图";
    zoom.onclick = (ev) => {
      ev.stopPropagation();
      window.open(e.image, "_blank");
    };
    div.appendChild(zoom);

    if (folder) {
      const cap = document.createElement("div");
      cap.className = "fs-item-cap";
      cap.textContent = e.label;
      div.appendChild(cap);
    }

    div.onclick = () => window.fsToggle(e, role);
    return div;
  }

  // 只更新选中样式与序号，不重建 DOM（否则每次点击都要重新拉一遍缩略图）
  window.fsRefreshSelectionUI = function (role) {
    const grid = $(role === "main" ? "fsMainGrid" : "fsRefGrid");
    const sel = window._fsSel[role];
    const order = new Map();
    let n = 0;
    for (const key of sel.keys()) order.set(key, ++n);
    if (grid) {
      grid.querySelectorAll(".fs-item").forEach((node) => {
        const key = node.dataset.key;
        const on = sel.has(key);
        node.classList.toggle("sel", on);
        const badge = node.querySelector(".fs-item-sel");
        if (badge) badge.textContent = on ? String(order.get(key) || "") : "";
      });
    }
    window.fsUpdateCounts();
  };

  window.fsToggle = function (entry, role) {
    const sel = window._fsSel[role];
    if (sel.has(entry.key)) sel.delete(entry.key);
    else sel.set(entry.key, entry);
    window.fsRefreshSelectionUI(role);
  };

  window.fsSelectPage = function (role) {
    const sel = window._fsSel[role];
    window.fsCurrentEntries(role).forEach((e) => sel.set(e.key, e));
    window.fsRefreshSelectionUI(role);
  };

  window.fsClearSel = function (role) {
    if (role) window._fsSel[role].clear();
    else ROLES.forEach((r) => window._fsSel[r].clear());
    ROLES.forEach((r) => window.fsRefreshSelectionUI(r));
  };

  window.fsUpdateCounts = function () {
    const m = window._fsSel.main.size;
    const r = window._fsSel.ref.size;
    const zip = ($("fsPairMode")?.value || "cross") === "zip";
    if ($("fsMainCount")) $("fsMainCount").textContent = m;
    if ($("fsRefCount")) $("fsRefCount").textContent = r;
    if ($("fsMainStripCount")) $("fsMainStripCount").textContent = m;
    if ($("fsRefStripCount")) $("fsRefStripCount").textContent = r;
    const box = $("fsComboCount");
    if (box) {
      if (zip && m && r && m !== r) {
        box.textContent = "数量不一致";
        box.style.color = "var(--danger)";
      } else {
        box.textContent = zip ? Math.min(m, r) : m * r;
        box.style.color = "";
      }
    }
    window.fsUpdateFooterSummary();
  };

  // ------------------------------------------------------------------ 布局：折叠 / 展开 / 预设
  window._fsColCollapsed = window._fsColCollapsed || { main: false, ref: false };
  window._fsFooterCollapsed = false;

  window.fsApplyLayout = function () {
    const c = window._fsColCollapsed;
    const cols = $("fsColumns");
    if (cols) {
      cols.className = "fs-columns" + (
        c.main && c.ref ? " col-both-collapsed"
          : c.main ? " col-main-collapsed"
            : c.ref ? " col-ref-collapsed" : "");
    }
    if ($("fsMainCol")) $("fsMainCol").classList.toggle("collapsed", !!c.main);
    if ($("fsRefCol")) $("fsRefCol").classList.toggle("collapsed", !!c.ref);
    if ($("fsFooter")) $("fsFooter").classList.toggle("collapsed", !!window._fsFooterCollapsed);
    if ($("fsFooterToggle")) $("fsFooterToggle").textContent = window._fsFooterCollapsed ? "▸" : "▾";
    if ($("fsPanel")) $("fsPanel").classList.toggle("collapsed", !!window._fsPanelCollapsed);
    if ($("fsPanelToggle")) $("fsPanelToggle").textContent = window._fsPanelCollapsed ? "▶" : "▼";
    window.fsUpdateCounts();
  };

  window.fsToggleCol = function (role) {
    window._fsColCollapsed[role] = !window._fsColCollapsed[role];
    window.UiState.set("fsCol_" + role, window._fsColCollapsed[role]);
    window.fsApplyLayout();
  };

  window.fsToggleFooter = function () {
    window._fsFooterCollapsed = !window._fsFooterCollapsed;
    window.UiState.set("fsFooterCollapsed", window._fsFooterCollapsed);
    window.fsApplyLayout();
  };

  window.fsTogglePanelCollapse = function () {
    window._fsPanelCollapsed = !window._fsPanelCollapsed;
    window.UiState.set("fsPanelCollapsed", window._fsPanelCollapsed);
    window.fsApplyLayout();
  };

  function setLayout(colMain, colRef, footerCollapsed) {
    window._fsColCollapsed.main = colMain;
    window._fsColCollapsed.ref = colRef;
    window._fsFooterCollapsed = footerCollapsed;
    window.UiState.set("fsCol_main", colMain);
    window.UiState.set("fsCol_ref", colRef);
    window.UiState.set("fsFooterCollapsed", footerCollapsed);
    window.fsApplyLayout();
  }

  window.fsFocusPicking = function () {
    // 一键把空间全给选图：收起参数区、展开两栏
    setLayout(false, false, true);
    window.showToast("已收起参数区，空间全给选图", "info");
  };

  window.fsExpandAll = function () {
    setLayout(false, false, false);
    window.fsTogglePromptExpand(false);
  };

  window.fsUpdateFooterSummary = function () {
    const box = $("fsFooterSummary");
    if (!box) return;
    const pair = $("fsPairMode")?.value === "zip" ? "1:1 配对" : "全组合";
    const sm = $("fsSeedMode")?.value || "fixed";
    const seedTxt = sm === "random"
      ? "随机种子"
      : `${sm === "increment" ? "递增" : "固定"} ${$("fsSeed")?.value || ""}`;
    const p = ($("fsPrompt")?.value || "").trim();
    box.textContent = `${pair} · ${seedTxt} · 提示词${p ? ` ${p.length} 字` : "用内置默认"}`;
  };

  // ------------------------------------------------------------------ 提示词放大编辑
  // 直接给同一个 textarea 换全屏样式，不做内容同步
  window.fsTogglePromptExpand = function (force) {
    const box = $("fsPromptBox");
    if (!box) return;
    const on = typeof force === "boolean" ? force : !window._fsPromptExpanded;
    window._fsPromptExpanded = on;
    box.classList.toggle("expanded", on);
    if ($("fsPromptBackdrop")) $("fsPromptBackdrop").classList.toggle("show", on);
    if ($("fsPromptExpandBtn")) $("fsPromptExpandBtn").textContent = on ? "▾ 收起" : "⤢ 放大编辑";
    if (on) setTimeout(() => $("fsPrompt")?.focus(), 30);
  };

  window.fsClearPrompt = function () {
    const t = $("fsPrompt");
    if (!t) return;
    if (t.value.trim() && !confirm("清空提示词？清空后将使用内置的换脸描述。")) return;
    t.value = "";
    window.fsUpdateFooterSummary();
  };

  // ------------------------------------------------------------------ 画廊分页
  window.fsPopulatePageSize = function () {
    const sel = $("fsPageSize");
    if (!sel) return;
    sel.innerHTML = PAGE_SIZES.map((n) =>
      `<option value="${n}" ${n === window._fsPageSize ? "selected" : ""}>${n}</option>`).join("");
    sel.onchange = function () {
      window._fsPageSize = parseInt(this.value, 10) || 60;
      window.fsLoadPage(1);
    };
  };

  window.fsLoadPage = async function (page) {
    const p = Math.max(1, parseInt(page, 10) || 1);
    const kw = ($("fsSearch")?.value || "").trim();
    const cat = $("fsCategory")?.value || "";
    const tag = $("fsTag")?.value || "";
    const loading = '<div class="fs-empty">加载中…</div>';
    if (window._fsMode.main === "gallery" && $("fsMainGrid")) $("fsMainGrid").innerHTML = loading;
    if (window._fsMode.ref === "gallery" && $("fsRefGrid")) $("fsRefGrid").innerHTML = loading;
    try {
      // 画廊模式支持按分类/标签筛选（后端 /api/history 早已支持，之前只传了搜索词）
      const qs = new URLSearchParams({
        page: String(p),
        page_size: String(window._fsPageSize),
        search: kw,
      });
      if (cat) qs.set("category_id", cat);
      if (tag) qs.set("tag_ids", tag);
      const data = await window.api(`/api/history?${qs.toString()}`);
      window._fsPage = data.page || p;
      window._fsTotal = data.total || 0;
      window._fsPageItems = data.items || [];
      window._fsPageItems.forEach((it) => window._fsItems.set(it.id, it));
      ROLES.forEach((r) => {
        if (window._fsMode[r] === "gallery") window.fsRenderColumn(r);
      });
      window.fsRenderPager();
    } catch (e) {
      const msg = `<div class="fs-empty">加载失败：${window.escHtml(e.message)}</div>`;
      if (window._fsMode.main === "gallery" && $("fsMainGrid")) $("fsMainGrid").innerHTML = msg;
      if (window._fsMode.ref === "gallery" && $("fsRefGrid")) $("fsRefGrid").innerHTML = msg;
    }
  };

  window.fsRenderPager = function () {
    const box = $("fsPager");
    if (!box) return;
    const totalPages = Math.max(1, Math.ceil(window._fsTotal / window._fsPageSize));
    const p = window._fsPage;
    box.innerHTML =
      `<span>第 ${p} / ${totalPages} 页，共 ${window._fsTotal} 张</span>` +
      `<button class="btn btn-sm btn-ghost" ${p <= 1 ? "disabled" : ""} onclick="window.fsLoadPage(${p - 1})">‹ 上一页</button>` +
      `<button class="btn btn-sm btn-ghost" ${p >= totalPages ? "disabled" : ""} onclick="window.fsLoadPage(${p + 1})">下一页 ›</button>` +
      `<span>每页 <select id="fsPageSize"></select></span>`;
    window.fsPopulatePageSize();
  };

  // ------------------------------------------------------------------ 节点映射探测
  window.fsDetectNodes = async function (verbose) {
    const tip = $("fsNodesTip");
    const wf = window.currentWorkflowPath();
    const custom = window.workflowExtraBody();
    if (!wf && !custom.workflow_content) {
      if (tip) tip.textContent = "请先在顶部选择一个工作流，再探测节点。";
      return;
    }
    if (tip) tip.textContent = "探测中…";
    try {
      const body = Object.assign({ workflow_path: wf || "" }, custom);
      const data = await window.api("/api/faceswap/nodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      window.fsFillNodeSelects(data);
      if (verbose) window.showToast("节点映射已刷新", "success");
    } catch (e) {
      if (tip) tip.textContent = "探测失败：" + e.message;
      if (verbose) window.showToast("探测失败：" + e.message, "error");
    }
  };

  window.fsFillNodeSelects = function (data) {
    const loads = data.loadimages || [];
    const opts = loads.map((n) => `<option value="${n.id}">节点 ${n.id} · ${window.escHtml(n.title)}</option>`).join("");
    const ms = $("fsMainNode");
    const rs = $("fsRefNode");
    if (ms) { ms.innerHTML = opts; if (data.main) ms.value = data.main; }
    if (rs) { rs.innerHTML = opts; if (data.ref) rs.value = data.ref; }
    const tip = $("fsNodesTip");
    if (!tip) return;
    if (!loads.length) {
      tip.className = "fs-adv-tip fs-adv-warn";
      tip.textContent = "这个工作流里没有 LoadImage 节点，无法注入素材（换一个带图输入的工作流）。";
    } else if (!data.ref) {
      tip.className = "fs-adv-tip fs-adv-warn";
      tip.textContent = `只探测到 1 个 LoadImage（节点 ${data.main}），无法同时注入主图与参考图。` +
        "请换用「双图参考」这类工作流。";
    } else {
      tip.className = "fs-adv-tip";
      tip.textContent = `探测到 ${loads.length} 个 LoadImage：` +
        loads.map((n) => `节点 ${n.id}=${n.title}`).join("，") +
        `。默认 主图→${data.main}，参考图→${data.ref}。`;
    }
  };

  window.fsSyncSeedDisabled = function () {
    const seed = $("fsSeed");
    if (seed) seed.disabled = ($("fsSeedMode")?.value === "random");
  };

  // ------------------------------------------------------------------ 提交
  function splitSelection(role) {
    const ids = [];
    const paths = [];
    for (const e of window._fsSel[role].values()) {
      if (e.kind === "history") ids.push(e.id);
      else paths.push(e.path);
    }
    return { ids, paths };
  }

  window.fsSubmit = async function () {
    return window.withLock("fsSubmit", async () => {
      const wf = window.currentWorkflowPath();
      const custom = window.workflowExtraBody();
      if (!wf && !custom.workflow_content) {
        window.showToast("请先在顶部选择工作流", "error");
        return;
      }
      const m = splitSelection("main");
      const r = splitSelection("ref");
      const mCount = m.ids.length + m.paths.length;
      const rCount = r.ids.length + r.paths.length;
      if (!mCount || !rCount) {
        window.showToast("主图和参考图各至少选一张", "error");
        return;
      }
      const pairMode = $("fsPairMode")?.value || "cross";
      if (pairMode === "zip" && mCount !== rCount) {
        window.showToast(`1:1 配对要求两侧数量相同（当前 ${mCount} vs ${rCount}）`, "error");
        return;
      }
      const total = pairMode === "zip" ? mCount : mCount * rCount;
      if (total > 30 && !confirm(`将提交 ${total} 张，确认继续？`)) return;

      const body = Object.assign({
        main_ids: m.ids, main_paths: m.paths,
        ref_ids: r.ids, ref_paths: r.paths,
        prompt: ($("fsPrompt")?.value || "").trim(),
        pair_mode: pairMode,
        seed_mode: $("fsSeedMode")?.value || "fixed",
        seed: parseInt($("fsSeed")?.value, 10) || 0,
        main_node: $("fsMainNode")?.value || null,
        ref_node: $("fsRefNode")?.value || null,
      }, { workflow_path: wf || "" }, custom);

      const btn = $("fsSubmitBtn");
      if (btn) { btn.disabled = true; btn.textContent = "提交中…"; }
      try {
        // track=false：换脸有自己的进度面板与 fsPoll，不接入全局任务 HUD
        const data = await window.submitTask({
          endpoint: "/api/faceswap/batch",
          payload: body,
          title: `批量换脸 (${total} 组)`,
          errorPrefix: "换脸提交失败",
          timeout: 600000,
          track: false,
        });
        if (!data) return;
        if (data.errors && data.errors.length) {
          window.showToast(`${data.errors.length} 个组合提交失败：${data.errors[0].error || ""}`, "error");
        }
        if (data.submitted) {
          window.showToast(`已提交 ${data.submitted}/${data.total} 个组合`, "success");
        } else {
          window.showToast("全部提交失败，请看下方任务面板", "error");
        }
        if (data.job_id) window.fsTrack(data.job_id);
      } catch (e) {
        // submitTask 已经提示过
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "🚀 开始批量换脸"; }
      }
    });
  };

  // ------------------------------------------------------------------ 进度
  window.fsShowPanel = function (show) {
    const panel = $("fsPanel");
    if (panel) panel.classList.toggle("show", !!show);
  };

  window.fsTrack = function (jobId) {
    window._fsJobId = jobId;
    if (window._fsTimer) clearInterval(window._fsTimer);
    window.fsShowPanel(true);
    window.fsPoll();
    window._fsTimer = setInterval(window.fsPoll, 1000);
  };

  window.fsPoll = async function () {
    if (!window._fsJobId) return;
    try {
      const job = await window.api(`/api/jobs/${window._fsJobId}`);
      window.fsRenderPanel(job);
      if (["done", "error", "stopped"].includes(job.status)) {
        clearInterval(window._fsTimer);
        window._fsTimer = null;
        window._fsJobId = null;
        if (typeof window.loadHistory === "function") window.loadHistory(false);
        window.showToast(
          `批量换脸结束：成功 ${job.done_count}/${job.total}，失败 ${job.error_count}`,
          job.error_count ? "error" : "success");
      }
    } catch (_) {
      /* 后端轮询 ComfyUI 时可能超时，下次再试 */
    }
  };

  window.fsRenderPanel = function (job) {
    if ($("fsPanelTitle")) $("fsPanelTitle").textContent = `${job.title || "批量换脸"} · #${job.id}`;
    const pct = job.total ? Math.round((job.done_count / job.total) * 100) : 0;
    if ($("fsBarFill")) $("fsBarFill").style.width = pct + "%";
    if ($("fsProgressText")) {
      $("fsProgressText").textContent = `${job.done_count}/${job.total}（${job.error_count} 失败）`;
    }
    const stopBtn = $("fsStopBtn");
    if (stopBtn) stopBtn.style.display = ["pending", "running"].includes(job.status) ? "" : "none";

    const list = $("fsItems");
    if (!list) return;
    list.innerHTML = "";
    (job.items || []).forEach((item, idx) => {
      const div = document.createElement("div");
      div.className = "batch-item";
      div.innerHTML =
        `<span class="batch-item-status ${item.status || "pending"}"></span>` +
        `<span class="batch-item-name">#${idx + 1} ${window.escHtml(item.prompt_preview || "")}` +
        `${item.comfyui_prompt_id ? ` <span style="color:var(--muted)">seed=${item.seed}</span>` : ""}</span>` +
        `<span style="color:var(--muted)">${window.statusText(item.status)}</span>`;
      if (item.error) div.innerHTML += `<span class="batch-item-error">${window.escHtml(item.error)}</span>`;
      list.appendChild(div);
    });
  };

  window.fsStop = async function () {
    if (!window._fsJobId) return;
    try {
      await window.api(`/api/jobs/${window._fsJobId}/cancel`, { method: "POST" });
      window.showToast("已发出停止指令", "info");
      window.fsPoll();
    } catch (e) {
      window.showToast("停止失败：" + e.message, "error");
    }
  };

  window.fsHidePanel = function () {
    window.fsShowPanel(false);
  };

  // 页面刷新后，如果还有未结束的换脸任务，自动接回进度
  window.fsResumeActive = async function () {
    try {
      const data = await window.api("/api/jobs?active=1");
      const job = (data.jobs || []).find((j) => j.job_type === "faceswap");
      if (job) window.fsTrack(job.id);
    } catch (_) {}
  };

  // Esc 收起放大编辑（捕获阶段拦截，避免和全局快捷键打架）
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && window._fsPromptExpanded) {
      e.stopPropagation();
      window.fsTogglePromptExpand(false);
    }
  }, true);
})();
