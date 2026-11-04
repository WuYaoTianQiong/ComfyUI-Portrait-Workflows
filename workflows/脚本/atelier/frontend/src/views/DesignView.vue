<script setup lang="ts">
import { ref } from 'vue'

import EmptyState from '../components/EmptyState.vue'
import Modal from '../components/Modal.vue'
import { useToast } from '../composables/useToast'

/**
 * 设计系统预览页。
 *
 * 目的不是好看，而是**让令牌与基础组件有一个可见的落点**：
 * 改 `tokens.css` 里的一个颜色，刷新这一页就能看到影响面；
 * 想知道"按钮有哪些状态""空状态长什么样"，不用去翻代码。
 */
const toast = useToast()
const demoOpen = ref(false)

const COLORS = [
  { name: '--bg', desc: '页面底色' },
  { name: '--panel', desc: '面板底色' },
  { name: '--panel-2', desc: '次级面板' },
  { name: '--panel-3', desc: '三级/悬停' },
  { name: '--border', desc: '常规边框' },
  { name: '--border-strong', desc: '强调边框' },
  { name: '--text', desc: '正文' },
  { name: '--muted', desc: '次要文字' },
  { name: '--primary', desc: '主色' },
  { name: '--primary-soft', desc: '主色浅底' },
  { name: '--success', desc: '成功' },
  { name: '--warn', desc: '警告' },
  { name: '--danger', desc: '危险' },
  { name: '--danger-soft', desc: '危险浅底' },
]

const SIZES = [
  { name: '--fs-xs', desc: '12px 辅助文字' },
  { name: '--fs-sm', desc: '13px 正文' },
  { name: '--fs-md', desc: '15px 强调' },
  { name: '--fs-lg', desc: '18px 标题' },
]

const SCALES = [
  { name: '--gap-xs', desc: '4px' },
  { name: '--gap-sm', desc: '8px' },
  { name: '--gap', desc: '12px' },
  { name: '--gap-lg', desc: '20px' },
]
</script>

<template>
  <div class="design">
    <section class="panel">
      <h3>颜色令牌</h3>
      <p class="hint">全部来自 <code>src/styles/tokens.css</code>，页面只允许用变量，不写死颜色。</p>
      <div class="swatches">
        <div v-for="c in COLORS" :key="c.name" class="swatch-item">
          <span class="swatch" :style="{ background: `var(${c.name})` }" />
          <span class="swatch-name">{{ c.name }}</span>
          <span class="swatch-desc">{{ c.desc }}</span>
        </div>
      </div>
    </section>

    <section class="panel">
      <h3>字阶</h3>
      <div class="rows">
        <div v-for="s in SIZES" :key="s.name" class="row">
          <span class="row-key">{{ s.name }}</span>
          <span class="row-desc">{{ s.desc }}</span>
          <span class="row-demo" :style="{ fontSize: `var(${s.name})` }">示例文字 Aa 123</span>
        </div>
      </div>
    </section>

    <section class="panel">
      <h3>间距与圆角</h3>
      <div class="rows">
        <div v-for="s in SCALES" :key="s.name" class="row">
          <span class="row-key">{{ s.name }}</span>
          <span class="row-desc">{{ s.desc }}</span>
          <span class="bar" :style="{ width: `var(${s.name})`, height: '14px' }" />
        </div>
      </div>
      <div class="rows">
        <div class="row">
          <span class="row-key">--radius-sm</span>
          <span class="box sm" />
          <span class="row-key">--radius</span>
          <span class="box md" />
        </div>
      </div>
    </section>

    <section class="panel">
      <h3>基础组件</h3>

      <div class="row">
        <span class="row-key">按钮</span>
        <button class="btn">默认</button>
        <button class="btn btn-sm">小号</button>
        <button class="btn primary">主要</button>
        <button class="btn danger">危险</button>
        <button class="btn" disabled>禁用</button>
      </div>

      <div class="row">
        <span class="row-key">输入</span>
        <input class="input-demo" placeholder="占位文字" />
        <select class="input-demo">
          <option>选项一</option>
          <option>选项二</option>
        </select>
        <label class="row-key check"><input type="checkbox" /> 复选</label>
      </div>

      <div class="row">
        <span class="row-key">反馈</span>
        <button class="btn btn-sm" @click="toast.info('这是一条 info 提示')">触发提示</button>
        <button class="btn btn-sm" @click="toast.success('这是一条成功提示')">成功</button>
        <button class="btn btn-sm" @click="toast.error('这是一条错误提示')">错误</button>
        <button class="btn btn-sm" @click="demoOpen = true">打开弹层</button>
      </div>

      <div class="row column">
        <span class="row-key">空状态</span>
        <EmptyState text="还没有内容" hint="这里可以放一句引导" />
      </div>
    </section>

    <Modal :open="demoOpen" title="弹层示例" @close="demoOpen = false">
      <div class="modal-demo">
        <p>Modal 提供统一的遮罩、圆角、阴影与 Esc 关闭；内容区的滚动由调用方自己决定。</p>
        <EmptyState text="示例内容" />
      </div>
      <template #footer>
        <span class="spacer" />
        <button class="btn btn-sm primary" @click="demoOpen = false">知道了</button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.design {
  height: 100%;
  overflow-y: auto;
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
}

.panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  padding: var(--gap);
}

.panel h3 {
  margin: 0 0 var(--gap-sm);
  font-size: var(--fs-sm);
  color: var(--muted);
  font-weight: 600;
}

.hint {
  margin: 0 0 var(--gap-sm);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.hint code {
  background: var(--panel-3);
  padding: 1px 4px;
  border-radius: 3px;
}

.swatches {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: var(--gap-sm);
}

.swatch-item {
  display: grid;
  grid-template-columns: 26px 1fr;
  grid-template-rows: auto auto;
  gap: 0 var(--gap-sm);
  align-items: center;
}

.swatch {
  grid-row: 1 / 3;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
}

.swatch-name {
  font-size: var(--fs-xs);
  font-family: ui-monospace, monospace;
}

.swatch-desc {
  font-size: 10px;
  color: var(--muted);
}

.rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
}

.row.column {
  flex-direction: column;
  align-items: stretch;
  gap: var(--gap-xs);
}

.row-key {
  width: 130px;
  flex: none;
  font-size: var(--fs-xs);
  font-family: ui-monospace, monospace;
  color: var(--muted);
}

.row-desc {
  width: 110px;
  flex: none;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.row-demo {
  flex: 1;
}

.bar {
  background: var(--primary);
  border-radius: 2px;
  display: inline-block;
}

.box {
  display: inline-block;
  width: 40px;
  height: 24px;
  background: var(--primary-soft);
  border: 1px solid var(--primary);
}

.box.sm {
  border-radius: var(--radius-sm);
}

.box.md {
  border-radius: var(--radius);
  width: 56px;
}

.input-demo {
  width: 180px;
}

.check {
  display: flex;
  align-items: center;
  gap: 5px;
  width: auto;
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--on-primary);
}

.btn.danger {
  border-color: var(--danger);
  color: var(--danger-text);
}

.btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.modal-demo {
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.modal-demo p {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--muted);
  line-height: 1.6;
}

.spacer {
  flex: 1;
}
</style>
