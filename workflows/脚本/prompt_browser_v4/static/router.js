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

window.routeHistory = function(params) {
  if (params && params.id) {
    const historyId = parseInt(params.id);
    const checkAndOpen = () => {
      const item = window._historyItems.find(it => it.id === historyId);
      if (item) {
        window._lightboxItems = window._historyItems;
        window._lightboxIndex = window._historyItems.findIndex(it => it.id === historyId);
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
  
  if (path === '/' || path === '/gallery') {
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

window.updateRoute = function() {
  let url = '/gallery';
  
  if (window._compareMode === 'single') {
    const item = window._lightboxItems[window._lightboxIndex];
    if (item) {
      url = `/history/${item.id}`;
    }
  } else if (window.UiState.get('activeTab', 'galleryTab') === 'promptTab' && window.selectedId) {
    url = `/prompt/${window.selectedId}`;
  } else if (window.UiState.get('activeTab', 'galleryTab') === 'promptTab') {
    url = '/prompt';
  } else if (window.UiState.get('activeTab', 'galleryTab') === 'composerTab') {
    url = '/composer';
  }
  
  if (window.location.pathname !== url && !window._suppressRouteUpdate) {
    console.log(`[路由] pushState: ${url}  ←  ${window.location.pathname}`);
    history.pushState(null, '', url);
  }
};
