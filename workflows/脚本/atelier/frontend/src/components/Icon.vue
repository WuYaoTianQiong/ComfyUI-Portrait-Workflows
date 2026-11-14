<script setup lang="ts">
/**
 * 全站唯一线性图标入口（unslop 体检批次 1，2026-11-14）。
 *
 * 尺寸 /  stroke / 颜色只在这里定：16px、1.5 stroke、currentColor 随文字角色色。
 * 单色文字符号（✓ ✕ ★ ☆ ♥ ✎ ☰）属排版符号，不走这里。
 */
import {
  ArrowUp,
  Ban,
  BrushCleaning,
  ClipboardList,
  Code2,
  Crosshair,
  Dices,
  Download,
  Eraser,
  Eye,
  EyeOff,
  FlaskConical,
  Folder,
  FolderOpen,
  FolderUp,
  Hand,
  Library,
  Link2,
  Lock,
  LockOpen,
  Paintbrush,
  Pin,
  Play,
  RectangleHorizontal,
  RectangleVertical,
  RefreshCw,
  Save,
  Trash2,
  Unlink,
  Wand2,
  Zap,
} from 'lucide-vue-next'

const ICONS = {
  'arrow-up': ArrowUp,
  ban: Ban,
  'brush-cleaning': BrushCleaning,
  'clipboard-list': ClipboardList,
  'code-2': Code2,
  crosshair: Crosshair,
  dices: Dices,
  download: Download,
  eraser: Eraser,
  eye: Eye,
  'eye-off': EyeOff,
  'flask-conical': FlaskConical,
  folder: Folder,
  'folder-open': FolderOpen,
  'folder-up': FolderUp,
  hand: Hand,
  library: Library,
  'link-2': Link2,
  lock: Lock,
  'lock-open': LockOpen,
  paintbrush: Paintbrush,
  pin: Pin,
  play: Play,
  'rectangle-horizontal': RectangleHorizontal,
  'rectangle-vertical': RectangleVertical,
  'refresh-cw': RefreshCw,
  save: Save,
  'trash-2': Trash2,
  unlink: Unlink,
  'wand-2': Wand2,
  zap: Zap,
} as const

export type IconName = keyof typeof ICONS

withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 16 })
</script>

<template>
  <component
    :is="ICONS[name]"
    :size="size"
    :stroke-width="1.5"
    class="ui-icon"
    aria-hidden="true"
  />
</template>

<style scoped>
.ui-icon {
  flex: none;
  vertical-align: -2px;
}
</style>