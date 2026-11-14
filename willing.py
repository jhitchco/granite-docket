"""Housing willingness heatmap: a 0-100 score per town for openness to new housing.

Rubric, 100 points. The first four measures are percentiles among towns with Census permit data, so a town is
scored against its peers rather than against Manchester; per-resident rates keep cities from winning on size.
Willingness here means what a town has actually let happen and what its boards are working on. Small rural
towns without water or sewer can score low for reasons that aren't only attitude, and the page says so.
"""
import datetime as dt, json
from maps import load

RUBRIC = [
    ("build", 35, "Building now", "Housing units of every type permitted in the last three full years, per 1,000 residents (Census Building Permits Survey)."),
    ("dense", 20, "Room for apartments", "Units in 5+ unit buildings permitted over the last five years plus this year, per 1,000 residents. Zero scores zero."),
    ("pipe", 20, "Big projects in the pipeline", "Units in projects over 15 units named in planning and zoning records since mid-2023, per 1,000 residents. Approved or under construction count in full, proposals and concepts at half, denied or withdrawn not at all."),
    ("trend", 10, "Picking up", "Units permitted in the last three full years compared with the three before."),
    ("policy", 15, "What boards are working on", "Starts at 50. Up 10 for each housing tool named in recent records (workforce housing ordinance, inclusionary zoning, cottage courts, missing middle, smaller lots, multifamily by right, InvestNH grants, Housing Champion designation); down 20 for each limit (growth-management ordinance, permit cap, phasing ordinance, residential moratorium)."),
]
ENABLE = {'"workforce housing ordinance"': "workforce housing ordinance", '"inclusionary zoning"': "inclusionary zoning", '"cottage court"': "cottage courts",
          '"missing middle"': "missing middle", '"reduce minimum lot size" OR "smaller lot sizes" OR "reduced lot size"': "smaller lots",
          '"by right" AND (multifamily OR "multi-family")': "multifamily by right", 'InvestNH': "InvestNH grant", '"Housing Champion"': "Housing Champion"}
RESTRICT = {'"growth management ordinance"': "growth-management ordinance", '"permit cap" OR "building permit cap" OR "building permit limitation"': "permit cap",
            '"phasing ordinance" OR "phased development ordinance"': "phasing ordinance",
            '"moratorium on residential" OR "residential moratorium" OR "moratorium on subdivision"': "residential moratorium"}
BANDS = [(65, "Saying yes", "b4"), (50, "Open", "b3"), (35, "Middle of the pack", "b2"), (20, "Cautious", "b1"), (0, "Little being built", "b0")]


def scores(mconn, hdb):
    today = dt.date.today()
    full = [r[0] for r in hdb.execute("SELECT DISTINCT period FROM permits WHERE kind='year' ORDER BY 1")]
    last3, prev3 = full[-3:], full[-6:-3]
    five = {str(y) for y in range(today.year - 5, today.year + 1)}
    pop = dict(mconn.execute("SELECT name,population FROM towns"))
    U, U5 = {}, {}
    for town, period, u1, u2, u34, u5 in hdb.execute("SELECT town,period,u1,u2,u34,u5 FROM permits WHERE kind='year'"):
        U.setdefault(town, {})[period] = u1 + u2 + u34 + u5
        if period in five: U5[town] = U5.get(town, 0) + u5
    after = str(int(full[-1]) + 1)  # months of the current year, not yet in an annual file
    if after in five:
        for town, u5 in hdb.execute("SELECT town,sum(u5) FROM permits WHERE kind='month' AND period LIKE ? GROUP BY town", (after + "-%",)):
            U5[town] = U5.get(town, 0) + (u5 or 0)
    pipe = {}
    for p in (load("big_builds.json", {}) or {}).get("projects", []):
        w = 1 if p.get("status") in ("approved", "under construction") else 0 if p.get("status") in ("denied", "withdrawn") else 0.5
        pipe[p["town"]] = pipe.get(p["town"], 0) + w * (p.get("units") or 0)
    sig = {}
    for kind, terms in (("enable", ENABLE), ("restrict", RESTRICT)):
        for q, lab in terms.items():
            for (town,) in mconn.execute("""SELECT DISTINCT d.town FROM doc_fts f JOIN documents d ON d.id=f.rowid
                                             WHERE doc_fts MATCH ? AND d.meeting_date>='2023-07-01'""", (q,)):
                sig.setdefault(town, {"enable": [], "restrict": []})[kind].append(lab)
    crawled = {r[0] for r in mconn.execute("SELECT name FROM towns WHERE crawl_status='done'")}
    raw = {}
    for t, p in pop.items():
        if t not in U or not p: continue
        k = p / 1000
        b3 = sum(U[t].get(y, 0) for y in last3); p3 = sum(U[t].get(y, 0) for y in prev3)
        s = sig.get(t, {"enable": [], "restrict": []})
        raw[t] = dict(build=b3 / k, dense=U5.get(t, 0) / k, pipe=pipe.get(t, 0) / k, trend=(b3 + 1) / (p3 + 1),
                      policy=max(0, min(100, 50 + 10 * len(s["enable"]) - 20 * len(s["restrict"]))) if t in crawled else 50,
                      n3=b3, np3=p3, n5=U5.get(t, 0), np=round(pipe.get(t, 0)), enable=s["enable"], restrict=s["restrict"], pop=p, crawled=t in crawled)

    def pct(key, zero_is_zero):
        vals = [v[key] for v in raw.values()]
        return {t: 0 if zero_is_zero and v[key] <= 0 else
                100 * (sum(1 for y in vals if y < v[key]) + 0.5 * sum(1 for y in vals if y == v[key])) / len(vals) for t, v in raw.items()}
    P = {"build": pct("build", True), "dense": pct("dense", True), "pipe": pct("pipe", True), "trend": pct("trend", False)}
    rows = {}
    for t, v in raw.items():
        parts = {k: P[k][t] if k != "policy" else v["policy"] for k, *_ in RUBRIC}
        score = round(sum(parts[k] * w for k, w, *_ in RUBRIC) / 100)
        band = next(b for b in BANDS if score >= b[0])
        rows[t] = dict(score=score, band=band[1], cls=band[2], parts={k: round(x) for k, x in parts.items()},
                       **{k: v[k] for k in ("n3", "np3", "n5", "np", "pop", "enable", "restrict", "crawled")})
    return rows, f"{last3[0]}–{last3[-1]}"


