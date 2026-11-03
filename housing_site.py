"""Housing & new construction pages for Granite Docket. Called from site.py (build(out, towns, page, write, slug, e))."""
import datetime as dt, json, os, re, sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
FEATURED = ["Londonderry", "Salem", "Manchester"]
SERIES = [("single", "1-unit (single-family)", "--s1"), ("small", "2–4 unit", "--s2"), ("apt", "5+ unit (apartments)", "--s3")]


def money(v):
    if v >= 1e9: return f"${v / 1e9:.1f}B"
    if v >= 1e6: return f"${v / 1e6:.1f}M"
    if v >= 1e3: return f"${v / 1e3:.0f}K"
    return f"${v:,.0f}"


def nice_max(v):
    if v <= 0: return 1
    p = 10 ** (len(str(int(v))) - 1)
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * p >= v: return m * p
    return 10 * p


def stacked_bars(labels, stacks, fmt, title, flags=None, every=1, w=760, h=240):
    """stacks: list of (key, values). flags: per-bar True when the value is estimated by Census (no report)."""
    L, R, T, B = 58, 10, 14, 34
    n = len(labels); top = nice_max(max((sum(s[1][i] for s in stacks) for i in range(n)), default=0))
    bw = (w - L - R) / max(n, 1)
    y = lambda v: T + (h - T - B) * (1 - v / top)
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{title}"><title>{title}</title>']
    for k in range(5):
        v = top * k / 4
        out.append(f'<line class="grid" x1="{L}" x2="{w - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/><text class="ax" x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{fmt(v)}</text>')
    for i, lab in enumerate(labels):
        x0, base = L + i * bw + bw * 0.12, 0
        for key, vals in stacks:
            v = vals[i]
            if v <= 0: continue
            out.append(f'<rect class="b-{key}{" est" if flags and flags[i] else ""}" x="{x0:.1f}" y="{y(base + v):.1f}" width="{bw * 0.76:.1f}" height="{y(base) - y(base + v):.1f}"><title>{lab}: {fmt(v)}</title></rect>')
            base += v
        if i % every == 0:
            out.append(f'<text class="ax" x="{L + i * bw + bw / 2:.1f}" y="{h - B + 16}" text-anchor="middle">{lab}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{w - R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/></svg>')
    return "".join(out)


