// router.js - 前端路由模块
// 依赖：utils.js, ui.js

// -------------------------------------------------------------------
// 前端路由（纯手动 History API，无第三方依赖）
// -------------------------------------------------------------------

window._suppressRouteUpdate = false;

// 路由处理函数
window.routeGallery = function() { window.switchTabByRoute('galleryTab'); };

window.routeComposer = function() { window.switchTabByRoute('composerTab'); };

window.routePrompt = function(params) {
  window._suppressRouteUpdate = true;
  window.switchTabByRoute('promptTab');
  window._suppressRouteUpdate = false;
  if (params && params.id) {
    const promptId = parseInt(params.id);
    if (promptId && window.allPrompts.some(p => p.id === promptId)) {
      window.selectPrompt(promptId, true, false, false, true);
    }
  }
};

window.routeStats = function() { window.switchTabByRoute('statsTab'); window.loadStats(); };

window.routeHistory = function(params) {
  if (params && params.id) {
    const historyId = parseInt(params.id);
    const checkAndOpen = () => {
      const src = window._galleryAllItems || window._historyItems;
      const item = src.find(it => it.id === historyId);
      if (item) {
        window._lightboxItems = src;
        window._lightboxIndex = src.findIndex(it => it.id === historyId);
        window._compareMode = 'single';
        window.openUnifiedImageModal();
      } else if (window._historyItems.length === 0) {
        setTimeout(checkAndOpen, 500);
      }
    };
    checkAndOpen();
  }
};

// 手动路由解析器
window.handleRoute = function(path) {
  if (window._compareMode === 'single' && !path.startsWith('/history/')) {
    window.closeCompareModal();
  }
  
  if (path === '/') {
    window.routePrompt({});
  } else if (path === '/gallery') {
    window.routeGallery();
  } else if (path.startsWith('/history/')) {
    const match = path.match(/\/history\/(\d+)/);
    if (match) window.routeHistory({ id: parseInt(match[1]) });
  } else if (path.startsWith('/prompt/')) {
    const match = path.match(/\/prompt\/(\d+)/);
    window.routePrompt(match ? { id: parseInt(match[1]) } : {});
  } else if (path === '/prompt') {
    window.routePrompt({});
  } else if (path === '/composer') {
    window.routeComposer();
  } else if (path === '/faceswap') {
    window.routeFaceswap();
  } else if (path === '/stats') {
    window.routeStats();
  } else {
    window.routeGallery();
  }
};

// 监听浏览器后退/前进按钮
window.addEventListener('popstate', () => {
  window._suppressRouteUpdate = true;
  window.handleRoute(window.location.pathname);
  window._suppressRouteUpdate = false;
});

window.switchTabByRoute = function(tabId) {
  const tabBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  if (tabBtn) {
    window.switchTab(tabId, tabBtn);
  }
};

window.updateRoute = function(useReplace = false) {
  let url = '/gallery';
  
  if (window._compareMode === 'single') {
    const item = window._lightboxItems[window._lightboxIndex];
    if (item) {
      url = `/history/${item.id}`;
    }
  } else {
    const activeTab = window.UiState.get('activeTab', 'galleryTab');
    if (activeTab === 'promptTab' && window.selectedId) {
      url = `/prompt/${window.selectedId}`;
    } else if (activeTab === 'promptTab') {
      url = '/prompt';
    } else if (activeTab === 'composerTab') {
      url = '/composer';
    } else if (activeTab === 'faceswapTab') {
      url = '/faceswap';
    } else if (activeTab === 'statsTab') {
      url = '/stats';
    }
    // galleryTab → url 保持 '/gallery'
  }
  
  if (window.location.pathname !== url && !window._suppressRouteUpdate) {
    console.log(`[路由] ${useReplace ? 'replaceState' : 'pushState'}: ${url}  ←  ${window.location.pathname}`);
    if (useReplace) {
      history.replaceState(null, '', url);
    } else {
      history.pushState(null, '', url);
    }
  }
};
