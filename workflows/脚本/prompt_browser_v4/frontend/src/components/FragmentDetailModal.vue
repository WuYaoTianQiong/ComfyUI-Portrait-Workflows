<script setup lang="ts">
import Modal from './Modal.vue'

interface FragmentDetail {
  type: string
  content: string
  source: 'prompt' | 'library' | 'custom'
  promptId: number | null
  promptName: string
  dupCount: number
}

/** 碎片全文弹层：卡片只能显示 3 行，双击这里看完整内容与来源。 */
defineProps<{ open: boolean; fragment: FragmentDetail | null }>()
const emit = defineEmits<{ close: []; pick: []; jump: [promptId: number] }>()
</script>

<template>
  <Modal :open="open" :title="`碎片全文 · ${fragment?.type ?? ''}`" width="min(760px, 94vw)" @close="emit('close')">
    <div v-if="fragment" class="body">
      <pre class="frag-full">{{ fragment.content }}</pre>
      <div class="meta">
        <span class="src">
          {{ fragment.source === 'library' ? '碎片库' : fragment.source === 'custom' ? '自定义' : '来自提示词' }}
        </span>
        <span v-if="fragment.promptName" class="name">{{ fragment.promptName }}</span>
        <span v-if="fragment.dupCount > 1" class="muted">出现在 {{ fragment.dupCount }} 条提示词里</span>
        <span class="spacer" />
        <button
          v-if="fragment.promptId"
          class="btn btn-sm"
          title="跳到这条来源提示词"
          @click="emit('jump', fragment.promptId)"
        >
          ↗ 来源提示词
        </button>
      </div>
    </div>

    <template #footer>
      <span class="spacer" />
      <button class="btn btn-sm" @click="emit('close')">关闭</button>
      <button class="btn btn-sm primary" @click="emit('pick')">
        填入「{{ fragment?.type }}」列
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.body {
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.frag-full {
  margin: 0;
  max-height: 52vh;
  overflow-y: auto;
  white-space: pre-wrap;
  font-size: var(--fs-sm);
  line-height: 1.6;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
}

.meta {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
  color: var(--muted);
  flex-wrap: wrap;
}

.src {
  color: var(--primary);
}

.name {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.muted {
  color: var(--muted);
}

.spacer {
  flex: 1;
}
</style>