def line_chart(labels, series, fmt, title, w=520, h=220, zero=True):
    """series: list of (css_class, label, values); None values are skipped."""
    L, R, T, B = 58, 12, 14, 34
    vals = [v for _, _, vs in series for v in vs if v is not None]
    if not vals: return ""
    hi = nice_max(max(vals)); lo = 0 if zero else min(vals) * 0.9
    x = lambda i: L + (w - L - R) * (i / max(1, len(labels) - 1))
    y = lambda v: T + (h - T - B) * (1 - (v - lo) / (hi - lo or 1))
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{title}"><title>{title}</title>']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        out.append(f'<line class="grid" x1="{L}" x2="{w - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/><text class="ax" x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{fmt(v)}</text>')
    for i, lab in enumerate(labels):
        out.append(f'<text class="ax" x="{x(i):.1f}" y="{h - B + 16}" text-anchor="middle">{lab}</text>')
    for cls, label, vs in series:
        pts = [(x(i), y(v), v, labels[i]) for i, v in enumerate(vs) if v is not None]
        out.append(f'<polyline class="ln {cls}" points="{" ".join(f"{a:.1f},{b:.1f}" for a, b, _, _ in pts)}"/>')
        out += [f'<circle class="pt {cls}" cx="{a:.1f}" cy="{b:.1f}" r="3"><title>{label} {lab}: {fmt(v)}</title></circle>' for a, b, v, lab in pts]
        if pts and cls == series[0][0]: out.append(f'<text class="ax lbl {cls}" x="{pts[-1][0] - 4:.1f}" y="{pts[-1][1] - 8:.1f}" text-anchor="end">{fmt(pts[-1][2])}</text>')
    out.append("</svg>")
    return "".join(out)


def spark(vals, w=120, h=26):
    if not vals or max(vals) <= 0: return '<svg class="spark" viewBox="0 0 120 26"></svg>'
    top = max(vals); bw = w / len(vals)
    bars = "".join(f'<rect x="{i * bw:.1f}" y="{h - h * v / top:.1f}" width="{bw * 0.8:.1f}" height="{h * v / top:.1f}"/>' for i, v in enumerate(vals))
    return f'<svg class="spark" viewBox="0 0 {w} {h}" aria-hidden="true">{bars}</svg>'


def legend(est=False):
    items = "".join(f'<span><i class="sw b-{k}"></i>{lab}</span>' for k, lab, _ in SERIES)
    if est: items += '<span><i class="sw est-sw"></i>estimated by Census (town did not report)</span>'
    return f'<div class="legend">{items}</div>'


def cluster_projects(rows):
    """Collapse repeated mentions of the same project (same town + unit count) across meetings."""
    g = {}
    for r in rows:
        key = (r["town"], r["units"])
        c = g.setdefault(key, dict(r, first=r["date"], last=r["date"], n=0, boards=set(), urls=[]))
        c["n"] += 1; c["boards"].add(r["board"])
        c["first"] = min(c["first"] or "9", r["date"] or "9"); c["last"] = max(c["last"] or "", r["date"] or "")
        if not c.get("location") and r.get("location"): c["location"] = r["location"]
        if r["board"] in ("planning", "zoning") and c["board"] not in ("planning", "zoning"):
            c.update(snippet=r["snippet"], url=r["url"], board=r["board"], kind=r["kind"])
        c["urls"].append(r["url"])
    out = [c for c in g.values() if c["n"] >= 2 or c["board"] in ("planning", "zoning")]
    return sorted(out, key=lambda c: c["last"] or "", reverse=True)


def build(out, towns, page, write, slug, e):
    db = sqlite3.connect(os.path.join(ROOT, "housing.db"))
    db.row_factory = sqlite3.Row
    months = [r[0] for r in db.execute("SELECT DISTINCT period FROM permits WHERE kind='month' ORDER BY 1")]
    years = [r[0] for r in db.execute("SELECT DISTINCT period FROM permits WHERE kind='year' ORDER BY 1")]
    last12 = months[-12:]; prev12 = months[-24:-12]
    M = defaultdict(dict); Y = defaultdict(dict)
    for r in db.execute("SELECT * FROM permits"):
        d = dict(r); d["single"] = (d["u1"], d["v1"]); d["small"] = (d["u2"] + d["u34"], d["v2"] + d["v34"]); d["apt"] = (d["u5"], d["v5"])
        (M if d["kind"] == "month" else Y)[d["town"]][d["period"]] = d
    opd = defaultdict(dict)
    for r in db.execute("SELECT * FROM opd"): opd[r["town"]][r["year"]] = dict(r)
    projs = defaultdict(list)
    for r in db.execute("SELECT * FROM projects"): projs[r["town"]].append(dict(r))
    clusters = {t: cluster_projects(v) for t, v in projs.items()}
    dra = defaultdict(dict)
    for r in db.execute("SELECT * FROM dra"): dra[r["town"]][r["year"]] = dict(r)

    def tot(town, periods, idx, keys=("single", "small", "apt")):
        return sum(M[town][p][k][idx] for p in periods if p in M[town] for k in keys)

    # ---------- statewide monthly chart
    sv = {k: [sum(M[t][p][k][1] for t in M if p in M[t]) for p in months] for k, _, _ in SERIES}
    est_share = [sum(1 for t in M if p in M[t] and not M[t][p]["reported"]) / max(1, sum(1 for t in M if p in M[t])) for p in months]
    labs = [dt.date(int(p[:4]), int(p[5:]), 1).strftime("%b %y") for p in months]
    state_chart = stacked_bars(labs, [(k, sv[k]) for k, _, _ in SERIES], money, "Statewide permitted construction value by month", every=6)
    t12 = sum(sum(v[-12:]) for v in sv.values()); p12 = sum(sum(v[-24:-12]) for v in sv.values())
    apt12 = sum(tot(t, last12, 0, ("apt",)) for t in M); u12 = sum(tot(t, last12, 0) for t in M)

    # ---------- ranking table
    rows = []
    for t in M:
        v12, v_prev = tot(t, last12, 1), tot(t, prev12, 1)
        if v12 <= 0 and v_prev <= 0: continue
        rep = sum(1 for p in last12 if p in M[t] and M[t][p]["reported"])
        rows.append(dict(town=t, v12=v12, vprev=v_prev, u12=tot(t, last12, 0), a12=tot(t, last12, 0, ("apt",)), rep=rep,
                         spark=[tot(t, [p], 1) for p in months[-24:]]))
    rows.sort(key=lambda r: -r["v12"])

    def chg(a, b):
        if not b: return '<span class="tr up">new</span>' if a else ""
        c = (a - b) / b * 100
        return f'<span class="tr {"up" if c > 0 else "dn"}">{"▲" if c > 0 else "▼"} {abs(c):.0f}%</span>'

    table = "".join(f"""<tr><td><a href="{slug(r["town"])}/index.html">{e(r["town"])}</a></td><td class="n">{money(r["v12"])}</td><td>{chg(r["v12"], r["vprev"])}</td>
<td class="n">{r["u12"]:,}</td><td class="n">{r["a12"]:,}</td><td>{spark(r["spark"])}</td><td class="n {"" if r["rep"] >= 10 else "warn"}">{r["rep"]}/12</td></tr>""" for r in rows[:60])

    # ---------- featured towns
    def town_charts(t):
        yv = [(p, Y[t][p]) for p in years if p in Y[t]]
        annual = stacked_bars([p for p, _ in yv], [(k, [d[k][0] for _, d in yv]) for k, _, _ in SERIES], lambda v: f"{v:,.0f}",
                              f"{t}: housing units permitted per year", flags=[d["reported"] == 0 for _, d in yv], w=520, h=220)
        mm = months[-36:]
        monthly = stacked_bars([dt.date(int(p[:4]), int(p[5:]), 1).strftime("%b %y") for p in mm],
                               [(k, [M[t][p][k][1] if p in M[t] else 0 for p in mm]) for k, _, _ in SERIES], money,
                               f"{t}: permitted construction value per month", flags=[(p in M[t] and not M[t][p]["reported"]) for p in mm], every=6, w=520, h=220)
        return annual, monthly

    def new_res(t, y):  # residential construction value permitted in year y (Census, all structure types)
        d = Y[t].get(str(y))
        return (d["v1"] + d["v2"] + d["v34"] + d["v5"]) if d else 0

    def tax_charts(t):
        dr = dra.get(t, {})
        yrs = [y for y in sorted(dr) if dr[y]["equalized"] and dr[y]["total_rate"]]
        if len(yrs) < 2: return None
        y0 = yrs[0]; base = dr[y0]["equalized"]; cum = 0; parts = {"base": [], "new": [], "appr": []}
        for y in yrs:
            if y > y0: cum += new_res(t, y)
            eq = dr[y]["equalized"]; b = min(base, eq); n = max(0, min(cum, eq - b))
            parts["base"].append(b); parts["new"].append(n); parts["appr"].append(max(0, eq - b - n))
        stack = stacked_bars([str(y) for y in yrs], [(k, parts[k]) for k in ("base", "new", "appr")], money,
                             f"{t}: equalized valuation split into {y0} base, new residential construction, and everything else", w=520, h=220)
        rates = line_chart([str(y) for y in yrs], [("tot", "Total tax rate", [dr[y]["total_rate"] for y in yrs]),
                                                   ("full", "Full-value rate", [round(dr[y]["total_rate"] * dr[y]["ratio"] / 100, 2) if dr[y]["ratio"] else None for y in yrs]),
                                                   ("sch", "Local school rate", [dr[y]["school_rate"] for y in yrs])],
                           lambda v: f"${v:.2f}", f"{t}: tax rate per $1,000", w=520, h=220)
        growth = dr[yrs[-1]]["equalized"] - base
        return dict(stack=stack, rates=rates, y0=y0, y1=yrs[-1], base=base, end=dr[yrs[-1]]["equalized"], growth=growth, new=cum,
                    share=(cum / growth if growth > 0 else None), r0=dr[y0]["total_rate"], r1=dr[yrs[-1]]["total_rate"])

    TAXLEG = ('<div class="legend"><span><i class="sw b-base"></i>value at start</span><span><i class="sw b-new"></i>new residential construction since (permit value)</span>'
              '<span><i class="sw b-appr"></i>appreciation, commercial and everything else</span></div>')
    RATELEG = ('<div class="legend"><span><i class="sw ln-tot"></i>total tax rate</span><span><i class="sw ln-full"></i>full-value rate (at market value)</span>'
               '<span><i class="sw ln-sch"></i>local school rate</span></div>')

    def tax_block(t, tc):
        share = f", about {tc['share'] * 100:.0f}% of the growth" if tc["share"] else ""
        return f"""<div class="taxline">Tax base {tc["y0"]}→{tc["y1"]}: {money(tc["base"])} → {money(tc["end"])} (+{tc["growth"] / tc["base"] * 100:.0f}%).
New residential construction permitted since then: {money(tc["new"])}{share}. Total tax rate ${tc["r0"]:.2f} → ${tc["r1"]:.2f} per $1,000.</div>
<div class="two"><figure>{TAXLEG}{tc["stack"]}<figcaption>Equalized (market) valuation, NH DRA</figcaption></figure><figure>{RATELEG}{tc["rates"]}<figcaption>Tax rate per $1,000 of assessed value, NH DRA</figcaption></figure></div>"""

    feat = []
    for t in FEATURED:
        if t not in M: continue
        a, m = town_charts(t)
        feat.append(f"""<article class="fcard"><div class="fh"><a class="town" href="{slug(t)}/index.html">{e(t)}</a><span class="num">last 12 months: {money(tot(t, last12, 1))} · {tot(t, last12, 0):,} units · {tot(t, last12, 0, ("apt",)):,} in 5+ unit buildings</span></div>
<div class="two"><figure>{a}<figcaption>Units per year</figcaption></figure><figure>{m}<figcaption>Construction value per month</figcaption></figure></div>{tax_block(t, tax_charts(t)) if tax_charts(t) else ""}</article>""")

    taxrows = []
    for t in sorted(dra):
        if t not in Y: continue
        tc = tax_charts(t)
        if not tc or tc["new"] < 10e6: continue
        taxrows.append((t, tc))
    taxrows.sort(key=lambda x: -(x[1]["new"] / x[1]["base"]))
    taxtable = "".join(f"""<tr><td><a href="{slug(t)}/index.html">{e(t)}</a></td><td class="n">{money(tc["base"])}</td><td class="n">{money(tc["end"])}</td><td class="n">+{tc["growth"] / tc["base"] * 100:.0f}%</td>
<td class="n">{money(tc["new"])}</td><td class="n">{tc["new"] / tc["base"] * 100:.1f}%</td><td class="n">{f'{tc["share"] * 100:.0f}%' if tc["share"] else "–"}</td><td class="n">${tc["r0"]:.2f} → ${tc["r1"]:.2f}</td></tr>""" for t, tc in taxrows[:60])

    big = sorted([c for v in clusters.values() for c in v if c["units"] >= 40 and (c["last"] or "") >= "2024-01-01"], key=lambda c: -c["units"])[:25]
    def proj_rows(cs, show_town=True):
        return "".join(f"""<tr>{f'<td><a href="{slug(c["town"])}/index.html">{e(c["town"])}</a></td>' if show_town else ""}<td class="n">{c["units"]:,}</td><td>{e(c["kind"])}</td><td>{e(c.get("location") or "")}</td>
<td>{e(c["first"] or "")} → {e(c["last"] or "")}</td><td class="n">{c["n"]}</td><td class="wrapcell"><a href="{e(c["url"])}" target="_blank" rel="noopener">source</a> <span class="q">…{e(c["snippet"][:240])}…</span></td></tr>""" for c in cs)

    body = f"""<header class="hd"><div class="eyebrow">Housing · new construction · New Hampshire</div><h1>What's being built</h1>
<p class="lede">Residential building permits filed with each town, with their construction value, from the US Census Building Permits Survey. "5+ unit" buildings are apartment and garden-style complexes. Projects are located from planning board records.</p></header>
<div class="stats"><div><b>{money(t12)}</b><span>permitted construction, last 12 months</span></div><div><b>{chg(t12, p12) or "–"}</b><span>vs. prior 12 months</span></div>
<div><b>{u12:,}</b><span>housing units permitted</span></div><div><b>{apt12:,}</b><span>units in 5+ unit buildings</span></div></div>
<section><h2>Statewide, by month</h2>{legend()}<figure class="wide">{state_chart}</figure>
<p class="note">Through {e(labs[-1] if labs else "")}. Value is the construction cost stated on the permit, not assessed value. Census fills in towns that did not report a month with estimates: {est_share[-1] * 100:.0f}% of towns in the latest month, so recent months will be revised.</p></section>
<section><h2>Featured towns</h2>{legend(True)}<div class="feat">{"".join(feat)}</div></section>
<section><h2>Towns ranked by construction value, last 12 months</h2><p class="note">"Reported" counts the months the town itself reported to Census. Fewer than 10 means much of the figure is a Census estimate.</p>
<div class="tablebox"><table><thead><tr><th>Town</th><th>Value</th><th>vs. prior 12 mo.</th><th>Units</th><th>5+ unit</th><th>24 months</th><th>Reported</th></tr></thead><tbody>{table}</tbody></table></div></section>
<section><h2>Largest projects in planning records since 2024</h2><p class="note">Unit counts pulled automatically from planning board, zoning and council documents. Mentions of the same unit count in one town are grouped. Read the source before relying on one: some are city-wide totals or proposals that never went ahead.</p>
<div class="tablebox"><table><thead><tr><th>Town</th><th>Units</th><th>Type</th><th>Location</th><th>Mentioned</th><th>Docs</th><th>Excerpt</th></tr></thead><tbody>{proj_rows(big)}</tbody></table></div></section>
<section><h2>New construction and the tax base, 2018–2025</h2><p class="note">Equalized valuation is NH DRA's estimate of each town's full market value, which removes the jumps from town revaluations. "New construction" is the residential permit value Census recorded from 2019 on, so treat it as a rough guide: permit value is not assessed value, and commercial building is not included. Ranked by new construction as a share of the 2018 tax base; towns with under $10M of new construction are left out.</p>
<div class="tablebox"><table><thead><tr><th>Town</th><th>Equalized 2018</th><th>Equalized 2025</th><th>Growth</th><th>New residential construction</th><th>% of 2018 base</th><th>Share of growth</th><th>Total tax rate</th></tr></thead><tbody>{taxtable}</tbody></table></div></section>"""
    write("housing/index.html", page("Housing & new construction · Granite Docket", 1, body, "NH residential building permits and construction value by town and month."))

    # ---------- per-town housing pages
    for t in towns:
        if t not in M and t not in clusters: continue
        a, m = town_charts(t) if t in M else ("", "")
        od = opd.get(t, {})
        cmp = "".join(f'<tr><td>{y}</td><td class="n">{Y[t][str(y)]["u1"] + Y[t][str(y)]["u2"] + Y[t][str(y)]["u34"] + Y[t][str(y)]["u5"] if str(y) in Y[t] else "–"}</td><td class="n">{Y[t][str(y)]["u5"] if str(y) in Y[t] else "–"}</td><td class="n">{(Y[t][str(y)]["reported"] if str(y) in Y[t] else "–")}</td><td class="n">{od[y]["sf"] + od[y]["f2"] + od[y]["conv"] + od[y]["u34"] + od[y]["u5"] + od[y]["mh"] if y in od else "–"}</td><td class="n">{od[y]["u5"] if y in od else "–"}</td></tr>' for y in range(2020, 2026))
        dr = dra.get(t, {})
        dra_html = ""
        if dr:
            yrs = sorted(dr)
            dra_html = "<table><thead><tr><th>Year</th><th>Net valuation</th><th>Residential buildings</th><th>Equalization ratio</th><th>Total tax rate</th><th>Municipal</th><th>Local school</th></tr></thead><tbody>" + "".join(
                f'<tr><td>{y}</td><td class="n">{money(dr[y]["net_valuation"] or 0)}</td><td class="n">{money(dr[y]["res_buildings"] or 0)}</td><td class="n">{dr[y]["ratio"] or ""}</td><td class="n">${dr[y]["total_rate"] or 0:.2f}</td><td class="n">${dr[y]["municipal_rate"] or 0:.2f}</td><td class="n">${dr[y]["school_rate"] or 0:.2f}</td></tr>' for y in yrs) + "</tbody></table>"
        body = f"""<header class="hd"><div class="eyebrow">Housing · <a href="../index.html">all towns</a></div><h1>{e(t)}: new construction</h1>
<p class="lede">Last 12 months: {money(tot(t, last12, 1))} of permitted residential construction, {tot(t, last12, 0):,} units, {tot(t, last12, 0, ("apt",)):,} of them in 5+ unit buildings. <a href="../../towns/{slug(t)}/index.html">Meeting records for {e(t)}</a>.</p></header>
{f'<section><h2>Permits</h2>{legend(True)}<div class="two"><figure>{a}<figcaption>Units per year (Census BPS annual)</figcaption></figure><figure>{m}<figcaption>Construction value per month, last 36 months</figcaption></figure></div></section>' if a else ""}
<section><h2>Two sources compared</h2><p class="note">Census counts permits issued; NH Office of Planning and Development counts net new units from the town's own survey (after demolitions). Where they disagree, the town survey is usually more reliable, especially in years the town didn't report to Census.</p>
<div class="tablebox"><table><thead><tr><th>Year</th><th>Census units</th><th>Census 5+</th><th>Months reported</th><th>OPD net units</th><th>OPD 5+</th></tr></thead><tbody>{cmp}</tbody></table></div></section>
{f'<section><h2>New construction, tax base and tax rate</h2>{tax_block(t, tax_charts(t))}<div class="tablebox">{dra_html}</div></section>' if dra_html and t in Y and tax_charts(t) else (f'<section><h2>Assessed value and tax rate</h2><div class="tablebox">{dra_html}</div></section>' if dra_html else "")}
<section><h2>Projects in planning records</h2>{f'<div class="tablebox"><table><thead><tr><th>Units</th><th>Type</th><th>Location</th><th>Mentioned</th><th>Docs</th><th>Excerpt</th></tr></thead><tbody>{proj_rows(clusters.get(t, [])[:40], False)}</tbody></table></div>' if clusters.get(t) else '<p class="empty">No multifamily projects found in the collected records.</p>'}</section>"""
        write(f"housing/{slug(t)}/index.html", page(f"{t} housing · Granite Docket", 2, body, f"New construction in {t}, NH"))
