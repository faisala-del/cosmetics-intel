"""Free, no-API classifier based on keyword rules.

Trade-offs compared with the Claude classifier:
  + costs nothing, works offline, deterministic
  - cannot write summaries (uses the source snippet when there is one)
  - misreads nuance (a headline mentioning "ban" is flagged regulatory even if
    the ban is about something else), so expect more noise
Edit the keyword lists below to tune it for your topics.
"""
from __future__ import annotations

import re

from scripts.classify import CATEGORIES, REGIONS, SECTIONS

# --- keyword lists (lower case; matched as whole words or phrases) ------------
CORE = [
    "cosmetic", "cosmetics", "beauty", "skincare", "skin care", "personal care", "sunscreen",
    "fragrance", "perfume", "hair care", "haircare", "hair dye", "toothpaste", "oral care",
    "mouthwash", "makeup", "lipstick", "dermocosmetic", "cosmeceutical", "moisturiser",
    "moisturizer", "serum", "shampoo", "uv filter", "anti-aging", "anti-ageing", "mocra",
    "sccs", "cdsco", "skin", "skin ageing", "skin aging", "toothpaste", "deodorant", "hair loss",
]
STRONG_INGREDIENTS = [
    "retinol", "retinoid", "niacinamide", "hyaluronic acid", "bemotrizinol", "avobenzone", "oxybenzone",
    "octinoxate", "benzophenone", "bakuchiol", "ceramide", "hydroquinone", "tretinoin", "minoxidil",
    "bimatoprost", "prostaglandin", "kojic acid", "phenoxyethanol", "triclosan", "paraben",
]
REGION_WORDS = {
    "India": ["india", "indian", "cdsco", "bis", "nykaa", "hindustan unilever", "honasa", "dabur"],
    "EU": ["eu", "european", "sccs", "1223/2009", "echa", "omnibus", "brussels", "cjeu"],
    "UK": ["uk", "britain", "british", "opss", "mhra"],
    "US": ["fda", "mocra", "u.s.", "us", "california", "federal register", "ftc", "epa"],
    "Canada": ["canada", "canadian", "health canada"],
    "China": ["china", "chinese", "nmpa", "proya", "c-beauty"],
    "Japan": ["japan", "japanese", "mhlw", "shiseido", "kao", "kose", "j-beauty"],
    "Korea": ["korea", "korean", "mfds", "k-beauty", "amorepacific", "lg h&h"],
    "ASEAN": ["asean", "indonesia", "bpom", "singapore", "malaysia", "thailand", "vietnam", "philippines"],
}
CATEGORY_WORDS = {
    "skin care": ["skin", "skincare", "anti-aging", "anti-ageing", "retinol", "retinoid", "peptide", "serum",
                  "moisturiser", "moisturizer", "wrinkle", "niacinamide", "hyaluronic", "ceramide"],
    "sun care": ["sunscreen", "spf", "uv filter", "sun care", "bemotrizinol", "avobenzone", "octocrylene",
                 "oxybenzone", "octinoxate", "benzophenone"],
    "hair care": ["hair", "shampoo", "scalp", "hair dye", "colourant", "keratin", "hair straightening"],
    "fragrance & colour": ["fragrance", "perfume", "allergen", "lipstick", "makeup", "mascara", "foundation",
                           "eyelash", "eyebrow", "nail", "colour cosmetics", "color cosmetics"],
    "oral & hygiene": ["toothpaste", "mouthwash", "oral care", "dentifrice", "fluoride", "hydroxyapatite",
                       "deodorant", "hygiene"],
}
REGULATORY_WORDS = [
    "regulation", "regulatory", "ban", "banned", "bans", "restrict", "restriction", "prohibit", "prohibited",
    "rule", "rules", "directive", "guidance", "sccs", "opinion", "recall", "warning", "enforcement",
    "compliance", "omnibus", "annex", "mocra", "cdsco", "nmpa", "mhlw", "mfds", "bpom", "notice",
    "circular", "amendment", "law", "legislation", "proposed rule", "final rule", "withdrawn",
    "approve", "approval", "approved", "authorise", "authorize", "authorisation", "authorization",
]
BORDERLINE_STRONG = [
    "prostaglandin", "bimatoprost", "minoxidil", "hydroquinone", "tretinoin", "cosmeceutical",
    "dermocosmetic", "borderline", "medicinal product", "quasi-drug", "otc drug", "injectable",
    "botulinum", "drug vs cosmetic", "drug or cosmetic",
]
EARNINGS_WORDS = ["results", "earnings", "profit", "revenue", "sales", "quarter", "guidance", "fy2", "h1", "h2",
                  "full-year", "full year", "half-year", "outlook"]
DEAL_WORDS = ["acquire", "acquires", "acquisition", "merger", "divest", "divestment", "stake", "licence",
              "license", "launch", "launches", "partnership", "appoints", "appointed", "ceo", "sells", "to sell"]
