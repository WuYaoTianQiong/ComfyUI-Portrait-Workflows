// 固定 / 取消固定碎片类型
// -------------------------------------------------------------------
window.toggleFixFragmentType = function (type) {
  if (window._composerFixed[type]) {
    delete window._composerFixed[type];
    window.showToast(`已取消固定「${type}」`, "info");
  } else {
    // 固定前必须已选该类型
    if (!window._composerSelection[type]) {
      window.showToast(`请先选择「${type}」的碎片再固定`, "warn");
      return;
    }
    window._composerFixed[type] = true;
    window.showToast(`已固定「${type}」：随机时不再变动`, "success");
  }
  // 更新列头固定按钮样式
  window._updateColumnFixUI(type);
  window._updateBatchRandomUI();
  // 更新工作台中的固定按钮
  window.renderComposerWorkbench();
};

window._updateColumnFixUI = function (type) {
  // 更新列头固定按钮
  const header = document.querySelector(`#composerList_${type}`)?.previousElementSibling;
  if (!header) return;
  let fixBtn = header.querySelector(".col-fix-btn");
  const isFixed = !!window._composerFixed[type];
  if (!fixBtn) {
    // 动态创建固定按钮
    fixBtn = document.createElement("span");
    fixBtn.className = "col-fix-btn";
    fixBtn.style.cssText = "cursor:pointer;font-size:11px;user-select:none;";
    header.appendChild(fixBtn);
  }
  // 使用 innerHTML 保留 fix-text 结构，以便在窄屏幕上隐藏文字
  fixBtn.innerHTML = `📌 <span class="fix-text">${isFixed ? '已固定' : '未固定'}</span>`;
  fixBtn.style.color = isFixed ? "var(--warning)" : "var(--muted)";
  fixBtn.onclick = (e) => { e.stopPropagation(); window.toggleFixFragmentType(type); };
};

// 更新批量随机跑图按钮提示
window._updateBatchRandomUI = function () {
  const btn = document.getElementById("composerBatchRunBtn");
  if (!btn) return;
  const fixedCount = Object.keys(window._composerFixed).length;
  if (fixedCount > 0) {
    btn.title = `固定了 ${fixedCount} 个类型，其余随机匹配`;
  } else {
    btn.title = "";
  }
};

// 更新单列选中状态
window._updateColumnSelectionUI = function (type) {
  const list = document.getElementById(`composerList_${type}`);
  if (!list) return;
  const cards = list.querySelectorAll(".composer-frag-card");
  for (const card of cards) {
    const f = {
      prompt_id: parseInt(card.dataset.promptId),
      content: card.dataset.content,
    };
    const selected = window._isFragmentSelected(type, f);
    card.classList.toggle("selected", selected);
    // 更新勾选标记
    let check = card.querySelector(".frag-check");
    if (selected) {
      if (!check) {
        check = document.createElement("div");
        check.className = "frag-check";
        check.textContent = "✓";
        card.appendChild(check);
      }
    } else {
      if (check) check.remove();
    }
  }
};

