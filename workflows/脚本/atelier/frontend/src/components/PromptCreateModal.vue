<script setup lang="ts">
import { reactive, ref, watch } from 'vue'

import { apiPost } from '../api/client'
import { useToast } from '../composables/useToast'
import Modal from './Modal.vue'
import { FRAGMENT_TYPES } from '../constants'

/**
 * 新建提示词 / 碎片。
 *
 * 两种模式：
 * · 完整提示词：正文、负面、标签、备注与四个采样参数
 * · 碎片：选类型 + 填内容，自动拼成 `【类型】\n内容` 存入（α 之后碎片 = 单块 prompt）
 */
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'created', id: number): void }>()

const toast = useToast()
const saving = ref(false)
const mode = ref<'full' | 'fragment'>('full')

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
const fragType = ref<string>('人物面部')
const fragContent = ref('')

watch(
  () => props.open,
  (open) => {
    if (open) {
      Object.assign(form, blank())
      mode.value = 'full'
      fragType.value = '人物面部'
      fragContent.value = ''
    }
  },
)

function numberOrNull(v: string | number): number | null {
  if (v === '' || v === null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

async function submit() {
  const isFragment = mode.value === 'fragment'
  const promptText = isFragment
    ? `【${fragType.value}】\n${fragContent.value.trim()}`
    : form.prompt
  if (!promptText.trim()) {
    toast.error(isFragment ? '碎片内容不能为空' : '正向提示词不能为空')
    return
  }
  saving.value = true
  try {
    const result = await apiPost<{ success: boolean; id: number }>('/api/prompts', {
      name: form.name.trim(),
      prompt: promptText,
      negative_prompt: isFragment ? '' : form.negative_prompt,
      tags: form.tags,
      note: isFragment ? '' : form.note,
      steps: isFragment ? null : numberOrNull(form.steps),
      cfg_scale: isFragment ? null : numberOrNull(form.cfg_scale),
      sampler: isFragment ? '' : form.sampler,
      seed: isFragment ? null : numberOrNull(form.seed),
    })
    toast.success(isFragment ? '已新建碎片' : '已新建提示词')
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
  <Modal :open="open" :title="mode === 'fragment' ? '新建碎片' : '新建提示词'" width="min(720px, 92vw)" @close="emit('close')">
    <div class="form">
      <div class="mode-switch">
        <button class="btn btn-sm" :class="{ active: mode === 'full' }" @click="mode = 'full'">完整提示词</button>
        <button class="btn btn-sm" :class="{ active: mode === 'fragment' }" title="只含一个【类型】块的提示词，可被组合器当碎片用" @click="mode = 'fragment'">碎片</button>
      </div>

      <label class="field">
        <span>名称</span>
        <input v-model="form.name" placeholder="方便识别的名称，如：冰品店打卡" />
      </label>

      <template v-if="mode === 'fragment'">
        <label class="field">
          <span>碎片类型</span>
          <select v-model="fragType">
            <option v-for="t in FRAGMENT_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>
        <label class="field">
          <span>碎片内容</span>
          <textarea v-model="fragContent" rows="6" spellcheck="false" placeholder="写一段描写，会自动存成「【类型】内容」格式…" />
        </label>
      </template>

      <template v-else>
        <label class="field">
          <span>正向提示词</span>
          <textarea v-model="form.prompt" rows="10" spellcheck="false" placeholder="提示词内容…" />
        </label>

        <label class="field">
          <span>负面提示词</span>
          <textarea v-model="form.negative_prompt" rows="2" spellcheck="false" placeholder="可留空" />
          <small class="field-hint">
            负向是否生效取决于出图工作流：只有 ZIT 或 CFG&gt;1 的链路会使用；其余线路只归档。
          </small>
        </label>
      </template>

      <label class="field">
        <span>标签（逗号分隔）</span>
        <input v-model="form.tags" placeholder="女性, 卧室, 连衣裙" />
      </label>

      <div v-if="mode === 'full'" class="grid">
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

      <label v-if="mode === 'full'" class="field">
        <span>备注</span>
        <input v-model="form.note" placeholder="可留空" />
      </label>
    </div>

    <template #footer>
      <span class="spacer" />
      <button class="btn btn-sm" @click="emit('close')">取消</button>
      <button
        class="btn btn-sm primary"
        :disabled="saving || (mode === 'fragment' ? !fragContent.trim() : !form.prompt.trim())"
        @click="submit"
      >
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

.mode-switch {
  display: flex;
  gap: var(--gap-xs);
}

.mode-switch .btn.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.field-hint {
  font-size: var(--fs-xs);
  line-height: 1.5;
  color: var(--muted);
}

.field input,
.field textarea,
.field select {
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
