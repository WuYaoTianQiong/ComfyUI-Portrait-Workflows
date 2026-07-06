// 模板面板拖拽缩放
// -------------------------------------------------------------------
window.setupTemplatePanelResize = function () {
  // 模板已改为弹窗
};

// -------------------------------------------------------------------
// 碎片库面板
// -------------------------------------------------------------------
window.toggleFragmentLibrary = function () {
  const overlay = document.getElementById("fragmentLibraryOverlay");
  if (!overlay) return;
  const showing = overlay.classList.contains("active");
  if (showing) {
    window.hideFragmentLibrary();
  } else {
    overlay.classList.add("active");
    if (window.initFragmentLibrary) window.initFragmentLibrary();
  }
};

window.hideFragmentLibrary = function () {
  const overlay = document.getElementById("fragmentLibraryOverlay");
  if (overlay) overlay.classList.remove("active");
  // 关闭后刷新 Composer
  window._composerDataStale = true;
  window.refreshComposer();
};

// 查看碎片完整内容（弹窗）
window._showFullFrag = function (type, promptId) {
  const grouped = window._composerFragmentData?.grouped;
  if (!grouped || !grouped[type]) return;
  const frag = grouped[type].find(f => {
    if (f.fragment_id) return f.fragment_id === promptId;
    return f.prompt_id === promptId;
  });
  if (!frag) return;

  document.getElementById("fragFullContent").textContent = frag.content;
  document.getElementById("fragFullType").textContent = type;

  // 来源显示为可点击链接
  const sourceEl = document.getElementById("fragFullSource");
  if (frag.source_names && frag.source_names.length > 1) {
    const links = frag.source_names.map(s => {
      // 从 "古风窗边·逆光回眸 (ID:116)" 提取 ID
      const m = s.match(/ID:(\d+)/);
      const name = s.replace(/\s*\(ID:\d+\)/, "");
      if (m) {
        return `<a href="#" onclick="event.preventDefault();window._closeFullFrag();window.jumpToPrompt(${m[1]})" style="color:var(--primary);text-decoration:none" title="跳转到此提示词">${window.escHtml(name)}</a>`;
      }
      return window.escHtml(s);
    });
    sourceEl.innerHTML = `出现在 <strong>${frag.dup_count}</strong> 条提示词中:<br>${links.join("、")}`;
  } else if (frag.prompt_id && frag.prompt_id > 0) {
    sourceEl.innerHTML = `来源: <a href="#" onclick="event.preventDefault();window._closeFullFrag();window.jumpToPrompt(${frag.prompt_id})" style="color:var(--primary);text-decoration:none">${window.escHtml(frag.prompt_name || `#${frag.prompt_id}`)}</a>`;
  } else if (frag.source === "library") {
    sourceEl.innerHTML = `来源: 📦 碎片库`;
  } else {
    sourceEl.textContent = `来源: ${frag.prompt_name || ""}`;
  }

  document.getElementById("fragFullModal").classList.add("active");
};
window._closeFullFrag = function () {
  document.getElementById("fragFullModal").classList.remove("active");
};

// 复制碎片完整内容
window.copyFragFullContent = function () {
  const content = document.getElementById("fragFullContent").textContent;
  if (!content) {
    window.showToast("没有内容可复制", "warn");
    return;
  }
  navigator.clipboard.writeText(content).then(() => {
    window.showToast("碎片内容已复制", "success");
  }).catch(() => {
    window.showToast("复制失败", "error");
  });
};

// 工作台碎片编辑：实时更新选中内容 + 自动增高
window._onFragEdit = function (el) {
  const type = el.dataset.fragType;
  if (window._composerSelection[type]) {
    window._composerSelection[type].content = el.value;
    window._saveComposerState();
  }
  // 清除固定高度和最小高度，让浏览器按内容撑开，读取真实 scrollHeight
  requestAnimationFrame(() => {
    el.style.minHeight = "0";
    el.style.height = "auto";
    const sh = el.scrollHeight;
    el.style.height = sh + "px";
  });
};