// -------------------------------------------------------------------
// 渲染组装工作台
// -------------------------------------------------------------------
window.renderComposerWorkbench = function () {
  const workbench = document.getElementById("composerWorkbench");
  if (!workbench) return;

  const selectedTypes = FRAGMENT_TYPES.filter(ft => window._composerSelection[ft.key]);

  if (selectedTypes.length === 0) {
    workbench.innerHTML = `
      <div class="workbench-empty">
        <div class="workbench-empty-icon">🧩</div>
        <div>从上方各列点击碎片，自由组合提示词</div>
        <div class="workbench-empty-hint">每列最多选一个碎片，选中的碎片会在这里拼接</div>
      </div>
    `;
    document.getElementById("composerRunBtn").disabled = true;
    return;
  }

  let html = "";
  for (const ft of FRAGMENT_TYPES) {
    const sel = window._composerSelection[ft.key];
    if (!sel) continue;
    const isCustom = sel.custom || sel.source === "custom";
    const sourceLabel = isCustom
      ? "✏️ 自定义内容"
      : (sel.source === "library"
        ? `📦 ${window.escHtml(sel.prompt_name || "碎片库")}`
        : `来源：${window.escHtml(sel.prompt_name || `#${sel.prompt_id}`)}`);
    const isFixed = !!window._composerFixed[ft.key];
    const fixLabel = isFixed ? '<span class="wb-fix-badge" title="批量随机时固定此类型">📌 已固定</span>' : '';
    const customActions = isCustom ? `
            <button class="wfa-btn wfa-save" onclick="window._saveCustomFragmentToLibrary('${ft.key.replace(/'/g, "\\'")}')" title="保存到碎片库">💾 入库</button>
            <button class="wfa-btn wfa-del" onclick="window._removeCustomFragment('${ft.key.replace(/'/g, "\\'")}')" title="删除自定义内容">🗑️ 删自定义</button>` : '';
    html += `
      <div class="workbench-frag" style="border-left: 3px solid ${ft.color}">
        <div class="workbench-frag-header">
          <span class="workbench-frag-type" style="color:${ft.color}" title="${sourceLabel}">${ft.icon} ${ft.key} ${fixLabel}</span>
          <div class="workbench-frag-actions">
            <button class="wfa-btn wfa-copy" onclick="window.copyComposerFragment('${ft.key.replace(/'/g, "\\'")}')" title="复制此碎片">📋 复制</button>
            <button class="wfa-btn ${isFixed ? 'wfa-fix' : 'wfa-fix-off'}" onclick="window.toggleFixFragmentType('${ft.key.replace(/'/g, "\\'")}')" title="${isFixed ? '取消固定' : '固定此类型（批量随机时不再变动）'}">📌 ${isFixed ? '已固定' : '未固定'}</button>${customActions}
            <button class="wfa-btn wfa-del" onclick="window.removeComposerFragment('${ft.key}')" title="移除">✕</button>
          </div>
        </div>
        <textarea class="workbench-frag-body" rows="1" data-frag-type="${ft.key}" oninput="window._onFragEdit(this)" placeholder="✏️ 点击编辑此碎片...">${window.escHtml(sel.content)}</textarea>
      </div>
    `;
  }

  workbench.innerHTML = html;

  // 等待 DOM + CSS 过渡完全渲染后再计算高度（双 requestAnimationFrame）
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      workbench.querySelectorAll(".workbench-frag-body").forEach(ta => {
        // 清除固定高度和最小高度，让浏览器按内容撑开，再读取真实 scrollHeight
        ta.style.minHeight = "0";
        ta.style.height = "auto";
        // 强制同步布局
        const sh = ta.scrollHeight;
        ta.style.height = sh + "px";
      });
    });
  });

  // 更新按钮状态
  const composed = window.getComposedPrompt();
  document.getElementById("composerRunBtn").disabled = !composed;
  const wbBtn = document.getElementById("wbModalBtn");
  if (wbBtn) wbBtn.disabled = !composed;
};


// -------------------------------------------------------------------
// 组装完整的提示词文本
// -------------------------------------------------------------------
window.getComposedPrompt = function () {
  const parts = [];
  for (const ft of FRAGMENT_TYPES) {
    const sel = window._composerSelection[ft.key];
    if (sel && sel.content) {
      parts.push(`【${ft.key}】${sel.content}`);
    }
  }
  return parts.join("\n");
};

// -------------------------------------------------------------------
// 一键复制（完整组合 + 单碎片）
// -------------------------------------------------------------------
window.copyComposedPrompt = function () {
  const text = window.getComposedPrompt();
  if (!text) { window.showToast("还没有组合任何碎片", "warn"); return; }
  const btn = document.querySelector('#wbModalOverlay .btn-ghost.btn-sm');
  if (btn) {
    window.showButtonFeedback(btn, '✅ 已复制', 1500);
  }
  navigator.clipboard.writeText(text).then(() => {
    window.showToast("完整提示词已复制", "success");
  }).catch(() => {
    window.showToast("复制失败", "error");
  });
};

window.copyComposerFragment = function (type) {
  const sel = window._composerSelection[type];
  if (!sel || !sel.content) { window.showToast("该碎片无内容", "warn"); return; }
  // 找到对应的复制按钮并添加反馈
  const workbench = document.getElementById("composerWorkbench");
  if (workbench) {
    const copyBtns = workbench.querySelectorAll('.wfa-copy');
    copyBtns.forEach(btn => {
      if (btn.textContent.includes('复制')) {
        window.showButtonFeedback(btn, '✅ 已复制', 1500);
      }
    });
  }
  navigator.clipboard.writeText(sel.content).then(() => {
    window.showToast(`${type} 碎片已复制`, "success");
  }).catch(() => {
    window.showToast("复制失败", "error");
  });
};

// -------------------------------------------------------------------
// 清空所有选择
// -------------------------------------------------------------------
window.clearComposerSelection = function () {
  window._composerSelection = {};
  window._composerFixed = {};
  // 更新所有列 UI
  for (const ft of FRAGMENT_TYPES) {
    window._updateColumnSelectionUI(ft.key);
    window._updateColumnFixUI(ft.key);
  }
  window.renderComposerWorkbench();
  window._saveComposerState();
  window._updateBatchRandomUI();
  window.showToast("已清空所有选择", "info");
};

// -------------------------------------------------------------------
// 随机组合（保留固定类型不变）