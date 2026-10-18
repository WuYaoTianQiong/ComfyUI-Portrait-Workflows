// store.js - 查询参数与列表状态的单一构造器（B4 第一步）
//
// 背景：画廊的筛选参数原本在三个地方各自拼装
//   1) history.js 的 _loadHistoryPage
//   2) gallery.js 的"全选全部"
//   3) index.html 里 HTMX 的 hx-vals
// 已经因此出现过"全选丢失分类/标签，批量删除误伤范围外图片"的问题。
// 这里先把参数拼装收成一个入口；后续 store 化时再把状态本身搬进来。
//
// 用法：
//   PBQuery.galleryUrl("/api/history")                       // 当前画廊筛选 + 分页
//   PBQuery.galleryUrl("/api/history/ids", {}, {paging:false})
//   PBQuery.gallery({ page: 1 })                             // 覆盖个别字段

window.PBQuery = (function () {
  function readGalleryState() {
    return {
      sort: window._gallerySort || "newest",
      favorite: window._galleryFilter === "favorite" ? "1" : "",
      search: window._gallerySearch || "",
      category_id: window._galleryCategoryId || "",
      tag_ids: (window._galleryTagIds || []).join(","),
      source: window._gallerySource || "",
      date: window._galleryDate || "",
      model: window._galleryModel || "",
      orientation: window._galleryOrientation || "",
    };
  }

  /**
   * 构造画廊查询参数。
   * @param {object} overrides 覆盖个别字段
   * @param {{paging?: boolean}} opts paging=false 时不带 page/page_size
   */
  function gallery(overrides, opts) {
    const includePaging = !opts || opts.paging !== false;
    const state = readGalleryState();
    if (includePaging) {
      state.page = window._galleryPage || 1;
      state.page_size = window._galleryPageSize || 50;
    }
    Object.assign(state, overrides || {});

    const params = new URLSearchParams();
    Object.keys(state).forEach(function (key) {
      const value = state[key];
      if (value === "" || value === null || value === undefined) return;
      params.set(key, value);
    });
    return params;
  }

  function galleryUrl(path, overrides, opts) {
    const qs = gallery(overrides, opts).toString();
    return qs ? path + "?" + qs : path;
  }

  return { gallery: gallery, galleryUrl: galleryUrl };
})();