window._detectConflicts = function (promptText) {
  const warnings = [];

  // 提取各碎片内容
  const frags = {};
  const pattern = /【([^】]+)】\s*(.*?)(?=\n【|$)/g;
  let m;
  while ((m = pattern.exec(promptText)) !== null) {
    frags[m[1].trim()] = m[2].trim();
  }

  // 1. 服装矛盾检测
  const clothTypes = [];
  if (frags["人物服饰"]) {
    const cloth = frags["人物服饰"];
    if (/抹胸|吊带|背心/.test(cloth)) clothTypes.push("露肩上衣");
    if (/毛衣|外套|开衫/.test(cloth)) clothTypes.push("外套");
    if (/短袖|T恤/.test(cloth)) clothTypes.push("短袖");
    if (/长裙|连衣裙/.test(cloth)) clothTypes.push("长裙");
    if (/短裤|裙子/.test(cloth)) clothTypes.push("下装");
    if (clothTypes.length >= 2 && clothTypes.includes("露肩上衣") && clothTypes.includes("外套")) {
      warnings.push("【人物服饰】可能同时描述多件上衣（抹胸/吊带 + 毛衣/外套），请确认");
    }
  }

  // 2. 姿态动作中引用的衣物与人物服饰是否一致
  if (frags["姿态动作"] && frags["人物服饰"]) {
    const pose = frags["姿态动作"];
    const cloth = frags["人物服饰"];
    // 检查姿态中提到的衣物类型是否与服饰一致
    if (/毛衣/.test(pose) && /抹胸|吊带/.test(cloth)) {
      warnings.push('【姿态动作】提到"毛衣"但【人物服饰】描述的是抹胸/吊带，请统一');
    }
    if (/外套/.test(pose) && !/外套/.test(cloth)) {
      warnings.push('【姿态动作】提到"外套"但【人物服饰】未描述外套');
    }
  }

  // 3. 画风冲突检测
  if (frags["画风技术"]) {
    const style = frags["画风技术"];
    const styleGroups = [
      { type: "写实", keywords: ["真人", "写实", "照片", "摄影", "胶片", "写真"] },
      { type: "动漫", keywords: ["动漫", "二次元", "插画", "CG", "厚涂", "赛璐璐"] },
      { type: "情绪", keywords: ["治愈", "温馨", "甜美", "柔和"] },
      { type: "压迫", keywords: ["压迫感", "张力", "冲击力", "激烈"] },
    ];

    const matched = styleGroups.filter(g => g.keywords.some(k => style.includes(k)));
    // 写实与动漫冲突
    const isReal = matched.some(g => g.type === "写实");
    const isAnime = matched.some(g => g.type === "动漫");
    if (isReal && isAnime) {
      warnings.push("【画风技术】同时包含写实和动漫关键词，风格矛盾。请二选一");
    }
    // 情绪冲突
    const isHealing = matched.some(g => g.type === "情绪");
    const isIntense = matched.some(g => g.type === "压迫");
    if (isHealing && isIntense) {
      warnings.push('【画风技术】"治愈"和"压迫感"情绪矛盾，请统一');
    }
  }

  // 4. 人物身材与人物面部重复检测
  if (frags["人物身材"] && frags["人物面部"]) {
    const body = frags["人物身材"];
    const face = frags["人物面部"];
    // 检测身材中是否混入了面容描述
    const faceKeywords = ["清纯", "可爱", "面容", "长相", "甜美", "大眼睛", "五官"];
    const overlaps = faceKeywords.filter(k => body.includes(k));
    if (overlaps.length > 0) {
      warnings.push(`【人物身材】中包含面容描述词"${overlaps.join("、")}"，建议移到【人物面部】`);
    }
  }

  return warnings;
};


