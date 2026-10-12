/* Cosmetics Intelligence Briefing: renders data/briefing.json and data/stocks.json.
   All text is inserted with textContent and links are checked, because feed
   content is untrusted. */
(function () {
  "use strict";

  var SECTIONS = [
    { key: "market", title: "1. Market trends", lede: "Size, growth, regions and consumer behaviour." },
    { key: "ingredients", title: "2. Ingredients", lede: "New, trending, restricted and banned ingredients, with the region each applies to." },
    { key: "technology", title: "3. New technologies", lede: "Biotech, AI, delivery systems, sustainability and stability science." },
    { key: "formulation", title: "4. Formulation updates", lede: "New formulations, supplier launches, patents and reformulation drivers." },
    { key: "news", title: "5. Beauty and personal care news", lede: "Launches, mergers and acquisitions, brand moves." },
    { key: "company", title: "6. Company updates", lede: "Earnings, guidance and announcements." },
    { key: "stocks", title: "7. Stock snapshot", lede: "Last close, daily change and 52-week range." },
    { key: "regulation", title: "8. Regulation by region", lede: "Drug and cosmetics law, rules and enforcement, grouped by region." },
    { key: "pharma", title: "9. Pharma and cosmetics crossover", lede: "Ingredients and products on the drug-versus-cosmetic boundary." }
  ];
  var REGIONS = ["India", "EU", "UK", "US", "Canada", "China", "Japan", "Korea", "ASEAN", "Global"];
  var CATEGORIES = ["skin care", "sun care", "hair care", "fragrance & colour", "oral & hygiene"];
  var PAGE = 12;

  var state = { regions: {}, cats: {}, regOnly: false, hiOnly: false, days: 0, q: "" };
  var data = { items: [], digest: [], mode: "live", generated_at: null };
  var stocks = null;
  var shown = {};

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function safeUrl(u) {
    try {
      var x = new URL(u);
      return (x.protocol === "https:" || x.protocol === "http:") ? x.href : null;
    } catch (e) { return null; }
  }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }
  function fmtNum(v, ccy) {
    if (v == null) return "—";
    try { return new Intl.NumberFormat(undefined, { style: "currency", currency: ccy, maximumFractionDigits: v < 10 ? 2 : 2 }).format(v); }
    catch (e) { return String(v); }
  }

  function matches(it) {
    var selR = Object.keys(state.regions).filter(function (k) { return state.regions[k]; });
    if (selR.length) {
      var regs = it.regions || [];
      var hit = regs.some(function (r) { return selR.indexOf(r) !== -1; }) || regs.indexOf("Global") !== -1;
      if (!hit) return false;
    }
    var selC = Object.keys(state.cats).filter(function (k) { return state.cats[k]; });
    if (selC.length && (it.categories || []).length) {
      if (!it.categories.some(function (c) { return selC.indexOf(c) !== -1; })) return false;
    }
    if (state.regOnly && !it.regulatory) return false;
    if (state.hiOnly && it.confidence !== "high") return false;
    if (state.days) {
      var age = (Date.now() - new Date(it.published).getTime()) / 86400000;
      if (age > state.days) return false;
    }
    if (state.q) {
      var hay = [it.headline, it.summary, (it.ingredients || []).join(" "), (it.companies || []).join(" "), it.source].join(" ").toLowerCase();
      if (hay.indexOf(state.q.toLowerCase()) === -1) return false;
    }
    return true;
  }

  function sectionItems(key) {
    return data.items.filter(function (it) {
      var inSection = key === "pharma" ? (it.section === "pharma" || it.borderline) : it.section === key;
      return inSection && matches(it);
    });
  }

  function renderItem(it) {
    var row = el("div", "item");
    var meta = el("div", "meta");
    meta.appendChild(el("span", "", fmtDate(it.published)));
    (it.regions || []).slice(0, 3).forEach(function (r) { meta.appendChild(el("span", "chip", r)); });
    if (it.regulatory) meta.appendChild(el("span", "chip flag", "Regulatory"));
    if (it.confidence !== "high") meta.appendChild(el("span", "chip warn", "Headline only"));
    row.appendChild(meta);

    var body = el("div");
    var h = el("h4");
    var url = safeUrl(it.url);
    if (url) {
      var a = el("a", "", it.headline);
      a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
      h.appendChild(a);
    } else { h.textContent = it.headline; }
    body.appendChild(h);
    if (it.summary) body.appendChild(el("p", "", it.summary));
    var tags = [];
    (it.ingredients || []).forEach(function (t) { tags.push(t); });
    (it.companies || []).forEach(function (t) { tags.push(t); });
    (it.categories || []).forEach(function (t) { tags.push(t); });
    if (tags.length) {
      var wrap = el("div", "tags");
      tags.slice(0, 8).forEach(function (t) { wrap.appendChild(el("span", "chip", t)); });
      body.appendChild(wrap);
    }
    body.appendChild(el("p", "src", "Source: " + (it.source || "unknown")));
    row.appendChild(body);
    return row;
  }

  function renderList(container, items, key) {
    var limit = shown[key] || PAGE;
    if (key === "regulation") {
      var groups = {};
      items.forEach(function (it) {
        var r = (it.regions && it.regions[0]) || "Global";
        (groups[r] = groups[r] || []).push(it);
      });
      REGIONS.forEach(function (r) {
        if (!groups[r]) return;
        container.appendChild(el("h3", "region", r + " (" + groups[r].length + ")"));
        groups[r].slice(0, limit).forEach(function (it) { container.appendChild(renderItem(it)); });
      });
      return;
    }
    items.slice(0, limit).forEach(function (it) { container.appendChild(renderItem(it)); });
    if (items.length > limit) {
      var btn = el("button", "more", "Show more (" + (items.length - limit) + " left)");
      btn.type = "button";
      btn.addEventListener("click", function () { shown[key] = limit + PAGE; render(); });
      container.appendChild(btn);
    }
  }

  function renderStocks(container) {
    if (!stocks || !stocks.groups) {
      container.appendChild(el("p", "empty", "No price data yet. It appears after the first refresh."));
      return;
    }
    stocks.groups.forEach(function (g) {
      var wrap = el("div", "tablewrap");
      var t = el("table");
      t.appendChild(el("caption", "", g.name));
      var thead = el("thead"), hr = el("tr");
      [["Company", ""], ["Symbol", ""], ["Last close", "num"], ["Day change", "num"], ["Date", ""], ["52-week range", "num"]].forEach(function (c) {
        hr.appendChild(el("th", c[1], c[0]));
      });
      thead.appendChild(hr); t.appendChild(thead);
      var tb = el("tbody");
      g.rows.forEach(function (r) {
        var tr = el("tr");
        tr.appendChild(el("td", "", r.name));
        tr.appendChild(el("td", "", r.symbol));
        tr.appendChild(el("td", "num", fmtNum(r.last, r.ccy)));
        var ch = el("td", "num");
        if (r.change_pct == null) { ch.textContent = "—"; }
        else {
          ch.textContent = (r.change_pct > 0 ? "+" : "") + r.change_pct.toFixed(2) + "%";
          ch.className = "num " + (r.change_pct >= 0 ? "up" : "down");
        }
        tr.appendChild(ch);
        var dtd = el("td", "", r.date || "—");
        if (r.stale) dtd.appendChild(el("span", "chip warn", "stale"));
        tr.appendChild(dtd);
        tr.appendChild(el("td", "num", r.low52 != null ? fmtNum(r.low52, r.ccy) + " – " + fmtNum(r.high52, r.ccy) : "—"));
        tb.appendChild(tr);
      });
      t.appendChild(tb); wrap.appendChild(t); container.appendChild(wrap);
    });
    container.appendChild(el("p", "src", "Prices are delayed, from Yahoo Finance via yfinance. Information only, not investment advice."));
  }

  function render() {
    var root = $("sections");
    root.textContent = "";
    var nav = $("nav");
    nav.textContent = "";
    SECTIONS.forEach(function (s) {
      var sec = el("section"); sec.id = s.key;
      sec.appendChild(el("h2", "", s.title));
      sec.appendChild(el("p", "lede", s.lede));
      var count = null;
      if (s.key === "stocks") { renderStocks(sec); }
      else {
        var items = sectionItems(s.key);
        count = items.length;
        if (!items.length) {
          sec.appendChild(el("p", "empty", data.items.length ? "Nothing matches the current filters." : "No items yet."));
        } else { renderList(sec, items, s.key); }
      }
      root.appendChild(sec);
      var li = el("li"), a = el("a");
      a.href = "#" + s.key;
      a.appendChild(el("span", "", s.title.replace(/^\d+\.\s*/, "")));
      if (count != null) a.appendChild(el("span", "n", String(count)));
      li.appendChild(a); nav.appendChild(li);
    });
    observe();
  }

  function renderDigest() {
    var box = $("digest-box"), ul = $("digest");
    ul.textContent = "";
    if (!data.digest || !data.digest.length) { box.hidden = true; return; }
    data.digest.forEach(function (d) {
      var li = el("li", "", d.text);
      var first = data.items.filter(function (i) { return d.ids && d.ids.indexOf(i.id) !== -1; })[0];
      var u = first && safeUrl(first.url);
      if (u) {
        li.appendChild(document.createTextNode(" "));
        var a = el("a", "", "Source"); a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer";
        li.appendChild(a);
      }
      ul.appendChild(li);
    });
    box.hidden = false;
  }

  function chips(containerId, values, store) {
    var c = $(containerId);
    values.forEach(function (v) {
      var b = el("button", "", v); b.type = "button"; b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", function () {
        store[v] = !store[v];
        b.setAttribute("aria-pressed", store[v] ? "true" : "false");
        shown = {}; render();
      });
      c.appendChild(b);
    });
  }

  function clearFilters() {
    state = { regions: {}, cats: {}, regOnly: false, hiOnly: false, days: 0, q: "" };
    document.querySelectorAll(".chips button").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
    $("f-reg").checked = false; $("f-hi").checked = false; $("f-days").value = "0"; $("f-q").value = "";
    shown = {}; render();
  }

  var io = null;
  function observe() {
    if (!("IntersectionObserver" in window)) return;
    if (io) io.disconnect();
    var links = {};
    document.querySelectorAll("nav.rail a").forEach(function (a) { links[a.getAttribute("href").slice(1)] = a; });
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          Object.keys(links).forEach(function (k) { links[k].removeAttribute("aria-current"); });
          if (links[e.target.id]) links[e.target.id].setAttribute("aria-current", "true");
        }
      });
    }, { rootMargin: "-20% 0px -70% 0px" });
    document.querySelectorAll("main section[id]").forEach(function (s) { io.observe(s); });
  }

  function load(path) {
    return fetch(path, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(path + " " + r.status);
      return r.json();
    });
  }

  function init() {
    chips("f-region", REGIONS, state.regions);
    chips("f-cat", CATEGORIES, state.cats);
    $("f-reg").addEventListener("change", function (e) { state.regOnly = e.target.checked; shown = {}; render(); });
    $("f-hi").addEventListener("change", function (e) { state.hiOnly = e.target.checked; shown = {}; render(); });
    $("f-days").addEventListener("change", function (e) { state.days = parseInt(e.target.value, 10) || 0; shown = {}; render(); });
    var t = null;
    $("f-q").addEventListener("input", function (e) {
      clearTimeout(t);
      var v = e.target.value.trim();
      t = setTimeout(function () { state.q = v; shown = {}; render(); }, 200);
    });
    $("f-clear").addEventListener("click", clearFilters);

    Promise.all([
      load("data/briefing.json").catch(function () { return null; }),
      load("data/stocks.json").catch(function () { return null; })
    ]).then(function (res) {
      if (res[0]) data = res[0];
      stocks = res[1];
      var asof = data.generated_at ? "Updated " + fmtDate(data.generated_at) : "Not yet refreshed";
      $("asof").textContent = asof;
      var banner = $("banner");
      if (!res[0]) {
        banner.textContent = "Could not load data/briefing.json. Run the refresh workflow, or serve this folder over http (not file://).";
        banner.hidden = false;
      } else if (data.mode === "seed") {
        banner.textContent = "Showing starter data from the 12 Oct 2026 research. It is replaced by live items after the first scheduled refresh.";
        banner.hidden = false;
      }
      $("foot-note").textContent = data.generated_at ? "Data generated " + new Date(data.generated_at).toUTCString() + "." : "";
      renderDigest();
      render();
    });
  }
  init();
})();
