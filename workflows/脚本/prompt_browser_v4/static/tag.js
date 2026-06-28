/* ======== Phase 2: 标签管理功能 ======== */

// 当前选中的标签（多选）
let _selectedTags = new Set();

// 加载标签（重写，支持多选）
async function loadTags() {
  try {
    const data = await window.api("/api/tags");
    const tags = data.tags || [];

    // 更新标签选择器
    renderTagSelector(tags);

    // 更新标签管理列表
    renderTagManageList(tags);
  } catch (e) {
    console.error("加载标签失败:", e);
  }
}

// 渲染标签选择器（侧边栏下拉）
function renderTagSelector(tags) {
  const list = document.getElementById("tagSelectorList");
  if (!list) return;

  list.innerHTML = tags.map(t => {
    const id = t.id;
    const name = window.escHtml(t.name);
    const color = t.color || '#888';
    const checked = _selectedTags.has(id) ? 'checked' : '';
    const selectedClass = _selectedTags.has(id) ? ' selected' : '';
    const attrName = window.escAttr(t.name);
    return `<div class="dropdown-item${selectedClass}" onclick="window.toggleTagSelection(${id}, '${attrName}', this)">
      <input type="checkbox" ${checked}>
      <span class="tag-color" style="background:${color}"></span>
      <span class="tag-name">${name}</span>
    </div>`;
  }).join('');
}

// 切换标签选择器显示
function toggleTagSelector() {
  const dropdown = document.getElementById("tagSelectorDropdown");
  if (!dropdown) return;

  // 检查标签列表是否为空
  const list = document.getElementById("tagSelectorList");
  if (list && list.children.length === 0) {
    window.showToast("暂无标签，请先创建标签", "info");
    return;
  }

  // 互斥：统一由 openDropdown 管理，关闭其他、切换自己
  window.openDropdown("tagSelectorDropdown");

  // 点击外部关闭
  if (dropdown.classList.contains("show")) {
    setTimeout(() => {
      document.addEventListener("click", closeTagSelectorOnClickOutside);
    }, 0);
  }
}

// 点击外部关闭标签选择器
function closeTagSelectorOnClickOutside(e) {
  const trigger = document.getElementById("tagSelectorTrigger");
  const dropdown = document.getElementById("tagSelectorDropdown");

  if (trigger && dropdown && !trigger.contains(e.target) && !dropdown.contains(e.target)) {
    dropdown.classList.remove("show");
    document.removeEventListener("click", closeTagSelectorOnClickOutside);
  }
}

// 切换标签选择（侧边栏）
function toggleTagSelection(tagId, tagName, element) {
  const checkbox = element.querySelector("input[type='checkbox']");
  checkbox.checked = !checkbox.checked;

  if (checkbox.checked) {
    _selectedTags.add(tagId);
    element.classList.add("selected");
  } else {
    _selectedTags.delete(tagId);
    element.classList.remove("selected");
  }

  // 更新触发器文本
  updateTagSelectorTrigger();

  // 重新加载提示词
  window._promptPage = 1;
  window.loadPrompts();
}

// 更新标签选择器触发器文本
function updateTagSelectorTrigger() {
  const label = document.getElementById("tagSelectorLabel");
  if (!label) return;

  if (_selectedTags.size === 0) {
    label.textContent = "全部标签";
  } else if (_selectedTags.size === 1) {
    const tagId = _selectedTags.values().next().value;
    window.api(`/api/tags`).then(data => {
      const tag = (data.tags || []).find(t => t.id === tagId);
      if (label) label.textContent = tag ? tag.name : "1 个标签";
    });
  } else {
    label.textContent = `${_selectedTags.size} 个标签`;
  }
}

// 管理标签（打开模态框）
function manageTags() {
  // 关闭标签选择器
  const dropdown = document.getElementById("tagSelectorDropdown");
  if (dropdown) dropdown.classList.remove("show");

  // 加载标签列表
  loadTags();

  // 显示模态框
  document.getElementById("tagManageModal").classList.add("active");
}

