// Ask the records: BM25 search over quoted passages from one town's minutes and agendas.
// Results are always passages from the record with a link to the source document; nothing is generated.
(function () {
  const C = window.CIVIC, $ = (s) => document.querySelector(s);
  const STOP = new Set("a an and are as at be but by for from has have in is it its of on or that the this to was were will with not no yes we they he she i you our their his her which who what when where how than then there these those been being do did does so if into about over under after before also any all can could would should may might must shall up out per via".split(" "));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const stem = (w) => w.replace(/(ings?|ed|es|s)$/, (m, _, i) => (w.length - m.length >= 3 ? "" : m));
  const toks = (s) => (s.toLowerCase().match(/[a-z0-9]+/g) || []).filter((w) => !STOP.has(w) && w.length > 1).map(stem);
  let D = null, idx = null, len = null, avg = 0;

  function build(data) {
    D = data; idx = new Map(); len = new Uint16Array(data.p.length);
    data.p.forEach(([, text], i) => {
      const t = toks(text); len[i] = Math.min(t.length, 65535);
      const tf = new Map(); t.forEach((w) => tf.set(w, (tf.get(w) || 0) + 1));
      tf.forEach((n, w) => { let a = idx.get(w); if (!a) idx.set(w, (a = [])); a.push(i, n); });
    });
    avg = len.reduce((a, b) => a + b, 0) / Math.max(1, len.length);
    const boards = [...new Set(data.docs.map((d) => d[1]))].sort();
    $("#fb").insertAdjacentHTML("beforeend", boards.map((b) => `<option value="${esc(b)}">${esc(C.boards[b] || b)}</option>`).join(""));
    $("#astat").textContent = `${data.docs.length.toLocaleString()} documents from ${data.from} on, searchable now.`;
  }

  function search(q, board) {
    const terms = [...new Set(toks(q))]; if (!terms.length) return [];
    const N = len.length, k1 = 1.2, b = 0.75, score = new Map(), hits = new Map();
    for (const w of terms) {
      const a = idx.get(w); if (!a) continue;
      const df = a.length / 2, idf = Math.log(1 + (N - df + 0.5) / (df + 0.5));
      for (let j = 0; j < a.length; j += 2) {
        const i = a[j], tf = a[j + 1];
        if (board && D.docs[D.p[i][0]][1] !== board) continue;
        score.set(i, (score.get(i) || 0) + idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * len[i] / avg)));
        hits.set(i, (hits.get(i) || 0) + 1);
      }
    }
    const phrase = q.trim().toLowerCase().replace(/^"|"$/g, "");
    const out = [...score.entries()].map(([i, s]) => {
      if (hits.get(i) === terms.length) s *= 1.5;                       // every term present
      if (phrase.includes(" ") && D.p[i][1].toLowerCase().includes(phrase)) s *= 2; // exact phrase
      const d = D.docs[D.p[i][0]]; if (d[2] === "minutes") s *= 1.15;       // decisions live in minutes
      return [i, s];
    }).sort((x, y) => y[1] - x[1]);
    const perDoc = new Map(), res = [];                                   // at most 2 passages per document
    for (const [i, s] of out) {
      const di = D.p[i][0], n = perDoc.get(di) || 0; if (n >= 2) continue;
      perDoc.set(di, n + 1); res.push(i); if (res.length >= 12) break;
    }
    return { res, terms };
  }

  function mark(text, terms) {
    const re = new RegExp("\\b(" + terms.map((t) => t.replace(/[^a-z0-9]/g, "")).filter(Boolean).join("|") + ")[a-z]*", "gi");
    return esc(text).replace(re, "<mark>$&</mark>");
  }

  function run(q) {
    if (!D) return;
    const { res, terms } = search(q, $("#fb").value) || {};
    const box = $("#ares");
    if (!res || !res.length) {
      box.innerHTML = `<p class="empty">I don't see that in the records collected for ${esc(C.town)}. Try other words, a different board, or check the coverage notes below.</p>`;
      return;
    }
    box.innerHTML = res.map((i) => {
      const [di, text] = D.p[i], [date, board, type, title, url, draft] = D.docs[di];
      return `<article class="ev"><div class="top"><span class="date">${esc(date || "date unknown")}</span>${draft ? '<span class="tag draft">Draft minutes</span>' : ""}</div>
<div class="meta">${esc(C.boards[board] || board)} · ${esc(type)}</div>
<p class="snip">…${mark(text, terms)}…</p>
<a class="doc" href="${esc(url)}" target="_blank" rel="noopener">Source: ${esc(title || url)}</a></article>`;
    }).join("") + `<p class="note">Quotes from ${esc(C.town)}'s posted records, ranked by match. Open the source before relying on one. <a href="${esc(C.report)}" target="_blank" rel="noopener">Report an error</a>.</p>`;
  }

  $("#askf").addEventListener("submit", (ev) => { ev.preventDefault(); run($("#q").value); });
  $("#fb").addEventListener("change", () => $("#q").value && run($("#q").value));
  document.querySelectorAll(".ex").forEach((b) => b.addEventListener("click", () => { $("#q").value = b.textContent; run(b.textContent); }));
  fetch("records.json").then((r) => r.json()).then(build).catch(() => { $("#astat").textContent = "The search index could not be loaded."; });
})();
