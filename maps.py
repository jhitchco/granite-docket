"""Map pages for Granite Docket: topic pages (one map + one town list) and the housing big-builds map.

Called from site.py after the rest of the site is written. Inputs:
  mapdata/nh_towns.json            town outlines in map coordinates (Census cousub 2023, equirectangular at 43.9N)
  mapdata/insights_<topic>.json    per-town read of the records: stance, what they seem to be weighing, the good and the bad
  mapdata/big_builds.json          housing projects over 15 units, checked against source text
  nh_meetings.db / housing.db      records and Census permits
"""
import datetime as dt, json, os, re, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(ROOT, "mapdata")
STANCE_ORDER = ["against", "leaning_against", "regulating", "mixed", "leaning_for", "for", "unclear"]
CLS = {"against": "against", "leaning_against": "lagainst", "regulating": "reg", "mixed": "mixed", "leaning_for": "lfor", "for": "for", "unclear": "unclear"}


def load(name, default=None):
    p = os.path.join(MD, name)
    return json.load(open(p, encoding="utf8")) if os.path.exists(p) else default


def assets(out):
    a = os.path.join(out, "assets"); os.makedirs(a, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "mapkit.js"), os.path.join(a, "mapkit.js"))
    geo = load("nh_towns.json")
    open(os.path.join(a, "nh-towns.js"), "w", encoding="utf8").write("window.NH_GEO=" + json.dumps(geo, ensure_ascii=False, separators=(",", ":")) + ";")


def topic_events(conn, topic):
    """Every record that matched the topic, one per file (towns post the same file at several URLs)."""
    evs, seen = {}, set()
    for town, board, typ, date, title, url, terms, snips, sha in conn.execute(
            """SELECT d.town,d.board,d.doc_type,d.meeting_date,d.title,d.url,h.terms,h.snippets,d.sha256
               FROM hits h JOIN documents d ON d.id=h.doc_id WHERE h.topic=? ORDER BY length(d.url)""", (topic,)):
        if (town, sha) in seen: continue
        seen.add((town, sha))
        evs.setdefault(town, []).append(dict(board=board, type=typ, date=date, title=title, url=url, terms=terms, snippets=json.loads(snips or "[]")))
    for v in evs.values(): v.sort(key=lambda x: x.get("date") or "", reverse=True)
    return evs


