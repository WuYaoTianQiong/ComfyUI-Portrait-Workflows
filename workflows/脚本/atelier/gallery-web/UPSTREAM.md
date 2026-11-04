# 上游来源与升级说明

本目录是从上游仓库接管（vendor）进来的 React 工作台，由 atelier 在 `/ref-web` 子路径下托管。
上游原件保持只读，所有改造只发生在本目录的副本上。

## 来源

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/anhao/ai-pose-gallery-zh |
| pin 的 commit | `a6c02596ce105c5f17a65d9fc54914cd6742963b` |
| 上游版本 | 2.0.0 |
| 上次同步日期 | 2026-11-04 |
| 本机只读副本 | `workflows/ai-pose-gallery-zh/`（junction 指向上游，不入库） |

接管时已排除：`data/`、`img/`、`thumbs/`（1.1GB 素材只读外挂）、`node_modules/`、`dist/`（本地构建）、
`functions/`、`worker.ts`、`wrangler.jsonc`（Cloudflare 部署，本机不用）。

## 本目录的改造

- `src/main.tsx`：路由 `basepath` 取自 `import.meta.env.BASE_URL`，构建时必须用 `--base=/ref-web/`。
- `src/services/aiGenerator.ts`：只保留本地 ComfyUI 协议，Gemini / GPT / Qwen / Doubao 分支与相关类型已删除。
- `src/routes/settings.tsx`：只保留 ComfyUI 地址、API Key 与连接测试。
- `src/routes/guide.tsx`：使用说明与免责声明按"仅本地 ComfyUI"口径改写。
- `vite.config.ts`：删除仅供云端厂商接口使用的 `/api/proxy` 转发中间件；只保留本地素材挂载与 `/comfy` 反代。
- `index.html`：移除外站 canonical / sitemap / og / JSON-LD 与第三方统计脚本，标题与描述改成"本地 ComfyUI 出图"口径；页面标记 `noindex`。
- `package.json`：新增 `build:prod`，先清空 `dist/` 再按 `/ref-web` 基路径构建。

## 构建

```powershell
cd workflows\脚本\atelier\gallery-web
pnpm install --frozen-lockfile --offline   # 首次或依赖变更；本机 pnpm store 已有上游包
pnpm run build:prod                        # = node scripts/clean-dist.mjs && vite build --base=/ref-web/
```

`build:prod` 会先执行 `scripts/clean-dist.mjs` 清空 `dist/`。不要依赖 Vite 的 `emptyOutDir`：
在部分受管控环境里 `fs.rmSync` 会被拦截成 no-op，旧 hash 产物会与新产物一起留在 `dist/`，
连续构建后从 25 个文件堆积到 36 个。`clean-dist.mjs` 用 `unlinkSync` / `rmdirSync` 递归删除，可稳定复现干净产物。

Git Bash 下必须禁用 MSYS 路径转换，否则 `--base=/ref-web/` 会被改写成 Git 安装路径：

```bash
MSYS_NO_PATHCONV=1 pnpm run build:prod
```

构建后检查 `dist/index.html` 中的资源前缀是否为 `/ref-web/assets/...`。

## 产物入库

`dist/` 必须随源码一起提交（运行时零 Node 依赖，atelier 不需要 Node）。
修改 `src/` 后忘记重新 `build:prod`，线上仍是旧产物。
`node_modules/` 已由仓库根 `.gitignore` 忽略，禁止提交。

## 升级合并步骤

1. 在只读上游目录 `git fetch` 并查看目标 commit 的差异：
   `git -C workflows/ai-pose-gallery-zh fetch` → `git -C workflows/ai-pose-gallery-zh diff <旧SHA> <新SHA> -- src/`
2. 将差异手工合并到本目录 `src/`，保留上表中的本地改造（尤其 `aiGenerator.ts` 的协议裁剪与 `main.tsx` 的 basepath）。
3. 跑 `pnpm run build:prod`，确认 `dist` 产物更新。
4. 更新本文件的 pin SHA 与同步日期，与源码、`dist/` 一起提交。

## 升级后必跑的三条冒烟

- `/ref-web/poses`、`/ref-web/costumes`、`/ref-web/portraits` 三库能加载数据与缩略图；
- `/ref-web/studio` 能连上本地 ComfyUI（同源 `/comfy`），并能提交一次生成；
- `/ref-web` 的深链接刷新不 404（`/ref-web/studio`、`/ref-web/settings` 直接访问）。