// 渲染标签管理列表
function renderTagManageList(tags) {
  const list = document.getElementById("tagManageList");
  if (!list) return;

  list.innerHTML = tags.map(t => `
    <div class="tag-manage-item" data-id="${t.id}">
      <span class="tag-color" style="background:${t.color}"></span>
      <span class="tag-name">${window.escHtml(t.name)}</span>
      <span class="tag-count">${t.prompt_count || 0} 个提示词</span>
      <div class="tag-actions">
        <button class="btn btn-sm btn-ghost" onclick="editTag(${t.id})">编辑</button>
        <button class="btn btn-sm btn-danger" onclick="deleteTag(${t.id})">删除</button>
      </div>
    </div>
  `).join("");
}

// 创建标签
async function createTag() {
  const name = document.getElementById("newTagName").value.trim();
  const color = document.getElementById("newTagColor").value;

  if (!name) {
    window.showToast("请输入标签名称", "error");
    return;
  }

  try {
    const data = await window.api("/api/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        color: color
      })
    });

    if (data.success) {
      window.showToast("标签已创建", "success");
      document.getElementById("newTagName").value = "";
      loadTags();
    } else {
      window.showToast("创建失败", "error");
    }
  } catch (e) {
    window.showToast("创建失败: " + e.message, "error");
  }
}

// 编辑标签
async function editTag(tagId) {
  const newName = prompt("输入新的标签名称:");
  if (!newName) return;

  try {
    const resp = await window.api(`/api/tags/${tagId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName })
    });

    if (resp.success) {
      window.showToast("标签已更新", "success");
      loadTags();
    }
  } catch (e) {
    window.showToast("更新失败: " + e.message, "error");
  }
}

// 删除标签
async function deleteTag(tagId) {
  if (!confirm("确定删除该标签吗？")) return;

  try {
    const resp = await window.api(`/api/tags/${tagId}`, {
      method: "DELETE"
    });

    if (resp.success) {
      window.showToast("标签已删除", "success");
      loadTags();
    }
  } catch (e) {
    window.showToast("删除失败: " + e.message, "error");
  }
}

// 关闭标签管理模态框
function closeTagManageModal() {
  document.getElementById("tagManageModal").classList.remove("active");
}

// ======== 共享函数：模态框标签多选 ========
// 以下两个函数供 prompt.js 的新建/编辑模态框复用

/**
 * 共享函数：渲染标签多选框到指定容器（新建/编辑提示词模态框）
 * @param {string} containerId - 容器元素 ID（如 "f_tags_select"）
 * @param {Set|Array} selectedIds - 已选中的标签 ID
 */
window.renderTagCheckboxes = async function(containerId, selectedIds) {
  const container = document.getElementById(containerId);
  if (!container) return;
  try {
    const data = await window.api("/api/tags");
    const tags = data.tags || [];
    const ids = new Set(selectedIds || []);
    container.innerHTML = tags.map(t => {
      const color = t.color || "#8b5cf6";
      const sel = ids.has(t.id) ? " selected" : "";
      return `<div class="tag-option${sel}" data-tag-id="${t.id}"
        onclick="window.toggleTagOption(this)"
        style="display:inline-block;padding:4px 10px;margin:3px;
        background:${sel ? color.replace(")", "30)") : color + "18"};
        color:${color};border:1px solid ${color}20;
        border-radius:6px;cursor:pointer;font-size:13px;user-select:none">
        ${window.escHtml(t.name)}
      </div>`;
    }).join("");
  } catch (e) {
    console.error("renderTagCheckboxes 失败:", e);
  }
};

/**
 * 共享函数：切换模态框标签多选状态
 * @param {HTMLElement} el - 被点击的 .tag-option 元素
 */
window.toggleTagOption = function(el) {
  el.classList.toggle("selected");
  const color = el.style.borderColor || "#8b5cf6";
  if (el.classList.contains("selected")) {
    el.style.background = color.replace(")", "30)");
  } else {
    el.style.background = color + "18";
  }
};

// ======== 挂载到 window 对象 ========
window.loadTags = loadTags;
window.renderTagSelector = renderTagSelector;
window.toggleTagSelector = toggleTagSelector;
window.closeTagSelectorOnClickOutside = closeTagSelectorOnClickOutside;
window.toggleTagSelection = toggleTagSelection;
window.updateTagSelectorTrigger = updateTagSelectorTrigger;
window.manageTags = manageTags;
window.renderTagManageList = renderTagManageList;
window.createTag = createTag;
window.editTag = editTag;
window.deleteTag = deleteTag;
window.closeTagManageModal = closeTagManageModal;
