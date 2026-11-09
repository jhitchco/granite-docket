/* Granite Docket map kit: NH town map with zoom (wheel, pinch, buttons, double-click) and drag-to-pan.
   NHMap(svg, geo, {onDraw(z), views}) -> {setView(name), zoomAt(f), focusTown(name), redraw(), townEl(name)} */
function NHMap(svg, geo, opts) {
  const NS = "http://www.w3.org/2000/svg";
  const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
  const views = Object.assign({ State: [0, 0, geo.w, geo.h] }, opts.views || {});
  let vb = views.State.slice(), raf = 0;
  const gT = el("g", { class: "towns" }, svg), gO = el("g", { class: "over" }, svg), gL = el("g", { class: "labels" }, svg);
  const paths = {};
  for (const [n, t] of Object.entries(geo.towns)) { const p = el("path", { d: t.d, class: "t", "data-town": n }, gT); el("title", {}, p).textContent = n; paths[n] = p; }
  const z = () => geo.w / vb[2];
  function draw() {
    svg.setAttribute("viewBox", vb.join(" "));
    gO.replaceChildren(); gL.replaceChildren();
    if (opts.onDraw) opts.onDraw(gO, z(), el);
    const zz = z(), fs = Math.min(9 + 1.6 * Math.log2(Math.max(zz, 1)), 15) / zz;
    for (const [n, t] of Object.entries(geo.towns)) {
      if (!(zz > 2.2 || (geo.big || []).includes(n) || (opts.labelTowns && opts.labelTowns().has(n) && zz > 1.4))) continue;
      const x = el("text", { x: t.c[0], y: t.c[1], class: "tl", "font-size": fs, "stroke-width": fs / 3.5, "text-anchor": "middle" }, gL); x.textContent = n;
    }
    if (opts.onView) opts.onView(current);
  }
  const redraw = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); };
  let current = "State";
  function setView(name) { current = name; vb = views[name].slice(); draw(); }
  function custom() { if (current !== "Custom") { current = "Custom"; } }
  function svgPt(cx, cy) { const r = svg.getBoundingClientRect(), s = Math.max(vb[2] / r.width, vb[3] / r.height); const ox = (r.width - vb[2] / s) / 2, oy = (r.height - vb[3] / s) / 2; return [vb[0] + (cx - r.left - ox) * s, vb[1] + (cy - r.top - oy) * s]; }
  function zoomAt(f, px, py) {
    const w = Math.min(geo.w * 1.05, Math.max(12, vb[2] / f)), k = w / vb[2];
    if (px == null) { px = vb[0] + vb[2] / 2; py = vb[1] + vb[3] / 2; }
    vb = [px - (px - vb[0]) * k, py - (py - vb[1]) * k, w, w * vb[3] / vb[2]]; custom(); redraw();
  }
  function focusTown(n, s = 90) { const t = geo.towns[n]; if (!t) return; vb = [t.c[0] - s / 2, t.c[1] - s / 2, s, s]; custom(); draw(); }
  svg.addEventListener("wheel", e => { e.preventDefault(); const [x, y] = svgPt(e.clientX, e.clientY); zoomAt(Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0018)), x, y); }, { passive: false });
  const ptrs = new Map(); let drag = null, moved = false;
  svg.addEventListener("pointerdown", e => { ptrs.set(e.pointerId, [e.clientX, e.clientY]); moved = false; drag = { vb: vb.slice(), pts: new Map(ptrs) }; });
  svg.addEventListener("pointermove", e => {
    if (!ptrs.has(e.pointerId) || !drag) return;
    ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    const r = svg.getBoundingClientRect(), v0 = drag.vb, s = Math.max(v0[2] / r.width, v0[3] / r.height), ids = [...ptrs.keys()];
    if (ids.length === 1 && drag.pts.has(ids[0])) {
      const [x0, y0] = drag.pts.get(ids[0]), [x1, y1] = ptrs.get(ids[0]);
      if (!moved && Math.hypot(x1 - x0, y1 - y0) < 4) return;
      if (!moved) svg.setPointerCapture(e.pointerId);
      moved = true; vb = [v0[0] - (x1 - x0) * s, v0[1] - (y1 - y0) * s, v0[2], v0[3]];
    } else if (ids.length === 2 && ids.every(i => drag.pts.has(i))) {
      const [a0, b0] = ids.map(i => drag.pts.get(i)), [a1, b1] = ids.map(i => ptrs.get(i));
      const f = Math.hypot(a1[0] - b1[0], a1[1] - b1[1]) / Math.hypot(a0[0] - b0[0], a0[1] - b0[1]);
      const w = Math.min(geo.w * 1.05, Math.max(12, v0[2] / f)), k = w / v0[2];
      const m0 = [(a0[0] + b0[0]) / 2, (a0[1] + b0[1]) / 2], m1 = [(a1[0] + b1[0]) / 2, (a1[1] + b1[1]) / 2];
      const px = v0[0] + (m0[0] - r.left) * s, py = v0[1] + (m0[1] - r.top) * s;
      vb = [px - (m1[0] - r.left) * s * k, py - (m1[1] - r.top) * s * k, w, w * v0[3] / v0[2]]; moved = true;
    } else return;
    custom(); redraw();
  });
  const endPtr = e => { ptrs.delete(e.pointerId); drag = ptrs.size ? { vb: vb.slice(), pts: new Map(ptrs) } : null; };
  svg.addEventListener("pointerup", endPtr); svg.addEventListener("pointercancel", endPtr);
  svg.addEventListener("click", e => { if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; } }, true);
  svg.addEventListener("dblclick", e => { const [x, y] = svgPt(e.clientX, e.clientY); zoomAt(e.shiftKey ? 0.5 : 2, x, y); });
  if (opts.controls) {
    const btn = (label, fn, aria) => { const b = document.createElement("button"); b.type = "button"; b.className = "mchip"; b.textContent = label; if (aria) b.setAttribute("aria-label", aria); b.addEventListener("click", fn); opts.controls.append(b); return b; };
    const vbtn = {};
    for (const name of Object.keys(views)) vbtn[name] = btn(name, () => setView(name));
    btn("+", () => zoomAt(1.6), "Zoom in"); btn("−", () => zoomAt(1 / 1.6), "Zoom out");
    const prev = opts.onView; opts.onView = v => { for (const k in vbtn) vbtn[k].setAttribute("aria-pressed", k === v); if (prev) prev(v); };
  }
  draw();
  return { setView, zoomAt, focusTown, redraw: draw, townEl: n => paths[n], zoom: z };
}
