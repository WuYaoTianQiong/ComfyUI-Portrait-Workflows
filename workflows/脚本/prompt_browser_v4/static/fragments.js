// fragments.js - 碎片库管理模块
// 依赖：utils.js, ui.js
// 职责：碎片库 CRUD 面板

// -------------------------------------------------------------------
// 碎片类型定义（与 Composer 保持一致）
// -------------------------------------------------------------------
const FRAG_TYPES = [
  { key: "拍摄视角", label: "拍摄视角", color: "#f97316", icon: "📷" },
  { key: "姿态动作", label: "姿态动作", color: "#f59e0b", icon: "🏃" },
  { key: "人物身材", label: "人物身材", color: "#059669", icon: "🧍" },
  { key: "人物服饰", label: "人物服饰", color: "#a855f7", icon: "👗" },
  { key: "人物面部", label: "人物面部", color: "#10b981", icon: "👤" },
  { key: "场景环境", label: "场景环境", color: "#3b82f6", icon: "🌄" },
  { key: "光影色调", label: "光影色调", color: "#06b6d4", icon: "💡" },
  { key: "画风技术", label: "画风技术", color: "#ef4444", icon: "🎨" },
];

// -------------------------------------------------------------------
// 状态
// -------------------------------------------------------------------
window._fragmentList = [];
window._fragmentTypeFilter = "";

// -------------------------------------------------------------------
// 初始化
// -------------------------------------------------------------------
window.initFragmentLibrary = function () {
  window._restoreFragmentState();
  window.refreshFragmentLibrary();
};

// 恢复状态
window._restoreFragmentState = function () {
  const savedType = window.UiState.get("fragmentTypeFilter", "");
  if (savedType) window._fragmentTypeFilter = savedType;
  const filterEl = document.getElementById("fragTypeFilter");
  if (filterEl) filterEl.value = savedType;
};

// -------------------------------------------------------------------
// 加载碎片列表
// -------------------------------------------------------------------
window.refreshFragmentLibrary = async function () {
  // Phase 2: HTMX 模式
  if (document.body.dataset.htmxActive === "1") {
    document.body.dispatchEvent(new CustomEvent("fragmentListRefresh"));
    return;
  }

  const search = (document.getElementById("fragSearchInput") || {}).value || "";
  const params = { search, page_size: 500 };
  if (window._fragmentTypeFilter) params.fragment_type = window._fragmentTypeFilter;

  try {
    const data = await window.api("/api/fragments?" + new URLSearchParams(params).toString());
    window._fragmentList = data.items || [];
    window.renderFragmentList();
    window.updateFragmentStats(data);
  } catch (e) {
    window.showToast("加载碎片库失败: " + e.message, "error");
  }
};

// 类型筛选切换
window.onFragmentTypeFilter = function () {
  const el = document.getElementById("fragTypeFilter");
  window._fragmentTypeFilter = el ? el.value : "";
  window.UiState.set("fragmentTypeFilter", window._fragmentTypeFilter);
  window.refreshFragmentLibrary();
};

// -------------------------------------------------------------------
// 渲染列表
// -------------------------------------------------------------------
window.renderFragmentList = function () {
  const list = document.getElementById("fragmentList");
  if (!list) return;
  const items = window._fragmentList;

  if (!items || items.length === 0) {
    list.innerHTML = '<div class="frag-empty">暂无碎片<br><small>点击上方"新建碎片"创建</small></div>';
    return;
  }

  let html = "";
  for (const f of items) {
    const ft = FRAG_TYPES.find(t => t.key === f.fragment_type) || {};
    const color = ft.color || "#888";
    const icon = ft.icon || "📄";
    const contentShort = (f.content || "").length > 55
      ? (f.content || "").slice(0, 55) + "…"
      : (f.content || "");
    html += `
      <div class="frag-item" data-id="${f.id}">
        <div class="frag-item-header">
          <span class="frag-item-type" style="color:${color}">${icon} ${f.fragment_type}</span>
          <span class="frag-item-name">${window.escHtml(f.name || "(未命名)")}</span>
          <span class="frag-item-usage" title="被引用次数">🔄${f.usage_count || 0}</span>
        </div>
        <div class="frag-item-body">${window.escHtml(contentShort)}</div>
        <div class="frag-item-actions">
          <button class="btn btn-xxs btn-ghost" onclick="window.editFragment(${f.id})" title="编辑">✏️</button>
          <button class="btn btn-xxs btn-ghost" onclick="window.copyFragmentText(${f.id})" title="复制">📋</button>
          <button class="btn btn-xxs btn-danger-ghost" onclick="window.deleteFragment(${f.id})" title="删除">🗑️</button>
        </div>
      </div>
    `;
  }
  list.innerHTML = html;
};