def topic_page(key, label, tslug, desc, conn, ctx):
    e, slug, BOARD, STANCE, auto_stance, hand, window = (ctx[k] for k in ("e", "slug", "BOARD", "STANCE", "auto_stance", "hand", "window"))
    ins = {x["town"]: x for x in (load(f"insights_{key}.json", {}) or {}).get("towns", [])}
    evs = topic_events(conn, key)
    cut = (dt.date.today() - dt.timedelta(window)).isoformat()
    cards, quiet, mapd = [], [], {}
    for town, tev in evs.items():
        i = ins.get(town)
        if (i and not i.get("relevant")) or (not i and hand.get(town, {}).get("stance") == "not_relevant"):
            quiet.append((town, tev, (i or {}).get("headline") or "Only passing or boilerplate mentions."))
            continue
        if i: st, conf, reviewed = i["stance"], i.get("confidence"), True
        else:
            st = hand.get(town, {}).get("stance") or auto_stance(key, town, tev); conf, reviewed = "low", False
        recent = sum(1 for x in tev if (x.get("date") or "") >= cut)
        last = next((x["date"] for x in tev if x.get("date")), None)
        cards.append(dict(town=town, st=st, conf=conf, reviewed=reviewed, i=i or {}, evs=tev, recent=recent, last=(i or {}).get("last_date") or last))
        mapd[town] = dict(st=st, n=len(tev), r=recent, last=last)
    cards.sort(key=lambda c: (-c["recent"], c["last"] or "" ) , reverse=False)
    cards.sort(key=lambda c: (c["recent"], c["last"] or ""), reverse=True)
    tally = {s: sum(1 for c in cards if c["st"] == s) for s in STANCE_ORDER}

    def snip(s): return f'<p class="snip">…{e(s.get("pre", ""))}<mark>{e(s.get("hit", ""))}</mark>{e(s.get("post", ""))}…</p>'

    def card(c):
        i, t = c["i"], c["town"]
        lab = STANCE[c["st"]][0]
        conf = f'<span class="conf">{e(c["conf"])} confidence</span>' if c["reviewed"] else '<span class="conf">auto · not yet reviewed</span>'
        good = "".join(f"<li>{e(x)}</li>" for x in i.get("good") or [])
        bad = "".join(f"<li>{e(x)}</li>" for x in i.get("bad") or [])
        gb = f'<div class="gb"><div class="good"><b>The good</b><ul>{good or "<li class=none>Nothing cited</li>"}</ul></div><div class="bad"><b>The bad</b><ul>{bad or "<li class=none>Nothing cited</li>"}</ul></div></div>' if c["reviewed"] else ""
        k = i.get("key") or {}
        keyrec = f'<p class="key">Most telling: <a href="{e(k["url"])}" target="_blank" rel="noopener">{e(k.get("board") or "record")}, {e(k.get("date") or "undated")}</a>{(" — “" + e(k["phrase"]) + "”") if k.get("phrase") else ""}</p>' if k.get("url") else ""
        docs = "".join(f"""<li><span class="d">{e(x.get("date") or "undated")}</span> <span class="b">{e(BOARD.get(x.get("board"), x.get("board") or ""))} · {e(x.get("type") or "")}</span>
<a href="{e(x["url"])}" target="_blank" rel="noopener">{e((x.get("title") or x["url"]).replace(" | ", " · ")[:150])}</a>{"".join(snip(s) for s in x["snippets"][:1])}</li>""" for x in c["evs"])
        n = len(c["evs"])
        return f"""<article class="tcardx" id="t-{slug(t)}" data-town="{e(t)}" data-st="{c["st"]}" data-recent="{c["recent"]}" data-last="{e(c["last"] or "")}" data-n="{n}">
<div class="th"><h3><a href="../../towns/{slug(t)}/index.html">{e(t)}</a></h3><span class="stance {CLS[c["st"]]}">{e(lab)}</span>{conf}
<span class="act">{n} record{"s" if n != 1 else ""}{f' · <b>{c["recent"]} in {window} days</b>' if c["recent"] else ""} · latest {e(c["last"] or "undated")}</span></div>
{f'<p class="hl">{e(i["headline"])}</p>' if i.get("headline") else ""}
{f'<div class="think"><b>What they seem to be thinking</b><p>{e(i["thinking"])}</p></div>' if i.get("thinking") else ""}
{gb}{keyrec}<details><summary>The records ({n})</summary><ol class="docs">{docs}</ol></details></article>"""

    chips = "".join(f'<button type="button" class="fchip" data-f="{s}" aria-pressed="false"><span class="stance {CLS[s]}">{e(STANCE[s][0])}</span><b>{tally[s]}</b></button>' for s in STANCE_ORDER if tally[s])
    qlist = "".join(f'<li><a href="../../towns/{slug(t)}/index.html">{e(t)}</a> <span class="qn">{len(v)}</span> <span class="qh">{e(h)}</span></li>' for t, v, h in sorted(quiet))
    body = f"""<header class="hd"><div class="eyebrow">Topic · New Hampshire · public record</div><h1>{e(label)}</h1><p class="lede">{e(desc)}</p></header>
<div class="stats"><div><b>{len(cards)}</b><span>towns actually discussing it</span></div><div><b>{sum(len(c["evs"]) for c in cards)}</b><span>records in those towns</span></div>
<div><b>{sum(c["recent"] for c in cards)}</b><span>in the last {window} days</span></div><div><b>{len(quiet)}</b><span>towns with passing mentions only</span></div></div>
<section class="mapsplit">
 <div class="mappanel"><div class="mctl" id="mctl"></div><svg class="nhmap" id="map" role="img" aria-label="Map of New Hampshire towns colored by stance on {e(label)}"></svg>
  <p class="mhint">Scroll or pinch to zoom, drag to move. Click a town to jump to it.</p></div>
 <div class="mapside"><h2>Where towns stand</h2><div class="fchips" id="fchips">{chips}</div>
  <p class="note">Click a stance to filter the map and list. "What they seem to be thinking" is our read of the records, not the town's words. Stances: against = moratorium or ban proposed or adopted; regulating = writing rules for where and how; leaning = language one way, no formal action.</p>
  <div class="lctl"><input type="search" id="q" placeholder="Find a town" aria-label="Find a town"><select id="sort" aria-label="Sort towns"><option value="recent">Most recent activity</option><option value="n">Most records</option><option value="az">A–Z</option></select></div></div>
</section>
<section><h2>Town by town</h2><div class="tlist" id="tlist">{"".join(card(c) for c in cards) or '<p class="empty">No town has discussed this yet.</p>'}</div>
{f'<details class="quiet"><summary>{len(quiet)} towns mention it only in passing or boilerplate</summary><p class="note">Emergency plans, standard definitions, resolutions on other subjects and similar. Listed so nothing is hidden.</p><ul>{qlist}</ul></details>' if quiet else ""}</section>
<script src="../../assets/nh-towns.js"></script><script src="../../assets/mapkit.js"></script>
<script>
(function(){{
const T={json.dumps(mapd, ensure_ascii=False, separators=(",", ":"))};
const geo=window.NH_GEO, svg=document.getElementById("map"), list=document.getElementById("tlist");
const on=new Set(); let sel=null;
const show=t=>!on.size||on.has(T[t].st);
let m; m=NHMap(svg,geo,{{views:{{"Southern tier":geo.views.south,"Seacoast":geo.views.sea,"Lakes & Concord":geo.views.lakes,"Upper Valley":geo.views.uv}},controls:document.getElementById("mctl"),
  labelTowns:()=>new Set(Object.keys(T).filter(show)),
  onDraw(){{for(const [t,d] of Object.entries(T)){{const p=m&&m.townEl(t);if(!p)continue;p.setAttribute("class","t s-"+d.st+(show(t)?"":" dim")+(sel===t?" on":""));}}}}}});
for(const t in T){{const p=m.townEl(t);if(!p)continue;p.style.cursor="pointer";p.addEventListener("click",()=>pick(t,true));}}
m.redraw();
function pick(t,scroll){{sel=t;m.redraw();list.querySelectorAll(".tcardx.on").forEach(x=>x.classList.remove("on"));const c=list.querySelector(`[data-town="${{CSS.escape(t)}}"]`);if(c){{c.classList.add("on");if(scroll)c.scrollIntoView({{behavior:"smooth",block:"start"}});}}}}
list.querySelectorAll(".tcardx").forEach(c=>c.addEventListener("click",ev=>{{if(ev.target.closest("a,summary"))return;const t=c.dataset.town;pick(t,false);m.focusTown(t,120);}}));
function filter(){{const q=document.getElementById("q").value.trim().toLowerCase();list.querySelectorAll(".tcardx").forEach(c=>{{c.hidden=!(show(c.dataset.town)&&(!q||c.dataset.town.toLowerCase().includes(q)));}});m.redraw();}}
document.querySelectorAll("#fchips .fchip").forEach(b=>b.addEventListener("click",()=>{{const f=b.dataset.f;on.has(f)?on.delete(f):on.add(f);b.setAttribute("aria-pressed",on.has(f));filter();}}));
document.getElementById("q").addEventListener("input",filter);
document.getElementById("sort").addEventListener("change",ev=>{{const k=ev.target.value,cs=[...list.querySelectorAll(".tcardx")];
 cs.sort((a,b)=>k==="az"?a.dataset.town.localeCompare(b.dataset.town):k==="n"?b.dataset.n-a.dataset.n:(b.dataset.recent-a.dataset.recent)||b.dataset.last.localeCompare(a.dataset.last));cs.forEach(c=>list.appendChild(c));}});
const h=decodeURIComponent(location.hash.slice(1));if(h){{const c=document.getElementById(h);if(c)pick(c.dataset.town,true);}}
}})();
</script>"""
    return body, len(cards), sum(len(c["evs"]) for c in cards), sum(c["recent"] for c in cards), [c["town"] for c in cards[:4]]


