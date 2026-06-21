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

// -------------------------------------------------------------------
// HTML 转义
// -------------------------------------------------------------------
window.escHtml = function(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
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
