// workflow.js - 工作流模块
// 依赖：utils.js

const LS_CUSTOM_WF = "promptBrowserCustomWorkflow_v3";
const LS_HIDDEN_WF = "promptBrowserHiddenWorkflows";

window.workflowList = [];
window.workflowSort = "mtime";
window.hiddenWorkflows = [];
window._customWorkflow = null;

// -------------------------------------------------------------------
// 工作流加载和渲染
// -------------------------------------------------------------------

window.loadWorkflows = async function() {
  return window.withLock("loadWorkflows", async () => {
    try {
      const data = await window.api(`/api/workflows?sort=${window.workflowSort}`);
      window.workflowList = data.workflows || [];
      if (window._customWorkflow) {
        window.workflowList.unshift({ path: "__custom__" + window._customWorkflow.name, name: "📁 " + window._customWorkflow.name });
      }
      window.hiddenWorkflows = window.getHiddenWorkflows();
      window.renderWorkflows();
      const savedPath = window.UiState.get("workflowPath", "") || data.default || "";
      window.selectWorkflowByPath(savedPath);
    } catch (e) {
      console.error("loadWorkflows", e);
      window.showToast("加载工作流失败: " + e.message, "error");
    }
  });
};

window.renderWorkflows = function() {
  const list = document.getElementById("wfPopoverList");
  list.innerHTML = "";
  const filtered = window.workflowList.filter(w => !window.hiddenWorkflows.includes(w.path));
  document.getElementById("wfRestoreBtn").style.display = window.hiddenWorkflows.length ? "" : "none";
  const selPath = document.getElementById("wfTrigger").dataset.path || "";
  if (!filtered.length) {
    list.innerHTML = '<div class="empty-tip" style="padding:20px">无可用工作流</div>';
    return;
  }
  filtered.forEach(w => {
    const div = document.createElement("div");
    div.className = "wf-item" + (w.path === selPath ? " active" : "");
    
    const nameSpan = document.createElement("span");
    nameSpan.className = "wf-item-name";
    nameSpan.title = w.path;
    nameSpan.textContent = w.name;
    
    const hideBtn = document.createElement("button");
    hideBtn.className = "wf-item-hide";
    hideBtn.title = "隐藏";
    hideBtn.textContent = "✕";
    hideBtn.onclick = (e) => { e.stopPropagation(); window.hideWorkflow(w.path); };
    
    div.appendChild(nameSpan);
    div.appendChild(hideBtn);
    div.onclick = () => { window.selectWorkflowByPath(w.path); window.closeWorkflowPopover(); };
    list.appendChild(div);
  });
};

window.selectWorkflowByPath = function(path) {
  const w = window.workflowList.find(x => x.path === path);
  const trigger = document.getElementById("wfTrigger");
  const label = document.getElementById("wfLabel");
  if (w) {
    trigger.dataset.path = w.path;
    label.textContent = w.name;
    label.title = w.path;
  } else if (window.workflowList.length) {
    window.selectWorkflowByPath(window.workflowList[0].path);
    return;
  } else {
    trigger.dataset.path = "";
    label.textContent = "选择工作流";
  }
  window.renderWorkflows();
  window.UiState.set("workflowPath", trigger.dataset.path || "");
  window.updateRunBtn();
};

// -------------------------------------------------------------------
// 工作流隐藏/恢复
// -------------------------------------------------------------------

window.getHiddenWorkflows = function() {
  try { return JSON.parse(localStorage.getItem(LS_HIDDEN_WF) || "[]"); } catch (_) { return []; }
};

window.setHiddenWorkflows = function(list) {
  try { localStorage.setItem(LS_HIDDEN_WF, JSON.stringify(list)); } catch (_) {}
};

window.hideWorkflow = function(path) {
  const list = window.getHiddenWorkflows();
  if (!list.includes(path)) list.push(path);
  window.setHiddenWorkflows(list);
  window.hiddenWorkflows = list;
  if (document.getElementById("wfTrigger").dataset.path === path && window.workflowList.length) {
    const next = window.workflowList.find(w => w.path !== path && !list.includes(w.path));
    if (next) window.selectWorkflowByPath(next.path);
  }
  window.renderWorkflows();
  window.showToast("已隐藏工作流", "info");
};

window.restoreHiddenWorkflows = function() {
  window.setHiddenWorkflows([]);
  window.hiddenWorkflows = [];
  window.renderWorkflows();
  window.showToast("已恢复所有隐藏工作流", "success");
};

window.toggleWorkflowSort = function() {
  window.workflowSort = window.workflowSort === "mtime" ? "name" : "mtime";
  document.getElementById("wfSortBtn").textContent = window.workflowSort === "mtime" ? "最近" : "名称";
  window.UiState.set("workflowSort", window.workflowSort);
  window.loadWorkflows();
};

// -------------------------------------------------------------------
// 自定义工作流
// -------------------------------------------------------------------

window.pickWorkflowFile = function(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const content = e.target.result;
    try {
      const wf = JSON.parse(content);
      const hasClip = wf.nodes && Array.isArray(wf.nodes)
        ? wf.nodes.some(n => n && n.type === "CLIPTextEncode")
        : Object.values(wf).some(v => v && v.class_type === "CLIPTextEncode");
      if (!hasClip) { window.showToast("所选文件没有 CLIPTextEncode 节点", "error"); return; }
    } catch (_) {
      window.showToast("无效的 JSON 文件", "error"); return;
    }
    window._customWorkflow = { name: file.name, content };
    try { localStorage.setItem(LS_CUSTOM_WF, JSON.stringify(window._customWorkflow)); } catch (_) {}
    window.showToast("已加载自定义工作流: " + file.name, "success");
    window.loadWorkflows();
    window.selectWorkflowByPath("__custom__" + file.name);
  };
  reader.readAsText(file);
  event.target.value = "";
};

window.loadCustomWorkflow = function() {
  try {
    const raw = localStorage.getItem(LS_CUSTOM_WF);
    if (raw) window._customWorkflow = JSON.parse(raw);
  } catch (_) {}
};

window.currentWorkflowPath = function() {
  return document.getElementById("wfTrigger").dataset.path || "";
};

window.workflowExtraBody = function() {
  const path = window.currentWorkflowPath();
  return path.startsWith("__custom__") ? { workflow_content: window._customWorkflow?.content || "" } : {};
};
