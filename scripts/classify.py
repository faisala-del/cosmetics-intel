"""Uses the Anthropic API to tag, summarise and digest fetched items.

Design rules baked into the prompt:
  * Claude may only use the title and snippet it is given. It must not add
    numbers, dates or facts from memory. Items with only a headline get
    confidence "low" so the website can flag them.
  * Output is strict JSON so a bad response can be detected and retried.
"""
from __future__ import annotations

import json
import time

SECTIONS = {
    "market": "Market size, growth, consumer trends, regional demand",
    "ingredients": "Ingredient news: new, trending, restricted, banned, safety opinions",
    "technology": "Biotech, AI, delivery systems, sustainability, stability science, devices",
    "formulation": "New formulas, supplier launches, patents, reformulation drivers",
    "news": "Product launches, M&A, partnerships, brand moves, leadership changes",
    "company": "Earnings, guidance and announcements of listed companies",
    "regulation": "Laws, rules, guidance, enforcement and regulator actions",
    "pharma": "Ingredients or products crossing the drug/cosmetic boundary: classification, actives used in both, borderline products",
}
REGIONS = ["India", "EU", "UK", "US", "Canada", "China", "Japan", "Korea", "ASEAN", "Global"]
CATEGORIES = ["skin care", "sun care", "hair care", "fragrance & colour", "oral & hygiene"]

SYSTEM = f"""You are an analyst for cosmetics R&D and regulatory-affairs teams.
You receive a JSON list of news items (id, title, snippet, source, region_hint, section_hint).
Return ONLY a JSON array with one object per item, in the same order, with these keys:
  id            - copy from input
  relevant      - true only if the item is about cosmetics, personal care, beauty companies, or ingredients/products that cross between pharma and cosmetics; otherwise false
  section       - one of {json.dumps(list(SECTIONS))}
  regions       - list from {json.dumps(REGIONS)}; use "Global" if no single region applies
  categories    - list from {json.dumps(CATEGORIES)}; empty list if none apply
  regulatory    - true only if about a law, rule, regulator action, safety opinion or enforcement
  borderline    - true if it concerns the drug-versus-cosmetic boundary (OTC drug vs cosmetic, medicinal-by-function, ingredients used in both)
  headline      - clear headline, at most 110 characters, in your own words
  summary       - at most 35 words, in your own words
  ingredients   - list of named ingredients mentioned (may be empty)
  companies     - list of named companies mentioned (may be empty)
  confidence    - "high" if the snippet has real detail, "low" if you only had a headline

Section guide: {json.dumps(SECTIONS)}

Hard rules:
- Use only the title and snippet provided. Do not add numbers, dates, names or facts from memory.
- If only a headline is available, restate it plainly and set confidence to "low".
- Never copy more than six consecutive words from the input.
- Output the JSON array and nothing else: no markdown fences, no commentary."""


def get_client():
    import anthropic  # imported lazily so tests can run without the SDK
    return anthropic.Anthropic()


def _extract_json(text: str):
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON found in model output")
    return json.loads(text[start:end + 1])


def _call(client, model: str, system: str, user: str, max_tokens: int, retries: int = 3) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            msg = client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        except Exception as exc:  # rate limit, overload, network
            last = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Claude call failed after {retries} tries: {last}")


def _as_list(value, allowed=None) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(v).strip() for v in value if str(v).strip()]
    if allowed is not None:
        out = [v for v in out if v in allowed]
    return out


def _coerce(row: dict, item: dict) -> dict:
    hint = item.get("section_hint")
    section = row.get("section")
    if section not in SECTIONS:
        section = hint if hint in SECTIONS else "news"
    regions = _as_list(row.get("regions"), REGIONS) or [item.get("region_hint") or "Global"]
    return {
        "relevant": bool(row.get("relevant", False)),
        "section": section,
        "regions": regions,
        "categories": _as_list(row.get("categories"), CATEGORIES),
        "regulatory": bool(row.get("regulatory", False)),
        "borderline": bool(row.get("borderline", False)),
        "headline": str(row.get("headline") or item["title"])[:140],
        "summary": str(row.get("summary") or "")[:400],
        "ingredients": _as_list(row.get("ingredients"))[:8],
        "companies": _as_list(row.get("companies"))[:8],
        "confidence": "high" if row.get("confidence") == "high" else "low",
    }


def classify_items(client, model: str, items: list[dict], batch_size: int) -> dict[str, dict]:
    """Returns {item_id: classification}. Items Claude fails on are skipped
    (they are retried on the next run because they are not cached)."""
    results: dict[str, dict] = {}
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        payload = [{k: it[k] for k in ("id", "title", "snippet", "source", "region_hint", "section_hint")}
                   for it in batch]
        try:
            text = _call(client, model, SYSTEM, json.dumps(payload, ensure_ascii=False), 4000)
            rows = _extract_json(text)
        except Exception as exc:
            print(f"  ! batch {i // batch_size + 1} failed: {exc}")
            continue
        by_id = {r.get("id"): r for r in rows if isinstance(r, dict)}
        for it in batch:
            if it["id"] in by_id:
                results[it["id"]] = _coerce(by_id[it["id"]], it)
        print(f"  classified batch {i // batch_size + 1}: {len(batch)} items")
    return results


DIGEST_SYSTEM = """You write the 'what changed' overview for a cosmetics R&D and regulatory team.
Input: a JSON list of items (id, section, headline, regulatory flag, date).
Return ONLY a JSON array of 5 to 7 objects: {"text": "...", "ids": ["..."]}.
Each text is one sentence (max 30 words) naming the development and why it matters to formulators or regulatory staff.
Prioritise regulatory changes, then ingredient safety, then company or market news.
Use only the headlines provided; add no outside facts. ids must come from the input and support the sentence."""


def make_digest(client, model: str, items: list[dict]) -> list[dict]:
    top = sorted(items, key=lambda x: (x["regulatory"], x["published"]), reverse=True)[:80]
    if not top:
        return []
    payload = [{"id": x["id"], "section": x["section"], "headline": x["headline"],
                "regulatory": x["regulatory"], "date": x["published"][:10]} for x in top]
    try:
        text = _call(client, model, DIGEST_SYSTEM, json.dumps(payload, ensure_ascii=False), 1500)
        rows = _extract_json(text)
    except Exception as exc:
        print(f"  ! digest failed: {exc}")
        return []
    valid = {x["id"] for x in top}
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get("text"):
            ids = [i for i in r.get("ids", []) if i in valid]
            out.append({"text": str(r["text"])[:300], "ids": ids})
    return out