def page_body(mconn, hdb, e, slug):
    rows, years = scores(mconn, hdb)
    ranked = sorted(rows.items(), key=lambda x: (-x[1]["score"], x[0]))
    counts = {b[1]: sum(1 for r in rows.values() if r["band"] == b[1]) for b in BANDS}
    rub = "".join(f"<tr><td><b>{e(lab)}</b></td><td class=n>{w}</td><td>{e(d)}</td></tr>" for k, w, lab, d in RUBRIC)
    legend = "".join(f'<button type="button" class="fchip" data-f="{c}" aria-pressed="false"><span class="wsw {c}"></span>{e(l)} <b>{counts[l]}</b></button>' for _, l, c in BANDS)
    trs = "".join(f"""<tr data-town="{e(t)}" data-cls="{r["cls"]}"><td class=n>{i + 1}</td><td><a href="../../towns/{slug(t)}/index.html">{e(t)}</a></td><td class=n><span class="wsc {r["cls"]}">{r["score"]}</span></td><td>{e(r["band"])}</td>
<td class=n>{r["parts"]["build"]}</td><td class=n>{r["parts"]["dense"]}</td><td class=n>{r["parts"]["pipe"]}</td><td class=n>{r["parts"]["trend"]}</td><td class=n>{r["parts"]["policy"]}</td><td class=n>{r["pop"]:,}</td></tr>"""
                  for i, (t, r) in enumerate(ranked))
    body = f"""<header class="hd"><div class="eyebrow">Housing · <a href="../index.html">new construction</a> · heatmap</div><h1>Where New Hampshire says yes to housing</h1>
<p class="lede">A 0–100 score for each town's openness to new housing, read from what it has actually permitted, the big projects moving through its boards, and the housing rules its boards are working on. Greener is more willing.</p></header>
<section class="mapsplit">
 <div class="mappanel"><div class="mctl" id="mctl"></div><svg class="nhmap" id="map" role="img" aria-label="Heatmap of New Hampshire towns by housing willingness score"></svg>
  <p class="mhint">Scroll or pinch to zoom, drag to move. Click a town to see how its score is built; gray towns have no Census permit data.</p></div>
 <div class="mapside"><h2>Score bands</h2><div class="fchips" id="fchips">{legend}</div>
  <div class="wcard" id="wcard"><p class="note">Pick a town on the map or in the table to see how its score is built.</p></div></div>
</section>
<section><h2>The rubric</h2><div class="tablebox"><table><thead><tr><th>Measure</th><th>Points</th><th>How it's scored</th></tr></thead><tbody>{rub}</tbody></table></div>
<p class="note">The first four measures are percentiles among the {len(rows)} towns with Census data: 100 means a town is ahead of every other town on that measure. Per-resident rates keep big cities from winning on size alone. Three-year window: {years}, compared with the three years before. Bands: 65+ saying yes, 50–64 open, 35–49 middle of the pack, 20–34 cautious, under 20 little being built. Because every measure is relative, the statewide average sits near 40.</p>
<p class="note">What this doesn't capture: water and sewer capacity, land prices and demand. Small rural towns can score low without anyone saying no, and a high score in a growing suburb can sit alongside heated local debate. Policy signals come from keywords in meeting records and are rougher than the permit numbers; towns whose sites can't be crawled get a neutral 50 on that measure.</p></section>
<section><h2>All towns, ranked</h2><div class="lctl"><input type="search" id="q" placeholder="Find a town" aria-label="Find a town"></div>
<div class="tablebox"><table class="wtab" id="wtab"><thead><tr><th>#</th><th>Town</th><th>Score</th><th>Band</th><th>Building</th><th>Apartments</th><th>Pipeline</th><th>Trend</th><th>Policy</th><th>Pop.</th></tr></thead><tbody>{trs}</tbody></table></div></section>
<script src="../../assets/nh-towns.js"></script><script src="../../assets/mapkit.js"></script>
<script>
(function(){{
const R={json.dumps(rows, ensure_ascii=False, separators=(",", ":"))};
const RUB={json.dumps([[k, w, lab] for k, w, lab, d in RUBRIC], ensure_ascii=False)}, Y={json.dumps(years)};
const geo=window.NH_GEO, on=new Set(); let sel=null, m;
const h=(t,a={{}},x)=>{{const e=document.createElement(t);for(const k in a)e.setAttribute(k,a[k]);if(x!=null)e.textContent=x;return e;}};
const tip=h("div",{{class:"mtip",hidden:""}});document.body.append(tip);
m=NHMap(document.getElementById("map"),geo,{{views:{{"Southern tier":geo.views.south,"Seacoast":geo.views.sea,"Lakes & Concord":geo.views.lakes,"Upper Valley":geo.views.uv}},controls:document.getElementById("mctl"),
 onDraw(){{for(const t in geo.towns){{const p=m&&m.townEl(t);if(!p)continue;const r=R[t];p.setAttribute("class","t w "+(r?r.cls:"nodata")+(r&&on.size&&!on.has(r.cls)?" dim":"")+(sel===t?" on":""));}}}}}});
function card(t){{const r=R[t],c=document.getElementById("wcard");c.replaceChildren();
 if(!r){{c.append(h("h3",{{}},t),h("p",{{class:"note"}},"No Census permit data, so no score."));return;}}
 const s=h("p");s.append(h("span",{{class:"wsc "+r.cls}},String(r.score))," "+r.band);c.append(h("h3",{{}},t),s);
 for(const [k,w,lab] of RUB){{const row=h("div",{{class:"wbar"}});row.append(h("span",{{}},lab),h("span",{{class:"n"}},Math.round(r.parts[k]*w/100)+" / "+w));const b=h("i");b.append(h("b",{{style:`width:${{r.parts[k]}}%`}}));row.append(b);c.append(row);}}
 const f=h("ul",{{class:"wfacts"}});
 f.append(h("li",{{}},`${{r.n3.toLocaleString()}} units permitted ${{Y}} (${{r.np3.toLocaleString()}} in the three years before) · population ${{r.pop.toLocaleString()}}`));
 f.append(h("li",{{}},`${{r.n5.toLocaleString()}} units in 5+ unit buildings permitted since ${{new Date().getFullYear()-5}}`));
 if(r.np)f.append(h("li",{{}},`${{r.np.toLocaleString()}} weighted units in big projects named in the records`));
 if(r.enable.length)f.append(h("li",{{}},"Housing tools in the records: "+[...new Set(r.enable)].join(", ")));
 if(r.restrict.length)f.append(h("li",{{}},"Limits in the records: "+[...new Set(r.restrict)].join(", ")));
 if(!r.crawled)f.append(h("li",{{}},"Meeting records not crawled, so policy is set to neutral."));
 c.append(f);}}
function pick(t){{sel=t;m.redraw();card(t);document.querySelectorAll("#wtab tr.on").forEach(x=>x.classList.remove("on"));const tr=document.querySelector(`#wtab tr[data-town="${{CSS.escape(t)}}"]`);if(tr)tr.classList.add("on");}}
for(const t in geo.towns){{const p=m.townEl(t);if(!p)continue;p.style.cursor="pointer";p.addEventListener("click",()=>pick(t));
 p.addEventListener("mousemove",e=>{{const r=R[t];tip.textContent=r?`${{t}} · ${{r.score}} · ${{r.band}}`:`${{t}} · no data`;tip.hidden=false;tip.style.left=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8)+"px";tip.style.top=(e.clientY+14)+"px";}});
 p.addEventListener("mouseleave",()=>tip.hidden=true);}}
document.querySelectorAll("#wtab tbody tr").forEach(tr=>tr.addEventListener("click",ev=>{{if(ev.target.closest("a"))return;pick(tr.dataset.town);m.focusTown(tr.dataset.town,120);document.querySelector(".mapsplit").scrollIntoView({{behavior:"smooth"}});}}));
function filter(){{const q=document.getElementById("q").value.trim().toLowerCase();document.querySelectorAll("#wtab tbody tr").forEach(tr=>tr.hidden=!((!on.size||on.has(tr.dataset.cls))&&(!q||tr.dataset.town.toLowerCase().includes(q))));m.redraw();}}
document.querySelectorAll("#fchips .fchip").forEach(b=>b.addEventListener("click",()=>{{const f=b.dataset.f;on.has(f)?on.delete(f):on.add(f);b.setAttribute("aria-pressed",on.has(f));filter();}}));
document.getElementById("q").addEventListener("input",filter);
m.redraw();
}})();
</script>"""
    return body, ranked
