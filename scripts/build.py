"""Orchestrates one refresh.

    python -m scripts.build            full run (needs ANTHROPIC_API_KEY)
    python -m scripts.build --check    test every source, print counts, no Claude, no writes
    python -m scripts.build --rules    free mode: keyword tagging, no API key, no cost
    (with no ANTHROPIC_API_KEY set, free mode is used automatically)

Outputs:
    site/data/briefing.json   items + digest shown on the website
    site/data/stocks.json     price table
    data/cache.json           every item already classified (keeps costs low)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

from scripts import classify, classify_rules, fetch, stocks

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache.json"
OUT_BRIEFING = ROOT / "site" / "data" / "briefing.json"
OUT_STOCKS = ROOT / "site" / "data" / "stocks.json"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def gather(cfg: dict) -> tuple[list[dict], dict]:
    """Runs every fetcher. Returns (items, report) where report maps
    source name -> {"count": n} or {"error": "..."}."""
    ua = cfg["user_agent"]
    days = cfg["lookback_days"]
    max_n = cfg["max_per_source"]
    ncbi_key = os.environ.get("NCBI_API_KEY")
    items: list[dict] = []
    report: dict = {}

    def run(name: str, fn):
        try:
            got = fn()
            items.extend(got)
            report[name] = {"count": len(got)}
        except Exception as exc:
            report[name] = {"error": str(exc)[:200]}

    for f in cfg.get("feeds", []):
        run(f"feed: {f['name']}", lambda f=f: fetch.fetch_feed(f, days, ua, max_n))
    for q in cfg.get("google_news", []):
        run(f"news: {q['q'][:60]}",
            lambda q=q: fetch.fetch_google_news(q["q"], q.get("region", "Global"),
                                                q.get("section_hint", "news"), days, ua, max_n))
    for p in cfg.get("pubmed_queries", []):
        run(f"pubmed: {p['name']}",
            lambda p=p: fetch.fetch_pubmed(p["term"], p.get("section_hint", "technology"),
                                           days, ua, max_n, ncbi_key))
    for term in cfg.get("federal_register_terms", []):
        run(f"federal register: {term}",
            lambda term=term: fetch.fetch_federal_register(term, days, ua, max_n))
    return fetch.dedupe(items), report


def print_report(report: dict) -> None:
    ok = {k: v for k, v in report.items() if "count" in v}
    bad = {k: v for k, v in report.items() if "error" in v}
    print(f"\nSources working: {len(ok)} | failing: {len(bad)}")
    for name, v in ok.items():
        print(f"  ok  {v['count']:>3}  {name}")
    for name, v in bad.items():
        print(f"  ERR      {name}  ->  {v['error']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="test sources only")
    ap.add_argument("--rules", action="store_true", help="free keyword tagging, never call Claude")
    ap.add_argument("--no-stocks", action="store_true", help="skip stock prices")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    print("Fetching sources...")
    items, report = gather(cfg)
    print_report(report)
    print(f"\n{len(items)} unique items after de-duplication")

    if args.check:
        if not args.no_stocks:
            _, errs = stocks.fetch_all(cfg["stocks"])
            print(f"\nTickers failing: {len(errs)}")
            for e in errs:
                print("  ERR", e)
        return 0

    cache: dict = load_json(CACHE, {})
    today = dt.date.today().isoformat()
    use_llm = bool(os.environ.get("ANTHROPIC_API_KEY")) and not args.rules
    client = None

    if use_llm:
        print("\nMode: Claude tagging (API key found)")
        # Items tagged earlier by free rules are upgraded to Claude tagging, within the cap.
        todo = [i for i in items if i["id"] not in cache or cache[i["id"]].get("method") == "rules"]
    else:
        print("\nMode: free keyword tagging (no API key, or --rules). Summaries are limited to source snippets.")
        todo = [i for i in items if i["id"] not in cache]
    todo = todo[: cfg["max_new_items_per_run"]]

    if todo and use_llm:
        client = classify.get_client()
        print(f"Classifying {len(todo)} items with {cfg['claude']['classify_model']}...")
        results = classify.classify_items(client, cfg["claude"]["classify_model"], todo, cfg["batch_size"])
        for it in todo:
            if it["id"] in results:
                cache[it["id"]] = {**it, **results[it["id"]], "first_seen": today, "method": "claude"}
        write_json(CACHE, cache)
    elif todo:
        print(f"Tagging {len(todo)} items with keyword rules...")
        results = classify_rules.classify_items(todo)
        for it in todo:
            cache[it["id"]] = {**it, **results[it["id"]], "first_seen": today, "method": "rules"}
        write_json(CACHE, cache)

    if not items and not cache:
        print("Nothing fetched and nothing cached. Check the network and run --check.")
        return 1

    cutoff = (fetch.now_utc() - dt.timedelta(days=cfg["retain_days"])).isoformat()
    live = [v for v in cache.values() if v.get("relevant") and v["published"] >= cutoff]
    live.sort(key=lambda x: x["published"], reverse=True)

    digest: list[dict] = []
    if live and use_llm:
        client = client or classify.get_client()
        print("Writing digest with Claude...")
        digest = classify.make_digest(client, cfg["claude"]["digest_model"], live)
    if live and not digest:
        digest = classify_rules.make_digest(live)

    keep = ("id", "section", "headline", "summary", "url", "source", "published", "regions",
            "categories", "regulatory", "borderline", "ingredients", "companies", "confidence", "origin")
    write_json(OUT_BRIEFING, {
        "mode": "live",
        "generated_at": fetch.now_utc().isoformat(),
        "lookback_days": cfg["lookback_days"],
        "digest": digest,
        "items": [{k: v.get(k) for k in keep} for v in live],
        "source_report": report,
    })
    print(f"Wrote {len(live)} items to {OUT_BRIEFING.relative_to(ROOT)}")

    if not args.no_stocks:
        print("Fetching stock prices...")
        prev = load_json(OUT_STOCKS, None)
        data, errs = stocks.fetch_all(cfg["stocks"], prev)
        write_json(OUT_STOCKS, data)
        for e in errs:
            print("  ! ticker failed:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
