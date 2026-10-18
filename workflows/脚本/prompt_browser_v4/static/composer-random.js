// -------------------------------------------------------------------
window.randomComposer = function () {
  if (!window._composerFragmentData) {
    window.showToast("请先加载碎片数据", "warn");
    return;
  }
  const grouped = window._composerFragmentData.grouped;
  // 只随机未固定的类型，固定类型保持不变
  for (const ft of FRAGMENT_TYPES) {
    if (window._composerFixed[ft.key] && window._composerSelection[ft.key]) {
      continue; // 跳过固定类型
    }
    const frags = grouped[ft.key] || [];
    if (frags.length > 0) {
      const pick = frags[Math.floor(Math.random() * frags.length)];
      window._composerSelection[ft.key] = {
        content: pick.content,
        prompt_id: pick.prompt_id,
        prompt_name: pick.prompt_name,
        type: ft.key,
      };
    }
  }
  for (const ft of FRAGMENT_TYPES) {
    window._updateColumnSelectionUI(ft.key);
  }
  window.renderComposerWorkbench();
  window._saveComposerState();

  // 滚动每列到已选卡片（列视图：滚动各列内部；行视图：滚动整个列表容器）
  setTimeout(() => {
    try {
      if (window._composerViewMode === "list") {
        // 行视图：滚动整个列表容器到第一个选中项
        const first = document.querySelector(".composer-list-card.selected");
        if (first) {
          first.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      } else {
        // 列视图：逐列滚动到该列的选中项
        for (const ft of FRAGMENT_TYPES) {
          const list = document.getElementById(`composerList_${ft.key}`);
          if (!list) continue;
          const sel = list.querySelector(".composer-frag-card.selected");
          if (sel) {
            // 精确计算：让选中项在列表可视区域中间
            const listRect = list.getBoundingClientRect();
            const selRect = sel.getBoundingClientRect();
            const relativeTop = sel.offsetTop - list.offsetTop;
            const targetScroll = relativeTop - list.clientHeight / 2 + sel.offsetHeight / 2;
            list.scrollTo({ top: Math.max(0, targetScroll), behavior: "smooth" });
          }
        }
      }
    } catch(e) {}
  }, 150);

  window.showToast("已随机组合", "info");
};

// 为随机组合按钮添加反馈
window.randomComposerWithFeedback = function() {
  const btn = event.target;
  if (btn && btn.tagName === 'BUTTON') {
    const originalText = btn.innerHTML;
    btn.innerHTML = '🎲 随机中...';
    btn.disabled = true;
    window.randomComposer();
    setTimeout(() => {
      btn.innerHTML = originalText;
      btn.disabled = false;
    }, 1000);
  } else {
    window.randomComposer();
  }
};

// -------------------------------------------------------------------
// 批量随机组合跑图
// -------------------------------------------------------------------
window.composerBatchRandomRun = async function () {
  return window.withLock("composerBatchRandomRun", async () => {
    const count = parseInt(document.getElementById("composerBatchCount")?.value || "1");
    const workflowPath = window.currentWorkflowPath();
    if (!workflowPath) { window.showToast("请先选择工作流", "error"); return; }

    const fixedFragments = {};
    for (const ft of FRAGMENT_TYPES) {
      if (window._composerFixed[ft.key] && window._composerSelection[ft.key]) {
        fixedFragments[ft.key] = window._composerSelection[ft.key].content;
      }
    }

    const btnState = window._runBtnState(document.getElementById("composerBatchRunBtn"), "发送中...");
    btnState.loading();
    try {
      const body = Object.assign({
        count, workflow_path: workflowPath,
        orientation: window.currentOrientation,
        quality: window.getQuality(),
        negative_prompt: "",
        fixed_fragments: fixedFragments,
      }, window.workflowExtraBody());
      const data = await window.submitTask({
        endpoint: "/api/composer/batch_random_run", payload: body,
        title: `批量随机组合 (${count} 组)`, errorPrefix: "批量随机跑图失败",
      });
      if (!data) return;
      const fixedN = Object.keys(fixedFragments).length;
      window.showToast(`批量随机组合已推送 (job ${data.job_id})${fixedN ? `（固定 ${fixedN} 个）` : ""}`, "success");
    } catch (e) {
      window.showToast("批量随机跑图失败: " + e.message, "error");
    } finally {
      btnState.restore();
    }
  });
};

// -------------------------------------------------------------------
// 随机组合提示词详情弹窗
// -------------------------------------------------------------------
window.showRandomPromptDetail = function(itemId) {
  const item = (window._galleryAllItems || window._historyItems)?.find(it => it.id === itemId);
  if (!item || !item.prompt_params) { window.showToast("未找到提示词详情", "error"); return; }
  const pp = typeof item.prompt_params === "string" ? JSON.parse(item.prompt_params) : item.prompt_params;
  if (pp.source !== "composer_random") return;

  const selection = pp.selection || {};
  const fixedTypes = pp.fixed_types || [];
  const seed = pp.seed || 0;
  const prompt = pp.prompt || "";
  const negative = pp.negative_prompt || "";

  // 构建碎片卡片列表
  let cardsHtml = "";
  for (const [ft, content] of Object.entries(selection)) {
    const isFixed = fixedTypes.includes(ft);
    const typeColor = isFixed ? "var(--warning)" : "var(--primary)";
    const typeIcon = isFixed ? "📌" : "🎲";
    const escapedContent = window.escHtml(content);
    cardsHtml += `
      <div style="background:var(--panel-2);border-radius:8px;padding:10px 14px;border-left:3px solid ${typeColor}">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
          <span style="font-size:11px;color:${typeColor};font-weight:600;flex:1">${typeIcon} ${window.escHtml(ft)}</span>
          ${isFixed ? '<span style="font-size:10px;background:rgba(245,158,11,0.15);color:var(--warning);padding:1px 6px;border-radius:4px">固定</span>' : ""}
          <button style="background:transparent;border:1px solid var(--border-soft);color:var(--muted);font-size:11px;padding:2px 8px;border-radius:4px;cursor:pointer" onclick="window.copyText('${escapedContent.replace(/'/g, "\\'")}')">📋 复制</button>
        </div>
        <div style="font-size:12.5px;color:var(--text);line-height:1.6;white-space:pre-wrap;max-height:80px;overflow-y:auto">${escapedContent}</div>
      </div>`;
  }

  const bodyHtml = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <!-- 种子 -->
      <div style="display:flex;align-items:center;gap:8px">
        <label style="font-size:11px;color:var(--muted);min-width:40px">种子</label>
        <code style="background:var(--bg);padding:3px 10px;border-radius:6px;font-size:13px;color:var(--text);border:1px solid var(--border-soft)">${seed}</code>
      </div>

      <!-- 碎片列表 -->
      <div>
        <div style="font-size:11px;color:var(--muted);margin-bottom:8px">碎片选取（${Object.keys(selection).length} 个类型）</div>
        <div style="display:flex;flex-direction:column;gap:8px;max-height:260px;overflow-y:auto;padding-right:4px">${cardsHtml}</div>
      </div>

      <!-- 完整提示词（可折叠） -->
      <details style="border:1px solid var(--border-soft);border-radius:8px;overflow:hidden">
        <summary style="cursor:pointer;padding:8px 14px;background:var(--panel-2);font-size:12px;color:var(--muted);user-select:none;display:flex;align-items:center;gap:6px">
          📄 完整提示词
          <button style="margin-left:auto;background:transparent;border:1px solid var(--border-soft);color:var(--muted);font-size:11px;padding:2px 8px;border-radius:4px;cursor:pointer" onclick="event.stopPropagation();window.copyRandomPrompt()">📋 复制</button>
        </summary>
        <div style="padding:10px 14px">
          <textarea id="randomPromptText" readonly style="width:100%;min-height:100px;background:var(--bg);color:var(--text);border:1px solid var(--border-soft);border-radius:6px;padding:8px;font-size:12px;resize:vertical;line-height:1.6">${window.escHtml(prompt)}</textarea>
        </div>
      </details>

      <!-- 负面提示词（如果有） -->
      ${negative ? `<details style="border:1px solid var(--border-soft);border-radius:8px;overflow:hidden">
        <summary style="cursor:pointer;padding:8px 14px;background:var(--panel-2);font-size:12px;color:var(--muted);user-select:none">⚠️ 负面提示词</summary>
        <div style="padding:10px 14px;font-size:12px;color:var(--text-secondary);white-space:pre-wrap">${window.escHtml(negative)}</div>
      </details>` : ""}
    </div>`;

  let overlay = document.getElementById("randomPromptModal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "randomPromptModal";
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal" style="max-width:810px;width:92%">
        <div class="modal-header">
          <h2>🎲 随机组合提示词</h2>
          <button class="close-btn" onclick="document.getElementById('randomPromptModal').classList.remove('active')">✕</button>
        </div>
        <div class="modal-body" id="randomPromptModalBody"></div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="document.getElementById('randomPromptModal').classList.remove('active')">关闭</button>
          <button class="btn btn-primary" onclick="window.copyRandomPrompt()">📋 复制提示词</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
  }
  document.getElementById("randomPromptModalBody").innerHTML = bodyHtml;
  overlay.classList.add("active");
};

window.copyRandomPrompt = function() {
  const textarea = document.getElementById("randomPromptText");
  if (!textarea) return;
  navigator.clipboard.writeText(textarea.value).then(() => {
    window.showToast("提示词已复制", "success");
  }).catch(() => {
    textarea.select();
    document.execCommand("copy");
    window.showToast("提示词已复制", "success");
  });
};

window.copyText = function(text) {
  navigator.clipboard.writeText(text).then(() => {
    window.showToast("已复制", "success");
  }).catch(() => {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    window.showToast("已复制", "success");
  });
};

// -------------------------------------------------------------------