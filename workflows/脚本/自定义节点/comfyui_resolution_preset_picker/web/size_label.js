import { app } from "../../scripts/app.js";

// 在 ResolutionSizer 节点底部实时画出「当前三个下拉会出多大」。
// 面积 = 原生像素量 × 倍率²，标题里写死数字会跟下拉脱节，所以只在这里显示。
const ASPECT = {
  "1:1 (Square)": [1, 1],
  "2:3 (Portrait Photo)": [2, 3],
  "3:2 (Landscape Photo)": [3, 2],
  "3:4 (Portrait Standard)": [3, 4],
  "4:3 (Standard)": [4, 3],
  "9:16 (Portrait Widescreen)": [9, 16],
  "16:9 (Widescreen)": [16, 9],
  "21:9 (Cinematic)": [21, 9],
};
const SCALE = {
  "0.25x": 0.25, "0.5x": 0.5, "0.75x": 0.75,
  "1.0x": 1.0, "1.25x": 1.25, "1.5x": 1.5, "2.0x": 2.0,
};

function computeSize(node) {
  const get = (n) => node.widgets?.find((x) => x.name === n);
  const w = get("aspect_ratio");
  const base = get("base_megapixels");
  const q = get("quality");
  const k = get("multiple");
  if (!w || !base || !q || !k) return null;
  const ab = ASPECT[w.value];
  if (!ab) return null;
  const scale = SCALE[q.value] ?? 1.0;
  const mp = Number(base.value) * scale * scale;
  if (!isFinite(mp) || mp <= 0) return null;
  const mult = Math.max(1, Number(k.value) || 8);
  const width = Math.sqrt(mp * 1024 * 1024 * (ab[0] / ab[1]));
  const height = (width * ab[1]) / ab[0];
  const r = (v) => Math.max(mult, Math.round(v / mult) * mult);
  return [r(width), r(height)];
}

app.registerExtension({
  name: "rpp.ResolutionSizer.sizeLabel",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== "ResolutionSizer") return;
    const onDraw = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function (ctx) {
      const r = onDraw?.apply(this, arguments);
      if (this.flags?.collapsed) return r;
      const size = computeSize(this);
      if (!size) return r;
      ctx.save();
      ctx.font = "12px sans-serif";
      ctx.textAlign = "right";
      ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR ?? "#bbb";
      ctx.fillText("→ " + size[0] + " × " + size[1], this.size[0] - 10, this.size[1] - 8);
      ctx.restore();
      return r;
    };
  },
});
