# 上游来源与升级说明

本文件记录 atelier 曾经 vendor（接管）进来的上游前端，以及 2026-11-05
「参考图库 React → Vue 统一迁移」收尾后的状态。

## 已移除的 React 子应用

原 `脚本/atelier/gallery-web/`（上游 `ai-pose-gallery-zh` 的 React 工作台副本）
已于 **2026-11-05** 删除（施工手册阶段 4.3），原因：

- 参考图库 `/reference` 已由纯 Vue 实现全量承接（阶段 1–3 验收通过）；
- iframe 承载分支与开关（`?shell=`、`pb.reference_shell_v1/v2`）同步删除；
- 后端 `/ref-web` 静态挂载移除，该前缀改由 301/302 重定向到 `/reference?tab=...`。

React 源码、`dist/` 产物、构建配置（`vite.config.ts`、`package.json`、
`pnpm-lock.yaml`、`tsconfig*.json`、`scripts/clean-dist.mjs`、`components.json`）
均不再存在。Git 历史仍可追溯（`git log -- 脚本/atelier/gallery-web`）。

## 上游来源（历史记录）

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/anhao/ai-pose-gallery-zh |
| pin 的 commit | `a6c02596ce105c5f17a65d9fc54914cd6742963b` |
| 上游版本 | 2.0.0 |
| 上次同步日期 | 2026-11-04（移除前最后一次同步） |
| 本机只读副本 | `workflows/ai-pose-gallery-zh/`（junction 指向上游，不入库） |

接管时已排除：`data/`、`img/`、`thumbs/`（1.1GB 素材只读外挂）、`node_modules/`、
`dist/`（本地构建）、`functions/`、`worker.ts`、`wrangler.jsonc`（Cloudflare 部署，本机不用）。

## 原目录的改造（历史记录）

- `src/main.tsx`：路由 `basepath` 取自 `import.meta.env.BASE_URL`，构建时用 `--base=/ref-web/`。
- `src/services/aiGenerator.ts`：只保留本地 ComfyUI 协议，Gemini / GPT / Qwen / Doubao 分支与相关类型已删除。
- `src/routes/settings.tsx`：只保留 ComfyUI 地址、API Key 与连接测试。
- `src/routes/guide.tsx`：使用说明与免责声明按「仅本地 ComfyUI」口径改写。
- `vite.config.ts`：删除仅供云端厂商接口使用的 `/api/proxy` 转发中间件；只保留本地素材挂载与 `/comfy` 反代。
- `index.html`：移除外站 canonical / sitemap / og / JSON-LD 与第三方统计脚本，标题与描述改成「本地 ComfyUI 出图」口径；页面标记 `noindex`。
- `package.json`：新增 `build:prod`，先清空 `dist/` 再按 `/ref-web` 基路径构建。

## 许可证与署名（保留义务，不得删除）

- **代码许可**：上游代码为 MIT 许可，版权行为 `Copyright (c) 2026 Anhao`。
  许可全文（含上游的「适用范围说明 / Scope」段）已迁移到
  `文档/第三方许可/ai-pose-gallery-zh/LICENSE`，与原 `gallery-web/LICENSE`
  逐字节一致（SHA-256 `7f8b59e5d91bc2c4957618b45fc063d739a26e0a30ef13b8260f115b7dec7b71`）。
  不得改写版权行或替换许可文本。
- **素材署名**：姿势 / 现实服装 / 人像素材著作权归原作者 **ギア（@giaaibusi）**；
  CharaDB 图片仅作参考、禁止再分发。完整授权边界见
  `文档/第三方许可/ai-pose-gallery-zh/NOTICE`。
- **结论**：删除 React 代码不改变版权归属；MIT 要求副本保留版权与许可声明，
  因此 `LICENSE` / `NOTICE` 永久保留在 `文档/第三方许可/ai-pose-gallery-zh/`。

## 当前形态

```text
/reference                              纯 Vue 参考图库（唯一入口）
/reference?tab=home|pose|costume|portrait|studio|settings
/ref-web, /ref-web/poses, ...           301/302 → /reference?tab=...
```

- 前端：`脚本/atelier/frontend/`（Vue 3 + Composition API），构建产物在 `脚本/atelier/web/`。
- 后端：`脚本/atelier/app/`，`/ref-web` 只保留重定向，不再有静态挂载。
- 本机只读上游目录 `workflows/ai-pose-gallery-zh/` 仍保留（素材来源），只读、不入库。