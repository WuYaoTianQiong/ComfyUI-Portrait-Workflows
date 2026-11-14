<script setup lang="ts">
import Modal from './Modal.vue'

interface FragmentDetail {
  type: string
  content: string
  source: 'prompt' | 'custom'
  promptId: number | null
  promptName: string
  dupCount: number
}

/**
 * 碎片全文弹层：卡片只能显示 3 行，双击这里看完整内容与来源。
 *
 * α 之后碎片统一从 prompts 解析（单块 prompt 就是碎片），编辑一律跳提示词页。
 * 这里**不做就地编辑**：同一段内容可能散落在多条提示词里（见 dupCount），
 * 就地改会让"已选"和"源"静默分叉。
 */
defineProps<{ open: boolean; fragment: FragmentDetail | null }>()
const emit = defineEmits<{
  close: []
  pick: []
  jump: [promptId: number, fragType: string]
}>()
</script>

<template>
  <Modal :open="open" :title="`碎片全文 · ${fragment?.type ?? ''}`" width="min(760px, 94vw)" @close="emit('close')">
    <div v-if="fragment" class="body">
      <pre class="frag-full">{{ fragment.content }}</pre>
      <div class="meta">
        <span class="src">
          {{ fragment.source === 'custom' ? '自定义' : '来自提示词' }}
        </span>
        <span v-if="fragment.promptName" class="name">{{ fragment.promptName }}</span>
        <span v-if="fragment.dupCount > 1" class="muted">
          同一段还出现在 {{ fragment.dupCount }} 条提示词里，改其中一条不会影响其它条
        </span>
        <span class="spacer" />
        <button
          v-if="fragment.promptId"
          class="btn btn-sm"
          title="去提示词页改这条提示词的正文（只改这一条）"
          @click="emit('jump', fragment.promptId, fragment.type)"
        >
          ✎ 编辑来源提示词
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
  color: var(--accent-link);
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
