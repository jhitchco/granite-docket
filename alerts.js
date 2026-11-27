// Alerts page: pick a town and topic, get the matching feed link.
(function () {
  const A = window.ALERTS, $ = (s) => document.querySelector(s);
  const BASE = "https://jhitchco.github.io/granite-docket/alerts/feeds/";
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  A.towns.forEach((t) => $("#at").insertAdjacentHTML("beforeend", `<option value="${esc(t)}">${esc(t)}</option>`));
  Object.entries(A.labels).forEach(([k, v]) => $("#ap").insertAdjacentHTML("beforeend", `<option value="${esc(k)}">${esc(v)}</option>`));
  const sl = (k) => (k === "energy-siting" ? k : A.slugs[k]);
  function update() {
    const t = $("#at").value, p = $("#ap").value;
    let fid, what;
    if (t && p) { fid = `${A.slugs[t]}--${sl(p)}`; what = `${t}, ${p === "energy-siting" ? "energy siting" : A.labels[p]}`; }
    else if (t) { fid = `town-${A.slugs[t]}`; what = `${t}, every topic`; }
    else if (p) { fid = p === "energy-siting" ? "energy-siting" : `topic-${sl(p)}`; what = `every town, ${p === "energy-siting" ? "energy siting" : A.labels[p]}`; }
    else { fid = "energy-siting"; what = "every town, energy siting"; }
    const url = BASE + fid + ".xml";
    const quiet = t && p && p !== "energy-siting" && !(A.combos[t] || []).includes(p) ? " No matches yet; the feed fills when one appears." : "";
    $("#aout").innerHTML = `<b>${esc(what)}</b>: <a href="feeds/${esc(fid)}.xml">${esc(url)}</a> · <a href="#" id="acopy">Copy link</a>${esc(quiet)}`;
    $("#acopy").onclick = (e) => { e.preventDefault(); copy(url, e.target); };
  }
  function copy(url, el) {
    try { navigator.clipboard.writeText(url).then(() => (el.textContent = "Copied")); } catch (_) { window.prompt("Copy this link", url); }
  }
  $("#at").onchange = update; $("#ap").onchange = update; update();
  document.querySelectorAll("a.copy").forEach((a) => (a.onclick = (e) => { e.preventDefault(); copy(a.dataset.url, a); }));
})();
