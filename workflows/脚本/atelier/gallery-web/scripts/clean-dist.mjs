import fs from 'node:fs'
import path from 'node:path'

const dist = path.resolve(import.meta.dirname, '..', 'dist')

// 不使用 fs.rmSync：部分受管控环境会把它 hook 成 no-op，导致旧 hash 产物残留。
function removeDir(dir) {
  if (!fs.existsSync(dir)) return
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const target = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      removeDir(target)
      fs.rmdirSync(target)
    } else {
      fs.unlinkSync(target)
    }
  }
}

if (fs.existsSync(dist)) {
  removeDir(dist)
  fs.rmdirSync(dist)
  console.log(`[build] 已清空 ${dist}`)
} else {
  console.log(`[build] ${dist} 不存在，跳过清空`)
}