// workflow.js - 工作流模块
// 依赖：utils.js

const LS_CUSTOM_WF = "pb_workflow_custom_v1";
const LS_HIDDEN_WF = "pb_workflow_hidden_v1";
const CUSTOM_WF_PREFIX = "__custom__";

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
        window.workflowList.unshift({ path: CUSTOM_WF_PREFIX + window._customWorkflow.name, name: "📁 " + window._customWorkflow.name });
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
  if (list) {
    list.innerHTML = "";
    const filtered = window.workflowList.filter(w => !window.hiddenWorkflows.includes(w.path));
    document.getElementById("wfRestoreBtn").style.display = window.hiddenWorkflows.length ? "" : "none";
    const selPath = document.getElementById("wfTrigger").dataset.path || "";
    if (!filtered.length) {
      list.innerHTML = '<div class="empty-tip" style="padding:20px">无可用工作流</div>';
    } else {
      filtered.forEach(w => { window._appendWfItem(list, w, selPath); });
    }
  }
  // 同时渲染到弹窗列表
  const modalList = document.getElementById("wfModalList");
  if (modalList) {
    modalList.innerHTML = "";
    if (window.workflowList.length === 0) {
      modalList.innerHTML = '<div class="empty-tip" style="padding:20px">无可用工作流</div>';
    } else {
      const selPath = document.getElementById("wfTrigger").dataset.path || "";
      const filtered = window.workflowList.filter(w => !window.hiddenWorkflows.includes(w.path));
      document.getElementById("wfRestoreBtnModal").style.display = window.hiddenWorkflows.length ? "" : "none";
      filtered.forEach(w => { window._appendWfItem(modalList, w, selPath); });
    }
  }
};

window._appendWfItem = function(container, w, selPath) {
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
  hideBtn.onclick = (e) => { e.stopPropagation(); window.hideWorkflow(w.path); window.renderWorkflows(); };
  div.appendChild(nameSpan);
  div.appendChild(hideBtn);
  div.onclick = () => { window.selectWorkflowByPath(w.path); window.closeWfModal(); };
  container.appendChild(div);
};

window.openWfModal = function() {
  document.getElementById("wfModalOverlay").classList.add("active");
  window.renderWorkflows();
};
window.closeWfModal = function() {
  document.getElementById("wfModalOverlay").classList.remove("active");
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
  // 更新组合创作页面的批量随机跑图按钮状态
  const batchBtn = document.getElementById("composerBatchRunBtn");
  if (batchBtn) batchBtn.disabled = !window.currentWorkflowPath();
  // 更新灯箱中的工作流显示
  if (window.updateLightboxWorkflowDisplay) {
    window.updateLightboxWorkflowDisplay();
  }
};

// -------------------------------------------------------------------
// 工作流隐藏/恢复
// -------------------------------------------------------------------

window.getHiddenWorkflows = function() {
  try {
    let raw = localStorage.getItem(LS_HIDDEN_WF);
    if (!raw) raw = localStorage.getItem("promptBrowserHiddenWorkflows"); // 旧键迁移
    return raw ? JSON.parse(raw) : [];
  } catch (_) { return []; }
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
  const label = window.workflowSort === "mtime" ? "最近" : "名称";
  const btn1 = document.getElementById("wfSortBtn");
  const btn2 = document.getElementById("wfSortBtnModal");
  if (btn1) btn1.textContent = label;
  if (btn2) btn2.textContent = label;
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
      if (!hasClip) { window.showToast("所选工作流不含文本提示词节点（CLIPTextEncode），将跳过提示词注入", "info"); }
    } catch (_) {
      window.showToast("无效的 JSON 文件", "error"); return;
    }
    window._customWorkflow = { name: file.name, content };
    try { localStorage.setItem(LS_CUSTOM_WF, JSON.stringify(window._customWorkflow)); } catch (_) {}
    window.showToast("已加载自定义工作流: " + file.name, "success");
    window.loadWorkflows();
    window.selectWorkflowByPath(CUSTOM_WF_PREFIX + file.name);
  };
  reader.readAsText(file);
  event.target.value = "";
};

window.loadCustomWorkflow = function() {
  try {
    let raw = localStorage.getItem(LS_CUSTOM_WF);
    if (!raw) raw = localStorage.getItem("promptBrowserCustomWorkflow_v3"); // 旧键迁移
    if (raw) { window._customWorkflow = JSON.parse(raw); localStorage.setItem(LS_CUSTOM_WF, raw); }
  } catch (_) {}
};

window.currentWorkflowPath = function() {
  return document.getElementById("wfTrigger").dataset.path || "";
};

window.workflowExtraBody = function() {
  const path = window.currentWorkflowPath();
  return path.startsWith(CUSTOM_WF_PREFIX) ? { workflow_content: window._customWorkflow?.content || "" } : {};
};
