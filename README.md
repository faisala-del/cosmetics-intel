# Cosmetics Intelligence Briefing: auto-refreshing website

One website covering market, ingredients, technology, formulation, deals, company results, stocks, regional regulation and the pharma/cosmetics boundary. It rebuilds itself every day.

**How it works**

```
GitHub Actions (daily)
  1. fetch    Google News (regional), PubMed, Federal Register, SEC filings, any feeds you add
  2. classify Claude Haiku tags each NEW item: section, region, category, regulatory flag,
              drug-vs-cosmetic flag, 35-word summary. Results are cached in data/cache.json
  3. digest   Claude Sonnet writes a 5 to 7 line "what changed" overview
  4. stocks   yfinance pulls closes and 52-week ranges
  5. publish  site/ folder goes live on GitHub Pages
```

The site is plain HTML, CSS and JavaScript. No server or database to run.

---

## What you need

- A free GitHub account
- About 20 minutes
- **Optional:** an Anthropic API key (console.anthropic.com) for better tagging and written summaries. **Without a key the project runs in free mode** (see "Free mode" below). Max and Team plan holders may get monthly API credits that cover it; check your Claude billing settings.

## Setup steps

**1. Create the repository**
1. On GitHub choose New repository. Name it `cosmetics-intel`. Public is simplest for free Pages hosting; a private repo needs a paid plan for Pages.
2. Upload every file and folder from this project, keeping the structure (`.github/workflows/refresh.yml` must keep that exact path).

**2. Add your API key (skip this step to stay free)**
1. Repository, Settings, Secrets and variables, Actions, New repository secret.
2. Name: `ANTHROPIC_API_KEY`. Value: your key.
3. Optional: add `NCBI_API_KEY` (free from NCBI) to raise PubMed rate limits.
If you add the key later, items already tagged by free rules are upgraded to Claude tagging on the next runs, within the `max_new_items_per_run` cap.

**3. Turn on Pages**
1. Settings, Pages, Source: **GitHub Actions**.

**4. Edit two lines in `config.yaml`**
1. `user_agent`: put your real email. SEC EDGAR and some sites block anonymous requests.
2. Check the company and ticker lists suit you.

**5. Run it once**
1. Actions tab, "Refresh briefing and deploy site", Run workflow.
2. When it turns green, open the Pages URL shown in the deploy step (also under Settings, Pages).
3. From then on it runs daily at 01:30 UTC (07:00 IST). Change the `cron` line in `.github/workflows/refresh.yml` to adjust. Add a second cron line for a twice-daily stock refresh.

The site ships with 19 starter items from the 12 Oct 2026 research so it is never empty. The first live run replaces them.

---

## Test before you rely on it

Run these on your own computer (Python 3.11 or newer):

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m scripts.build --check      # tests every source and ticker, no Claude, no cost
```

`--check` prints which sources work and which fail. **Do this first.** I could not test live network access when building this, so some feed URLs or tickers may need small fixes. Failing sources are skipped automatically and listed in `site/data/briefing.json` under `source_report`.

Then:

```bash
python -m scripts.build --rules      # free mode, no key needed
# or, with a key:
export ANTHROPIC_API_KEY=sk-ant-...                    # Windows: set ANTHROPIC_API_KEY=...
python -m scripts.build              # Claude mode
cd site && python -m http.server 8000   # open http://localhost:8000
```

(Open the site through `http.server`, not by double-clicking `index.html`, or the browser will block loading the data files.)

---

## Customising

| To change | Edit |
|---|---|
| Add a regulator or trade-press feed | `feeds:` in `config.yaml` (any RSS or Atom URL) |
| Add a topic, ingredient or country to watch | `google_news:` queries (use `OR` between terms) |
| Add scientific topics (stability, delivery, UV filters) | `pubmed_queries:` |
| Add or remove companies | `stocks:` (Yahoo Finance symbols) |
| Lower cost | reduce `max_new_items_per_run` or `google_news` entries |
| Higher quality summaries | set `classify_model` to a stronger model |
| Looks | `site/style.css` |

## Free mode (no API key, no cost)

If `ANTHROPIC_API_KEY` is not set, or you run `--rules`, `scripts/classify_rules.py` tags items with keyword rules instead of Claude. GitHub Actions, GitHub Pages, Google News RSS, PubMed, the Federal Register, SEC and yfinance are all free, so the whole site runs at zero cost.

| | Free mode | Claude mode |
|---|---|---|
| Cost | none | small per-run API cost |
| Section, region, category, regulatory flag | keyword rules | model judgement |
| Summaries | source snippet only (PubMed abstracts, Federal Register, SEC); none for Google News headlines | 35-word summary for every item |
| "What changed" overview | the six newest regulatory headlines | written overview |
| Accuracy | good on obvious items, noisier on nuance (for example a headline containing "ban" about something unrelated) | better |

Tune free mode by editing the keyword lists at the top of `scripts/classify_rules.py` (companies, ingredients, regulator names, regions).

**Other free routes I have not built:** some other providers offer free-tier language-model APIs, and you can run an open model locally with a tool such as Ollama. Either would replace the `_call()` function in `scripts/classify.py`. Free-tier limits and terms change, so check them before relying on one. Local models cannot run inside GitHub's free scheduler, so they suit running the build on your own computer.

## Cost control (Claude mode)

Claude is only called for items it has not seen before (cached in `data/cache.json`), plus one digest call per run. Haiku-class models are the cheapest tier. `max_new_items_per_run` caps the worst case. Check usage in the Anthropic console after the first few runs and adjust.

---

## Honest limits

- **Summaries come from headlines and snippets, not full articles.** Google News gives only a headline, so those items are labelled "Headline only". PubMed, Federal Register and SEC items carry real abstracts or text and are rated higher. For deeper coverage, add direct feeds from sources you trust.
- **AI tagging can be wrong.** Every item links to its source. Confirm any regulation, date or figure against the primary document before using it in a filing, formulation decision or investment.
- **Regulatory sources are indirect.** There is no single official feed for CDSCO, NMPA, MHLW, MFDS, BPOM or the EU Official Journal. The project finds their news through press coverage. If you need legally exact tracking for a country, add that regulator's own page or a paid regulatory-intelligence feed.
- **No patent coverage yet.** Patent search needs a dedicated source (for example Lens.org or PatentsView). It is the next extension to add.
- **yfinance is unofficial.** It can break. If it does, replace `fetch_one()` in `scripts/stocks.py` with Finnhub or Alpha Vantage; nothing else changes.
- **GitHub pauses scheduled workflows** in public repos after about 60 days with no repository activity. Look at the Actions tab now and then, or press Run workflow to wake it.
- Prices are delayed. Nothing here is legal or investment advice.

## Project layout

```
config.yaml                  sources, queries, tickers, models
scripts/fetch.py             RSS, Google News, PubMed, Federal Register fetchers
scripts/classify.py          Claude tagging, summaries and digest
scripts/classify_rules.py    free keyword tagging (used when there is no API key)
scripts/stocks.py            price fetcher
scripts/build.py             runs everything, writes JSON
data/cache.json              items already classified (committed by the workflow)
site/                        the website (index.html, app.js, style.css, data/*.json)
.github/workflows/refresh.yml  daily schedule and deployment
```
