// imageViewer.js - 图片查看器模块（简化版processFromLightbox）
// 依赖：utils.js, gallery.js, history.js

// -------------------------------------------------------------------
// 图片处理（超分/重绘等）- 使用通用withLoading
// -------------------------------------------------------------------

window.processFromLightbox = async function() {
  const item = window._lightboxItems[window._lightboxIndex];
  if (!item) return;

  const workflowPath = window.currentWorkflowPath();
  if (!workflowPath) {
    window.showToast('请先选择工作流', 'error');
    return;
  }

  const processBtn = document.getElementById('lightboxProcessBtn');

  await window.withLoading(
    'processFromLightbox',
    async () => {
      const body = {
        workflow_path: workflowPath,
        ...window.workflowExtraBody(),
        orientation: window.currentOrientation,
        quality: window.getQuality(),
      };

      const data = await window.api(`/api/history/${item.id}/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (data.job_id) window.trackJob(data.job_id);
      return data;
    },
    {
      loadingText: '正在提交处理任务...',
      successText: '已提交处理任务',
      errorPrefix: '处理失败: ',
      loadingBtn: processBtn,
      loadingBtnText: '⏳',
    }
  );
};
