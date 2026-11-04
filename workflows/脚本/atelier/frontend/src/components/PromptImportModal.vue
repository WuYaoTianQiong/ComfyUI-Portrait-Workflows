<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { apiPost } from '../api/client'
import { useToast } from '../composables/useToast'
import { fragmentsInOrder, renderSegments, smartSegmentText } from '../utils/segmentation'
import Modal from './Modal.vue'

/**
 * 智能导入：粘贴多条提示词 → 自动按空行分条、按关键词分段 → 预览确认后入库。
 *
 * 旧版 `static/prompt.js` 的 parseImportText 就是这套规则，重构时丢了。
 * 与旧版保持一致：
 * · 以空行分隔多条；
 * · `名称:` / `负面:` 行单独提取；
 * · 正文用智能分段整理成【类型】结构。
 */
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'imported'): void }>()

const toast = useToast()
const raw = ref('')
const importing = ref(false)

interface ImportItem {
  name: string
  prompt: string
  negative_prompt: string
  selected: boolean
}

/** 解析中间态：正文还没渲染成 `【类型】` 文本 */
interface ImportDraft {
  name: string
  body: string
  negative_prompt: string
  selected: boolean
}
const items = ref<ImportItem[]>([])

watch(
  () => props.open,
  (open) => {
    if (open) {
      raw.value = ''
      items.value = []
    }
  },
)

const selectedCount = computed(() => items.value.filter((i) => i.selected).length)

async function parse() {
  const blocks = raw.value
    .split(/\n\s*\n+/)
    .map((b) => b.trim())
    .filter(Boolean)
  if (!blocks.length) {
    toast.error('没有可解析的内容')
    return
  }

  const drafts: ImportDraft[] = []
  const bodies: string[] = []
  for (const block of blocks) {
    const lines = block.split(/\r?\n/)
    let name = ''
    let bodyLines = lines
    const nameMatch = (lines[0] ?? '').match(/^(名称|name|标题)\s*[:：]\s*(.+)$/i)
    if (nameMatch) {
      name = nameMatch[2].trim()
      bodyLines = lines.slice(1)
    }

    let negative = ''
    const posLines: string[] = []
    for (const line of bodyLines) {
      const negMatch = line.match(/^(negative|负面|反向)\s*[:：]\s*(.*)$/i)
      if (negMatch) {
        negative = negative ? `${negative}, ${negMatch[2].trim()}` : negMatch[2].trim()
      } else {
        posLines.push(line)
      }
    }

    const body = posLines.join('\n').trim()
    bodies.push(body)
    drafts.push({
      name: name || `未命名 ${drafts.length + 1}`,
      body,
      negative_prompt: negative,
      selected: true,
    })
  }

  // 渲染统一走后端（`【类型】` 格式只有一份实现），一次往返渲染全部条目
  const groups = bodies.map((body) => fragmentsInOrder(smartSegmentText(body)))
  const rendered = await renderSegments(groups)

  items.value = drafts.map((draft, i) => ({
    name: draft.name,
    // 没分出类型时原样保留正文，总比把内容弄丢强
    prompt: rendered[i] || draft.body,
    negative_prompt: draft.negative_prompt,
    selected: draft.selected,
  }))
  toast.success(`解析完成 ${items.value.length} 条`)
}

async function submit() {
  const selected = items.value.filter((i) => i.selected)
  if (!selected.length) {
    toast.error('请至少选择一条')
    return
  }
  importing.value = true
  try {
    const result = await apiPost<{ success: boolean; imported: number; message: string }>(
      '/api/prompts/import',
      {
        prompts: selected.map((i) => ({
          name: i.name,
          prompt: i.prompt,
          negative_prompt: i.negative_prompt,
        })),
      },
    )
    toast.success(result?.message || `已导入 ${result?.imported ?? 0} 条`)
    emit('imported')
    emit('close')
  } catch (e) {
    toast.error(`导入失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <Modal :open="open" title="智能导入" width="min(860px, 94vw)" height="86vh" @close="emit('close')">
    <div class="import-body">
      <label class="field">
        <span>粘贴多条提示词（空行分隔；支持 `名称:` 与 `负面:` 行）</span>
        <textarea
          v-model="raw"
          rows="7"
          spellcheck="false"
          placeholder="名称: 示例一&#10;黑色长发，白色连衣裙，站在窗边&#10;负面: 低质量, 变形&#10;&#10;名称: 示例二&#10;…"
        />
      </label>

      <div class="parse-row">
        <button class="btn btn-sm" :disabled="!raw.trim()" @click="parse">解析</button>
        <span class="muted">共解析 {{ items.length }} 条，已选 {{ selectedCount }} 条</span>
        <span class="spacer" />
        <button
          class="btn btn-sm"
          :disabled="!items.length"
          @click="items.forEach((i) => (i.selected = true))"
        >
          全选
        </button>
        <button
          class="btn btn-sm"
          :disabled="!items.length"
          @click="items.forEach((i) => (i.selected = false))"
        >
          取消全选
        </button>
      </div>

      <div v-if="items.length" class="preview">
        <div v-for="(item, idx) in items" :key="idx" class="import-card">
          <div class="card-head">
            <input v-model="item.selected" type="checkbox" />
            <input v-model="item.name" class="name-input" />
            <span class="frag-count">
              {{ (item.prompt.match(/【[^】]+】/g) || []).length }} 碎片
            </span>
          </div>
          <pre class="card-body">{{ item.prompt }}</pre>
          <div v-if="item.negative_prompt" class="card-neg">负面：{{ item.negative_prompt }}</div>
        </div>
      </div>
      <div v-else class="empty-tip">粘贴内容后点「解析」，这里会出现预览</div>
    </div>

    <template #footer>
      <span class="spacer" />
      <button class="btn btn-sm" @click="emit('close')">取消</button>
      <button
        class="btn btn-sm primary"
        :disabled="importing || !selectedCount"
        @click="submit"
      >
        {{ importing ? '导入中…' : `导入选中 ${selectedCount} 条` }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.import-body {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
  min-height: 0;
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--fs-sm);
  color: var(--muted);
}

.field textarea {
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

.parse-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
}

.muted {
  color: var(--muted);
  font-size: var(--fs-sm);
}

.spacer {
  flex: 1;
}

.preview {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--gap-sm);
  align-content: start;
}

.import-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  padding: var(--gap-sm);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.card-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.name-input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text);
  font: inherit;
  font-weight: 600;
  padding: 2px 4px;
}

.name-input:hover,
.name-input:focus {
  border-color: var(--border);
  background: var(--panel);
}

.frag-count {
  font-size: var(--fs-xs);
  color: var(--muted);
  white-space: nowrap;
}

.card-body {
  margin: 0;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 140px;
  overflow: hidden;
}

.card-neg {
  font-size: var(--fs-xs);
  color: var(--danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-tip {
  color: var(--muted);
  text-align: center;
  padding: 40px;
  font-size: var(--fs-sm);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.btn.primary:disabled {
  opacity: 0.4;
}
</style>
