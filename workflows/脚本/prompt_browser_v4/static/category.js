/* ======== Phase2: 分类管理功能 ======== */

// 当前选中的分类 ID（null = 全部分类）
window._currentCategoryId = null;

/**
 * 共享函数：将分类树渲染到任意 <select> 元素
 * 侧边栏下拉框和模态框下拉框均复用此函数
 * @param {string} selectId  - <select> 元素的 ID
 * @param {string|number} selectedId - 需要选中的分类 ID
 * @param {boolean} showCount  - 是否显示 prompt_count
 */
window.renderCategorySelect = async function(selectId, selectedId, showCount) {
  const select = document.getElementById(selectId);
  if (!select) return;
  try {
    const data = await window.api("/api/categories?tree=true");
    const categories = data.categories || [];
    select.innerHTML = selectId === "f_category"
      ? '<option value="">未分类</option>'
      : '<option value="">全部分类</option>';

    function addOpts(cats, level) {
      (cats || []).forEach(c => {
        const opt = document.createElement("option");
        opt.value = c.id;
        const indent = "　".repeat(level);
        opt.textContent = indent + c.name + (showCount ? ` (${c.prompt_count || 0})` : "");
        if (String(selectedId) === String(c.id)) opt.selected = true;
        select.appendChild(opt);
        if (c.children && c.children.length) addOpts(c.children, level + 1);
      });
    }
    addOpts(categories, 0);

    // 添加组合模板特殊选项（仅侧边栏分类筛选）
    if (selectId === "categorySelect") {
      const sep = document.createElement("option");
      sep.disabled = true;
      sep.textContent = "──────────";
      select.appendChild(sep);
      const tplOpt = document.createElement("option");
      tplOpt.value = "__templates__";
      tplOpt.textContent = "📦 组合模板";
      select.appendChild(tplOpt);
    }

    select.style.color = "";
  } catch (e) {
    console.error("renderCategorySelect 失败:", e);
  }
};

// 加载分类到侧边栏下拉框（复用共享函数）
async function loadCategories() {
  await window.renderCategorySelect("categorySelect", window._currentCategoryId || "", true);
}

// 分类下拉框变化
function onCategoryChange() {
  const select = document.getElementById("categorySelect");
  if (!select) return;

  const value = select.value;
  window.UiState.set("categoryFilter", value);
  if (value === "__templates__") {
    window._currentCategoryId = "__templates__";
    window._promptPage = 1;
    window.loadTemplatesAsItems();
  } else {
    window._currentCategoryId = value ? parseInt(value) : null;
    window._promptPage = 1;
    window.loadPrompts();
  }
}

// 管理分类（打开模态框）
async function manageCategories() {
  try {
    const data = await window.api("/api/categories?tree=false");
    const categories = data.categories || [];

    // 填充父分类下拉框
    const parentSelect = document.getElementById("newCategoryParent");
    parentSelect.innerHTML = '<option value="">无（顶级分类）</option>';
    categories.forEach(cat => {
      const opt = document.createElement("option");
      opt.value = cat.id;
      opt.textContent = cat.name;
      parentSelect.appendChild(opt);
    });

    // 渲染分类列表
    renderCategoryManageList(categories);

    // 显示模态框
    document.getElementById("categoryManageModal").classList.add("active");
  } catch (e) {
    window.showToast("加载分类失败: " + e.message, "error");
  }
}

// 渲染分类管理列表
function renderCategoryManageList(categories) {
  const list = document.getElementById("categoryManageList");
  if (!list) return;

  list.innerHTML = categories.map(cat => `
    <div class="category-manage-item" data-id="${cat.id}">
      <span class="category-color" style="background:${cat.color}"></span>
      <span class="category-name">${window.escHtml(cat.name)}</span>
      <span class="category-count">${cat.prompt_count || 0} 个提示词</span>
      <div class="category-actions">
        <button class="btn btn-sm btn-ghost" onclick="editCategory(${cat.id})">编辑</button>
        <button class="btn btn-sm btn-danger" onclick="deleteCategory(${cat.id})">删除</button>
      </div>
    </div>
  `).join("");
}

// 创建分类
async function createCategory() {
  const name = document.getElementById("newCategoryName").value.trim();
  const color = document.getElementById("newCategoryColor").value;
  const parentId = document.getElementById("newCategoryParent").value;

  if (!name) {
    window.showToast("请输入分类名称", "error");
    return;
  }

  try {
    const data = await window.api("/api/categories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        color: color,
        parent_id: parentId ? parseInt(parentId) : null
      })
    });

    if (data.success) {
      window.showToast("分类已创建", "success");
      document.getElementById("newCategoryName").value = "";
      manageCategories();
      loadCategories();
    } else {
      window.showToast("创建失败", "error");
    }
  } catch (e) {
    window.showToast("创建失败: " + e.message, "error");
  }
}

// 编辑分类
async function editCategory(categoryId) {
  const newName = prompt("输入新的分类名称:");
  if (!newName) return;

  try {
    const resp = await window.api(`/api/categories/${categoryId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName })
    });

    if (resp.success) {
      window.showToast("分类已更新", "success");
      manageCategories();
      loadCategories();
    }
  } catch (e) {
    window.showToast("更新失败: " + e.message, "error");
  }
}

// 删除分类
async function deleteCategory(categoryId) {
  if (!confirm("确定删除该分类吗？子分类也会被删除。")) return;

  try {
    const resp = await window.api(`/api/categories/${categoryId}`, {
      method: "DELETE"
    });

    if (resp.success) {
      window.showToast("分类已删除", "success");
      manageCategories();
      loadCategories();
    }
  } catch (e) {
    window.showToast("删除失败: " + e.message, "error");
  }
}

// 关闭分类管理模态框
function closeCategoryManageModal() {
  document.getElementById("categoryManageModal").classList.remove("active");
}

// ======== 挂载到 window 对象 ========
window.loadCategories = loadCategories;
window.onCategoryChange = onCategoryChange;
window.manageCategories = manageCategories;
window.renderCategoryManageList = renderCategoryManageList;
window.createCategory = createCategory;
window.editCategory = editCategory;
window.deleteCategory = deleteCategory;
window.closeCategoryManageModal = closeCategoryManageModal;
