<script setup lang="ts">
import { reactive, ref, watch } from 'vue'

import { apiPost } from '../api/client'
import { useToast } from '../composables/useToast'
import Modal from './Modal.vue'

/**
 * 新建提示词。
 *
 * 旧版提示词页有「＋ 新建」，重构成 Vue 时漏了 —— 只能靠导入 JSON 造数据。
 * 这里恢复最小可用表单：正文、负面、标签、备注与四个采样参数。
 */
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'created', id: number): void }>()

const toast = useToast()
const saving = ref(false)

const blank = () => ({
  name: '',
  prompt: '',
  negative_prompt: '',
  tags: '',
  note: '',
  steps: '' as string | number,
  cfg_scale: '' as string | number,
  sampler: '',
  seed: '' as string | number,
})
const form = reactive(blank())

watch(
  () => props.open,
  (open) => {
    if (open) Object.assign(form, blank())
  },
)

function numberOrNull(v: string | number): number | null {
  if (v === '' || v === null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

async function submit() {
  if (!form.prompt.trim()) {
    toast.error('正向提示词不能为空')
    return
  }
  saving.value = true
  try {
    const result = await apiPost<{ success: boolean; id: number }>('/api/prompts', {
      name: form.name.trim(),
      prompt: form.prompt,
      negative_prompt: form.negative_prompt,
      tags: form.tags,
      note: form.note,
      steps: numberOrNull(form.steps),
      cfg_scale: numberOrNull(form.cfg_scale),
      sampler: form.sampler,
      seed: numberOrNull(form.seed),
    })
    toast.success('已新建提示词')
    if (result?.id) emit('created', result.id)
    emit('close')
  } catch (e) {
    toast.error(`新建失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Modal :open="open" title="新建提示词" width="min(720px, 92vw)" @close="emit('close')">
    <div class="form">
      <label class="field">
        <span>名称</span>
        <input v-model="form.name" placeholder="方便识别的名称，如：冰品店打卡" />
      </label>

      <label class="field">
        <span>正向提示词</span>
        <textarea v-model="form.prompt" rows="10" spellcheck="false" placeholder="提示词内容…" />
      </label>

      <label class="field">
        <span>负面提示词</span>
        <textarea v-model="form.negative_prompt" rows="2" spellcheck="false" placeholder="可留空" />
      </label>

      <label class="field">
        <span>标签（逗号分隔）</span>
        <input v-model="form.tags" placeholder="女性, 卧室, 连衣裙" />
      </label>

      <div class="grid">
        <label class="field">
          <span>步数</span>
          <input v-model="form.steps" type="number" min="1" placeholder="30" />
        </label>
        <label class="field">
          <span>CFG</span>
          <input v-model="form.cfg_scale" type="number" step="0.1" placeholder="4.0" />
        </label>
        <label class="field">
          <span>采样器</span>
          <input v-model="form.sampler" placeholder="euler" />
        </label>
        <label class="field">
          <span>种子</span>
          <input v-model="form.seed" type="number" min="0" placeholder="0" />
        </label>
      </div>

      <label class="field">
        <span>备注</span>
        <input v-model="form.note" placeholder="可留空" />
      </label>
    </div>

    <template #footer>
      <span class="spacer" />
      <button class="btn btn-sm" @click="emit('close')">取消</button>
      <button class="btn btn-sm primary" :disabled="saving || !form.prompt.trim()" @click="submit">
        {{ saving ? '保存中…' : '保存' }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.field input,
.field textarea {
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.field textarea {
  resize: vertical;
}

.field input:focus,
.field textarea:focus {
  border-color: var(--primary);
}

.grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--gap-sm);
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
}
</style>
