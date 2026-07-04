// utils.js - 工具函数模块
// 依赖：无

// -------------------------------------------------------------------
// 通用防抖锁：防止异步操作重复触发
// -------------------------------------------------------------------
const _locks = new Map();  // key -> Promise (进行中)

window.withLock = async function(key, fn) {
  if (_locks.has(key)) {
    return _locks.get(key);
  }
  const promise = (async () => {
    try {
      return await fn();
    } finally {
      _locks.delete(key);
    }
  })();
  _locks.set(key, promise);
  return promise;
};

window.disableBtnWhilePending = function(btn, fn) {
  return async (...args) => {
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    try {
      return await fn(...args);
    } finally {
      btn.disabled = false;
    }
  };
};

// -------------------------------------------------------------------
// 网络请求
// -------------------------------------------------------------------
window.API = "";

window.api = async function(path, opts = {}) {
  const resp = await fetch(window.API + path, opts);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status} ${resp.statusText}${text ? ": " + text : ""}`);
  }
  return resp.json();
};

/** 显示通用模态框（HTML 内容） */
window.showModal = function(html) {
  let overlay = document.getElementById('dynamicModalOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'dynamicModalOverlay';
    overlay.className = 'modal-overlay';
    overlay.innerHTML = '<div class="modal" id="dynamicModal"></div>';
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) window.closeModal();
    });
    document.body.appendChild(overlay);
  }
  const modal = document.getElementById('dynamicModal');
  modal.innerHTML = html;
  overlay.classList.add('active');
};

window.closeModal = function() {
  const overlay = document.getElementById('dynamicModalOverlay');
  if (overlay) overlay.classList.remove('active');
};

/** 获取二进制响应（用于文件下载） */
window.apiBlob = async function(path, opts = {}) {
  const resp = await fetch(window.API + path, opts);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return resp.blob();
};

// -------------------------------------------------------------------
// HTML 转义
// -------------------------------------------------------------------
window.escHtml = function(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
};

// 将【标题】内容\n\n 格式的提示词转为带样式的 HTML，标题用高亮色
window.formatFragmentDisplay = function(text) {
  if (!text) return "";
  const safe = window.escHtml(text);
  return safe.replace(/【([^】]+)】/g, '<span class="frag-tag">【$1】</span>');
};

window.escAttr = function(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "&#10;").replace(/\r/g, "&#13;");
};

// -------------------------------------------------------------------
// Toast 提示
// -------------------------------------------------------------------
window.showToast = function(msg, type = "info") {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.className = "show " + (type || "info");
  clearTimeout(t._hide);
  t._hide = setTimeout(() => t.className = "", 3500);
};

// -------------------------------------------------------------------
// 通用异步操作管理器（防抖 + Loading提示）
// -------------------------------------------------------------------
window._asyncOperationFlags = {}; // 存储各个操作的loading状态

/**
 * 执行异步操作，自动处理防抖和loading提示
 * @param {string} operationId - 操作唯一标识
 * @param {Function} asyncFn - 异步函数
 * @param {Object} options - 配置选项
 * @param {string} options.loadingText - loading提示文本
 * @param {string} options.successText - 成功提示文本
 * @param {string} options.errorPrefix - 错误提示前缀
 * @param {HTMLElement} options.loadingBtn - loading时要禁用的按钮
 * @param {string} options.loadingBtnText - loading时按钮文本
 * @returns {Promise}
 */
window.withLoading = async function(operationId, asyncFn, options = {}) {
  // 防抖检查
  if (window._asyncOperationFlags[operationId]) {
    window.showToast('操作进行中，请稍候...', 'info');
    return null;
  }

  const {
    loadingText = '处理中...',
    successText = '',
    errorPrefix = '操作失败: ',
    loadingBtn = null,
    loadingBtnText = '⏳',
  } = options;

  // 设置loading状态
  window._asyncOperationFlags[operationId] = true;
  
  // 处理按钮loading状态
  let originalBtnText = '';
  if (loadingBtn) {
    loadingBtn.disabled = true;
    originalBtnText = loadingBtn.textContent;
    loadingBtn.innerHTML = loadingBtnText;
    loadingBtn.style.opacity = '0.6';
  }

  // 显示loading提示
  let loadingToast = null;
  if (loadingText) {
    loadingToast = document.createElement('div');
    loadingToast.id = `loadingToast_${operationId}`;
    loadingToast.style.cssText = `
      position: fixed;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      background: var(--panel);
      color: var(--text);
      padding: 12px 24px;
      border-radius: 8px;
      border: 1px solid var(--primary);
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      z-index: 100002;
      font-size: 14px;
    `;
    loadingToast.textContent = `⏳ ${loadingText}`;
    document.body.appendChild(loadingToast);
  }

  try {
    const result = await asyncFn();
    
    // 成功提示
    if (successText) {
      window.showToast(successText, 'success');
    }
    
    return result;
  } catch (e) {
    // 错误提示
    window.showToast(errorPrefix + e.message, 'error');
    return null;
  } finally {
    // 清理loading状态
    window._asyncOperationFlags[operationId] = false;
    
    // 恢复按钮状态
    if (loadingBtn) {
      loadingBtn.disabled = false;
      loadingBtn.textContent = originalBtnText;
      loadingBtn.style.opacity = '1';
    }
    
    // 移除loading提示
    if (loadingToast && loadingToast.parentNode) {
      loadingToast.remove();
    }
  }
};

// -------------------------------------------------------------------
// 统一管理下拉互斥：打开指定 id 的下拉，关闭其余全部
// -------------------------------------------------------------------
window.openDropdown = function(openId) {
  document.querySelectorAll('.wf-popover, .dropdown-menu').forEach(el => {
    if (el.id === openId) {
      el.classList.toggle("show");
    } else {
      el.classList.remove("show");
    }
  });
};

// -------------------------------------------------------------------
// 文件大小格式化
// -------------------------------------------------------------------
window.formatFileSize = function(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
};

window.copyFilename = async function(name) {
  if (!name) return;
  try {
    await navigator.clipboard.writeText(name);
    window.showToast("已复制: " + name, "success");
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = name;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    window.showToast("已复制: " + name, "success");
  }
};
