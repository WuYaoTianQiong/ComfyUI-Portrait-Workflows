import { app } from "../../scripts/app.js";

// 在 ResolutionSizer 节点底部实时画出「当前下拉会出多大」。
// 标题里的像素是静态文字，改下拉不会跟着变，容易误读；这里按实际 widget 值算。
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

function computeSize(node) {
  const w = node.widgets?.find((x) => x.name === "aspect_ratio");
  const m = node.widgets?.find((x) => x.name === "megapixels");
  const k = node.widgets?.find((x) => x.name === "multiple");
  if (!w || !m || !k) return null;
  const ab = ASPECT[w.value];
  if (!ab) return null;
  const mult = Math.max(1, Number(k.value) || 8);
  const mp = Number(m.value);
  if (!isFinite(mp) || mp <= 0) return null;
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
      const text = "→ " + size[0] + " × " + size[1];
      ctx.save();
      ctx.font = "12px sans-serif";
      ctx.textAlign = "right";
      ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR ?? "#bbb";
      ctx.fillText(text, this.size[0] - 10, this.size[1] - 8);
      ctx.restore();
      return r;
    };
  },
});
