<script setup lang="ts">
import { ref, watch } from 'vue'

import { apiPost } from '../api/client'
import { useGenerate } from '../composables/useGenerate'
import { useSettings } from '../composables/useSettings'
import { useToast } from '../composables/useToast'
import Modal from './Modal.vue'

/**
 * 改文本跑图：不改动提示词库，直接拿当前文本去出图。
 *
 * 用途是"临时试一版" —— 调提示词时不想污染库里的正式版本。
 * `source_prompt_id` 带上当前提示词 id，出图仍然会关联回这条提示词，
 * 只是提示词**文本**保持原样。
 */
const props = defineProps<{
  open: boolean
  prompt: string
  negativePrompt: string
  promptId: number | null
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const { workflowPath, quality, orientation } = useSettings()
const { track } = useGenerate()
const toast = useToast()

const text = ref('')
const negative = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open) return
    // 每次打开都从当前提示词重置，避免上一轮的试改残留
    text.value = props.prompt
    negative.value = props.negativePrompt
  },
)

const running = ref(false)

async function submit() {
  if (!text.value.trim()) {
    toast.error('提示词不能为空')
    return
  }
  if (!workflowPath.value) {
    toast.error('请先选择工作流')
    return
  }
  running.value = true
  try {
    const result = await apiPost<{ success: boolean; job_id: number }>('/api/run_text', {
      prompt: text.value,
      negative_prompt: negative.value,
      workflow_path: workflowPath.value,
      orientation: orientation.value,
      quality: quality.value,
      seed: 0,
      source_prompt_id: props.promptId ?? 0,
    })
    track(result.job_id)
    toast.success('已提交 —— 这次的文本改动不会写回提示词库')
    emit('close')
  } catch (e) {
    toast.error(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    running.value = false
  }
}
</script>

<template>
  <Modal
    :open="open"
    title="改文本跑图（不写回提示词库）"
    width="min(720px, 92vw)"
    @close="emit('close')"
  >
    <div class="body">
      <label class="field">
        <span>正向提示词</span>
        <textarea v-model="text" rows="8" spellcheck="false" />
      </label>
      <label class="field">
        <span>负向提示词</span>
        <textarea v-model="negative" rows="3" spellcheck="false" />
      </label>
      <p class="hint">
        出图仍会关联回当前提示词，但**提示词文本保持原样** —— 想保留这次改动请回详情页点「保存」。
      </p>
    </div>

    <template #footer>
      <span class="spacer" />
      <button class="btn btn-sm" @click="emit('close')">取消</button>
      <button class="btn btn-sm primary" :disabled="running" @click="submit">
        {{ running ? '提交中…' : '跑这张' }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.body {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--fs-sm);
}

.field textarea {
  width: 100%;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
  resize: vertical;
}

.field textarea:focus {
  border-color: var(--primary);
}

.hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  line-height: 1.6;
}

.spacer {
  flex: 1;
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.btn.primary:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