def housing_map(hdb, e):
    """Big housing builds: projects over 15 units from meeting records, plus Census 5+ unit permits by town."""
    projects = (load("big_builds.json", {}) or {}).get("projects", [])
    years = [str(y) for y in range(dt.date.today().year - 5, dt.date.today().year + 1)]
    permits, last_month = {}, None
    for town, period, b5, u5, v5 in hdb.execute("SELECT town,period,b5,u5,v5 FROM permits WHERE kind='year' AND u5>0"):
        if period in years: permits.setdefault(town, {})[period] = [b5, u5, v5]
    have_year = {r[0] for r in hdb.execute("SELECT DISTINCT period FROM permits WHERE kind='year'")}
    for y in years:
        if y in have_year: continue
        for town, b5, u5, v5, mx in hdb.execute("SELECT town,sum(b5),sum(u5),sum(v5),max(period) FROM permits WHERE kind='month' AND period LIKE ? GROUP BY town HAVING sum(u5)>0", (y + "-%",)):
            permits.setdefault(town, {})[y] = [b5, u5, v5]
        last_month = hdb.execute("SELECT max(period) FROM permits WHERE kind='month' AND period LIKE ?", (y + "-%",)).fetchone()[0] or last_month
    ylab = {y: y for y in years}
    if last_month: ylab[last_month[:4]] = f"{last_month[:4]} (through {dt.date(int(last_month[:4]), int(last_month[5:7]), 1):%b})"
    D = dict(projects=projects, permits=permits, years=years, ylab=ylab)
    yr_css = "".join(f".y{i}{{--c:var(--y{i})}}" for i in range(len(years)))
    body = f"""<header class="hd"><div class="eyebrow">Housing · <a href="../index.html">new construction</a> · map</div><h1>Big housing builds</h1>
<p class="lede">Housing projects in New Hampshire with more than 15 units, and where they cluster. Bubble size is units; color is when it started, from faded ({years[0]}) to deep ({years[-1]}).</p></header>
<div class="stats" id="tally"></div>
<section class="mapsplit wide">
 <div class="mappanel"><div class="mctl" id="mctl"></div>
  <div class="mctl" id="layers"><span class="ml">Show</span></div><div class="mctl" id="years"><span class="ml">Started</span></div>
  <svg class="nhmap" id="map" role="img" aria-label="Map of New Hampshire with housing project bubbles"></svg>
  <p class="mhint">Scroll or pinch to zoom, drag to move. Solid bubbles are projects; dashed bubbles are a town's permitted 5+ unit buildings.</p></div>
 <div class="mapside"><h2>Where it clusters</h2><ul class="hot" id="hot"></ul>
  <p class="note">Proposed = units in projects named in planning and zoning records (some never get built). Permitted = units in 5+ unit buildings with a building permit (Census). Click a town to zoom to it.</p></div>
</section>
<section><h2>Projects from meeting records</h2><div class="mctl" id="statusf"><span class="ml">Status</span></div>
<div class="tablebox"><table class="ptab" id="tbl"><thead><tr><th data-k="units">Units</th><th data-k="name">Project</th><th data-k="town">Town</th><th data-k="type">Type</th><th data-k="status">Status</th><th data-k="first">First seen</th><th>Source</th></tr></thead><tbody></tbody></table></div>
<p class="note">Projects come from planning board, ZBA and select board records, which start in mid-2023 for most towns (a few older projects appear because later meetings cite them). Each was checked against its source text and duplicates merged; first seen is the earliest meeting that names it. Records almost never state construction cost, so dollar value comes from the permit layer. Pins marked approx. sit at the street or town center. Permits: U.S. Census Building Permits Survey, units in 5+ unit buildings; towns that don't report are missing.</p></section>
<script src="../../assets/nh-towns.js"></script><script src="../../assets/mapkit.js"></script>
<script>
(function(){{
const D={json.dumps(D, ensure_ascii=False, separators=(",", ":"))};
const geo=window.NH_GEO, Y=D.years, yi=y=>Math.max(0,Y.indexOf(y)), col=y=>`var(--y${{yi(y)}})`;
const fmt=n=>n==null?"":n.toLocaleString("en-US"), money=n=>n?"$"+(n>=1e9?(n/1e9).toFixed(2)+"B":n>=1e6?(n/1e6).toFixed(n>=1e7?0:1)+"M":fmt(n)):"";
const DEAD=new Set(["denied","withdrawn"]);
const st={{layers:{{projects:true,permits:true}},years:new Set(Y),status:"active",sel:null,sort:["units",-1]}};
const h=(t,a={{}},x)=>{{const e=document.createElement(t);for(const k in a)e.setAttribute(k,a[k]);if(x!=null)e.textContent=x;return e;}};
const tip=h("div",{{class:"mtip",hidden:""}});document.body.append(tip);
const vis=()=>D.projects.filter(p=>st.years.has(p.first.slice(0,4))&&(st.status==="all"||(st.status==="active"?!DEAD.has(p.status):DEAD.has(p.status))));
function tipAt(e,nodes){{tip.replaceChildren(...nodes);tip.hidden=false;tip.style.left=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8)+"px";tip.style.top=Math.min(e.clientY+14,innerHeight-tip.offsetHeight-8)+"px";}}
const m=NHMap(document.getElementById("map"),geo,{{views:{{"Manchester–Nashua":geo.views.south,"Seacoast":geo.views.sea,"Lakes & Concord":geo.views.lakes,"Upper Valley":geo.views.uv}},controls:document.getElementById("mctl"),
 labelTowns:()=>new Set(vis().map(p=>p.town)),
 onDraw(g,z,el){{
  const k=0.95*Math.min(Math.sqrt(z),3)/z, items=[];
  if(st.layers.permits)for(const [t,ys] of Object.entries(D.permits)){{let u=0,w=0,v=0;for(const y of Y)if(st.years.has(y)&&ys[y]){{u+=ys[y][1];w+=ys[y][1]*+y;v+=ys[y][2];}}
   if(!u||!geo.towns[t])continue;const c=geo.towns[t].c;items.push({{town:t,u,v,x:c[0],y:c[1],yr:String(Math.round(w/u)),r:k*1.15*Math.sqrt(u)}});}}
  if(st.layers.projects)for(const p of vis())items.push({{p,x:p.x,y:p.y,yr:p.first.slice(0,4),r:k*1.15*Math.sqrt(p.units||1)}});
  items.sort((a,b)=>b.r-a.r);
  for(const it of items){{const c=el("circle",{{cx:it.x,cy:it.y,r:Math.max(it.r,2.2/z),class:"bub"+(it.p?"":" town")+(it.p&&DEAD.has(it.p.status)?" dead":"")+(it.p&&st.sel===it.p.id?" on":""),fill:col(it.yr)}},g);
   const nodes=it.p?[h("b",{{}},it.p.name||it.p.address),h("br"),`${{it.p.address}}, ${{it.p.town}}`,h("br"),`${{fmt(it.p.units)}} units · ${{it.p.status}} · first seen ${{it.p.first}}`]
     :[h("b",{{}},it.town+" — building permits"),h("br"),`${{fmt(it.u)}} units in 5+ unit buildings · ${{money(it.v)}} permitted value`];
   c.addEventListener("mousemove",e=>tipAt(e,nodes));c.addEventListener("mouseleave",()=>tip.hidden=true);
   c.addEventListener("click",()=>it.p?select(it.p.id,true):m.focusTown(it.town));}}
 }}}});
function select(id,scroll){{st.sel=st.sel===id?null:id;m.redraw();table();if(scroll&&st.sel!=null)document.querySelector(`tr[data-id="${{id}}"]`)?.scrollIntoView({{block:"center",behavior:"smooth"}});}}
function table(){{const [k,d]=st.sort,tb=document.querySelector("#tbl tbody");tb.replaceChildren();
 for(const p of vis().sort((a,b)=>{{const A=a[k]??"",B=b[k]??"";return(A>B?1:A<B?-1:0)*d;}})){{
  const tr=h("tr",{{"data-id":p.id}});if(st.sel===p.id)tr.className="on";
  const nm=h("td");nm.append(h("span",{{class:"dot",style:`background:${{col(p.first.slice(0,4))}}`}}),h("b",{{}},p.name||p.address));if(p.name)nm.append(h("br"),h("small",{{}},p.address));if(p.prec!=="address")nm.append(h("span",{{class:"approx"}},"approx. pin"));
  const src=h("td");src.append(h("a",{{href:p.url,target:"_blank",rel:"noopener"}},"record"));
  tr.append(h("td",{{class:"n"}},fmt(p.units)),nm,h("td",{{}},p.town),h("td",{{}},p.type),h("td",{{class:"stt"}},p.status),h("td",{{class:"n"}},p.first),src);
  tr.addEventListener("click",e=>{{if(e.target.tagName!=="A"){{select(p.id);m.focusTown(p.town,120);}}}});tb.append(tr);}}}}
function hot(){{const by={{}};for(const p of vis()){{const b=by[p.town]||={{town:p.town,p:0,q:0}};b.p+=p.units||0;}}
 for(const [t,ys] of Object.entries(D.permits)){{let u=0;for(const y of Y)if(st.years.has(y)&&ys[y])u+=ys[y][1];if(u)(by[t]||={{town:t,p:0,q:0}}).q=u;}}
 const rows=Object.values(by).sort((a,b)=>(b.p+b.q)-(a.p+a.q)).slice(0,18),mx=Math.max(1,...rows.map(r=>r.p+r.q)),ul=document.getElementById("hot");ul.replaceChildren();
 for(const r of rows){{const li=h("li",{{tabindex:0}});li.append(h("span",{{class:"nm"}},r.town),h("span",{{class:"n"}},`${{fmt(r.p)}} proposed · ${{fmt(r.q)}} permitted`));
  const bar=h("span",{{class:"bar"}});bar.append(h("i",{{style:`width:${{100*r.p/mx}}%;background:var(--y${{Y.length-2}})`}}),h("i",{{style:`width:${{100*r.q/mx}}%;background:var(--y1)`}}));li.append(bar);
  li.addEventListener("click",()=>m.focusTown(r.town));li.addEventListener("keydown",e=>{{if(e.key==="Enter")m.focusTown(r.town);}});ul.append(li);}}}}
function tally(){{const ps=vis();let pu=0;for(const p of ps)pu+=p.units||0;let tu=0,tv=0;for(const ys of Object.values(D.permits))for(const y of Y)if(st.years.has(y)&&ys[y]){{tu+=ys[y][1];tv+=ys[y][2];}}
 const t=document.getElementById("tally");t.replaceChildren();for(const [n,l] of [[ps.length,"projects over 15 units"],[fmt(pu),"units proposed"],[fmt(tu),"units permitted in 5+ unit buildings"],[money(tv),"permitted construction value"]]){{const d=h("div");d.append(h("b",{{}},n),h("span",{{}},l));t.append(d);}}}}
function all(){{m.redraw();hot();table();tally();}}
const chip=(p,l,on,f)=>{{const b=h("button",{{type:"button",class:"mchip","aria-pressed":on}},l);b.addEventListener("click",()=>f(b));p.append(b);return b;}};
for(const [k,l] of [["projects","Projects"],["permits","Town permits"]])chip(document.getElementById("layers"),l,true,b=>{{st.layers[k]=!st.layers[k];b.setAttribute("aria-pressed",st.layers[k]);all();}});
for(const y of Y){{const b=chip(document.getElementById("years"),"",true,b=>{{st.years.has(y)?st.years.delete(y):st.years.add(y);b.setAttribute("aria-pressed",st.years.has(y));all();}});b.classList.add("yr");b.append(h("i",{{style:`background:${{col(y)}}`}}),D.ylab[y]);}}
const sb={{}};for(const [k,l] of [["active","Active & approved"],["dead","Denied or withdrawn"],["all","All"]])sb[k]=chip(document.getElementById("statusf"),l,st.status===k,()=>{{st.status=k;for(const j in sb)sb[j].setAttribute("aria-pressed",j===k);all();}});
document.querySelectorAll("#tbl th[data-k]").forEach(th=>th.addEventListener("click",()=>{{const k=th.dataset.k;st.sort=[k,st.sort[0]===k?-st.sort[1]:(k==="units"||k==="first"?-1:1)];table();}}));
all();
}})();
</script>"""
    return body