MARKET_WORDS = ["market size", "forecast", "cagr", "market share", "market growth", "consumer trend", "demand"]
TECH_WORDS = ["biotech", "fermentation", "ai", "artificial intelligence", "encapsulation", "delivery",
              "sustainable", "sustainability", "stability", "nanocarrier", "liposome", "personalization",
              "personalisation", "diagnostics"]
FORMULATION_WORDS = ["formulation", "reformulation", "patent", "new formula", "ingredient launch", "supplier"]
COMPANIES = [
    "L'Oréal", "L'Oreal", "Estée Lauder", "Estee Lauder", "Coty", "Shiseido", "Unilever", "Procter & Gamble",
    "Beiersdorf", "Kenvue", "Kao", "Kose", "Amorepacific", "LG H&H", "Proya", "Nykaa", "Honasa", "Dabur",
    "Hindustan Unilever", "Croda", "Givaudan", "dsm-firmenich", "BASF", "Evonik", "Kering", "LVMH",
    "Interparfums", "Revlon", "Olaplex", "e.l.f.",
]
INGREDIENTS = [
    "retinol", "retinoid", "niacinamide", "hyaluronic acid", "peptide", "bemotrizinol", "avobenzone",
    "oxybenzone", "octinoxate", "titanium dioxide", "zinc oxide", "formaldehyde", "paraben", "PFAS", "talc",
    "benzophenone", "salicylic acid", "vitamin C", "ceramide", "bakuchiol", "minoxidil", "bimatoprost",
    "hydroquinone", "tretinoin", "fluoride", "hydroxyapatite", "triclosan", "phenoxyethanol", "kojic acid",
    "prostaglandin", "mercury",
]


def _pattern(word: str) -> re.Pattern:
    # whole word, optional plural ending: "sunscreen" also matches "sunscreens"
    return re.compile(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?:s|es)?(?![a-z0-9])")


def _has(text: str, words: list[str]) -> bool:
    return any(_pattern(w).search(text) for w in words)


def _found(text: str, names: list[str]) -> list[str]:
    seen, out = set(), []
    for n in names:
        if _pattern(n).search(text) and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def classify_item(item: dict) -> dict:
    text = f"{item['title']} {item.get('snippet', '')}".lower()
    origin = item.get("origin", "")
    hint = item.get("section_hint", "news")

    relevant = origin == "pubmed" or _has(text, CORE) or bool(_found(text, COMPANIES)) \
        or _has(text, STRONG_INGREDIENTS)

    regions = [r for r, words in REGION_WORDS.items() if _has(text, words)]
    if not regions:
        regions = [item.get("region_hint") or "Global"]
    regions = [r for r in regions if r in REGIONS][:3] or ["Global"]

    categories = [c for c, words in CATEGORY_WORDS.items() if _has(text, words)]
    regulatory = origin != "pubmed" and _has(text, REGULATORY_WORDS) and relevant
    borderline = relevant and _has(text, BORDERLINE_STRONG)
    companies = _found(text, COMPANIES)
    ingredients = _found(text, INGREDIENTS)

    # section: start from the source's hint, then apply strong signals
    section = hint if hint in SECTIONS else "news"
    if borderline and not regulatory:
        section = "pharma"
    elif companies and _has(text, EARNINGS_WORDS):
        section = "company"
    elif companies and _has(text, DEAL_WORDS):
        section = "news"
    elif regulatory and section not in ("regulation", "ingredients"):
        section = "regulation"
    elif _has(text, MARKET_WORDS) and section in ("news", "market"):
        section = "market"
    elif section in ("news",) and _has(text, TECH_WORDS):
        section = "technology"
    elif section in ("news",) and _has(text, FORMULATION_WORDS):
        section = "formulation"

    snippet = item.get("snippet", "")
    words = snippet.split()
    summary = " ".join(words[:35]) + ("…" if len(words) > 35 else "")
    detailed = len(snippet) >= 120

    return {
        "relevant": relevant,
        "section": section,
        "regions": regions,
        "categories": [c for c in categories if c in CATEGORIES],
        "regulatory": bool(regulatory),
        "borderline": bool(borderline),
        "headline": item["title"][:140],
        "summary": summary if detailed else "",
        "ingredients": ingredients[:8],
        "companies": companies[:8],
        "confidence": "high" if detailed else "low",
    }


def classify_items(items: list[dict]) -> dict[str, dict]:
    return {it["id"]: classify_item(it) for it in items}


def make_digest(items: list[dict], limit: int = 6) -> list[dict]:
    """Free digest: the newest regulatory items, then the newest of the rest.
    Uses the headline as written, so no model is needed."""
    ranked = sorted(items, key=lambda x: (x["regulatory"], x["published"]), reverse=True)[:limit]
    return [{"text": x["headline"], "ids": [x["id"]]} for x in ranked]
