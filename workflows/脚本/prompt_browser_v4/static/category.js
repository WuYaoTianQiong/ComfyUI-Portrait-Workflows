/* ======== Phase 2: 分类管理功能 ======== */

// 当前选中的分类 ID（null = 全部分类）
window._currentCategoryId = null;

// 加载分类到下拉框
async function loadCategories() {
  try {
    const data = await api("/api/categories?tree=true");
    const select = document.getElementById("categorySelect");
    if (!select) return;
    
    const categories = data.categories || [];
    
    // 保留第一个选项
    if (categories.length === 0) {
      select.innerHTML = '<option value="">暂无分类，请先创建</option>';
      select.disabled = false;
      select.style.color = "var(--muted)";
    } else {
      select.innerHTML = '<option value="">全部分类</option>';
      
      // 递归添加选项
      function addOptions(categories, level = 0) {
        categories.forEach(cat => {
          const indent = '　'.repeat(level); // 全角空格缩进
          const opt = document.createElement("option");
          opt.value = cat.id;
          opt.textContent = indent + cat.name + ` (${cat.prompt_count || 0})`;
          select.appendChild(opt);
          
          if (cat.children && cat.children.length > 0) {
            addOptions(cat.children, level + 1);
          }
        });
      }
      
      addOptions(categories);
      select.style.color = "";
    }
    
    // 恢复之前的选择
    if (window._currentCategoryId && categories.length > 0) {
      select.value = window._currentCategoryId;
    }
  } catch (e) {
    console.error("加载分类失败:", e);
    window.showToast("加载分类失败: " + e.message, "error");
  }
}

// 分类下拉框变化
function onCategoryChange() {
  const select = document.getElementById("categorySelect");
  if (!select) return;
  
  const value = select.value;
  window._currentCategoryId = value ? parseInt(value) : null;
  window._promptPage = 1;
  window.loadPrompts();
}

// 管理分类（打开模态框）
async function manageCategories() {
  try {
    const data = await api("/api/categories?tree=false");
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
    showToast("加载分类失败: " + e.message, "error");
  }
}

// 渲染分类管理列表
function renderCategoryManageList(categories) {
  const list = document.getElementById("categoryManageList");
  if (!list) return;

  list.innerHTML = categories.map(cat => `
    <div class="category-manage-item" data-id="${cat.id}">
      <span class="category-color" style="background:${cat.color}"></span>
      <span class="category-name">${escHtml(cat.name)}</span>
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
    showToast("请输入分类名称", "error");
    return;
  }

  try {
    const data = await api("/api/categories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        color: color,
        parent_id: parentId ? parseInt(parentId) : null
      })
    });

    if (data.success) {
      showToast("分类已创建", "success");
      document.getElementById("newCategoryName").value = "";
      manageCategories(); // 刷新列表
      loadCategories(); // 刷新分类树
    } else {
      showToast("创建失败", "error");
    }
  } catch (e) {
    showToast("创建失败: " + e.message, "error");
  }
}

// 编辑分类
async function editCategory(categoryId) {
  // 简化实现：直接弹出 prompt 修改名称
  const newName = prompt("输入新的分类名称:");
  if (!newName) return;

  try {
    const resp = await api(`/api/categories/${categoryId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName })
    });

    if (resp.success) {
      showToast("分类已更新", "success");
      manageCategories();
      loadCategories();
    }
  } catch (e) {
    showToast("更新失败: " + e.message, "error");
  }
}

// 删除分类
async function deleteCategory(categoryId) {
  if (!confirm("确定删除该分类吗？子分类也会被删除。")) return;

  try {
    const resp = await api(`/api/categories/${categoryId}`, {
      method: "DELETE"
    });

    if (resp.success) {
      showToast("分类已删除", "success");
      manageCategories();
      loadCategories();
    }
  } catch (e) {
    showToast("删除失败: " + e.message, "error");
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