// 统计
window.updateFragmentStats = function (data) {
  const el = document.getElementById("fragmentStats");
  if (!el) return;
  el.textContent = `共 ${data.total || window._fragmentList.length} 个独立碎片`;
};

// -------------------------------------------------------------------
// 新建/编辑
// -------------------------------------------------------------------
window.showCreateFragment = function () {
  window._editingFragmentId = null;
  window._fragmentModalOriginal = { name: "", content: "" };
  document.getElementById("fragFormTitle").textContent = "新建碎片";
  document.getElementById("fragName").value = "";
  document.getElementById("fragContent").value = "";
  document.getElementById("fragType").value = "拍摄视角";
  document.getElementById("fragTags").value = "";
  document.getElementById("fragModalOverlay").classList.add("active");
};

window.editFragment = async function (fragmentId) {
  const f = window._fragmentList.find(x => x.id === fragmentId);
  if (!f) { window.showToast("碎片不存在", "error"); return; }
  window._editingFragmentId = fragmentId;
  window._fragmentModalOriginal = { name: f.name || "", content: f.content || "" };
  document.getElementById("fragFormTitle").textContent = "编辑碎片";
  document.getElementById("fragName").value = f.name || "";
  document.getElementById("fragContent").value = f.content || "";
  document.getElementById("fragType").value = f.fragment_type || "拍摄视角";
  document.getElementById("fragTags").value = f.tags || "";
  document.getElementById("fragModalOverlay").classList.add("active");
};

window.saveFragment = async function () {
  return window.withLock("saveFragment", async () => {
    const name = document.getElementById("fragName").value.trim();
    const content = document.getElementById("fragContent").value.trim();
    const fragmentType = document.getElementById("fragType").value;
    const tags = document.getElementById("fragTags").value.trim();
    if (!content) { window.showToast("碎片内容不能为空", "warn"); return; }

    const body = { name, content, fragment_type: fragmentType, tags };
    try {
      if (window._editingFragmentId) {
        await window.api(`/api/fragments/${window._editingFragmentId}`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        window.showToast("碎片已更新", "success");
      } else {
        await window.api("/api/fragments", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        window.showToast("碎片已创建", "success");
      }
      window._fragmentModalOriginal = null;
      window.closeFragmentModal();
      window.refreshFragmentLibrary();
      if (window.refreshComposer) window._composerDataStale = true;
    } catch (e) {
      window.showToast("保存碎片失败: " + e.message, "error");
    }
  });
};

window._fragmentModalOriginal = null;

window.closeFragmentModal = function () {
  const nameEl = document.getElementById("fragName");
  const contentEl = document.getElementById("fragContent");
  const nameChanged = nameEl && nameEl.value !== (window._fragmentModalOriginal?.name || "");
  const contentChanged = contentEl && contentEl.value !== (window._fragmentModalOriginal?.content || "");
  if ((nameChanged || contentChanged) && !confirm("有未保存的修改，确定关闭？")) return;
  window._fragmentModalOriginal = null;
  document.getElementById("fragModalOverlay").classList.remove("active");
};

// -------------------------------------------------------------------
// 删除
// -------------------------------------------------------------------
window.deleteFragment = async function (fragmentId) {
  if (!confirm("确定删除此碎片？")) return;
  try {
    await window.api(`/api/fragments/${fragmentId}`, { method: "DELETE" });
    window.showToast("碎片已删除", "info");
    window.refreshFragmentLibrary();
    if (window.refreshComposer) window._composerDataStale = true;
  } catch (e) {
    window.showToast("删除失败: " + e.message, "error");
  }
};

// -------------------------------------------------------------------
// 复制
// -------------------------------------------------------------------
window.copyFragmentText = function (fragmentId) {
  const f = window._fragmentList.find(x => x.id === fragmentId);
  if (!f || !f.content) { window.showToast("无内容可复制", "warn"); return; }
  navigator.clipboard.writeText(f.content).then(() => {
    window.showToast("碎片内容已复制", "success");
  }).catch(() => {
    window.showToast("复制失败", "error");
  });
};
