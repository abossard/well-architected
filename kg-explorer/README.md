# Azure Well-Architected Knowledge Graph Explorer

Interactive knowledge graph + mental-model browser for the Azure Well-Architected Framework.

**Live site:** https://abossard.github.io/well-architected/

## Two commands to rebuild everything

```bash
# Prereqs: venv + copilot-api proxy for the mining step
source .venv/bin/activate
npx copilot-api start --port 11435   # only needed for ingest + mining

# Pull new WAF docs into the knowledge graph (idempotent, skips ingested files)
python3 ingest.py

# Rebuild every site artifact and mirror it into ../docs/
python3 build_site.py                 # full rebuild
python3 build_site.py --skip-mine     # skip LLM mining, use cached taxonomy/cards
python3 build_site.py --skip-trees    # skip per-card tree diagrams
```

`build_site.py` owns the whole pipeline:

1. Export the LightRAG GraphML → `graph.json`
2. Classify entities and generate mental-model cards (LLM)
3. Build `site-data.json`
4. Render per-card radial tree diagrams
5. Copy every artifact into `../docs/`

HTML shells (`docs/index.html`, `docs/graph.html`, `docs/mental_models/index.html`) are **static** — they load the JSON files at runtime, so they never need regeneration.

## Site

| Page | Description |
|------|-------------|
| [Home](https://abossard.github.io/well-architected/) | Entry point with live stats |
| [Mental Model Cards](https://abossard.github.io/well-architected/mental_models/) | Filterable, searchable cards with mantras, failure modes, tradeoffs |
| [Knowledge Graph](https://abossard.github.io/well-architected/graph.html) | D3 force-directed view of 4,000+ entities |
| [Card Trees](https://abossard.github.io/well-architected/mental_models/cards/) | Radial tree per mental model |

## Active scripts

| Script | Purpose |
|--------|---------|
| `build_site.py` | **Single entry point** for rebuilding site data |
| `ingest.py` | Unified LightRAG ingestion for every WAF subdir |
| `mine_mental_models.py` | Library: entity classification + card generation |
| `export_lightrag_graph.py` | Library: GraphML → D3 JSON |
| `generate_card_diagram.py` | Library: per-card radial tree HTML |
| `densify_cards.py` | Measure info density and rewrite sparse cards |
| `query_lightrag.py` | CLI query tool (hybrid / local / global / naive) |
| `gh_proxy.py` | Minimal GitHub Models proxy (alternative to copilot-api) |

Superseded scripts live in `deprecated/`.

## How it works

1. **LightRAG** ingests 221+ WAF markdown docs into a knowledge graph
2. **Claude Opus 4.6** (via [copilot-api](https://github.com/ericc-ch/copilot-api)) extracts entities and relations
3. **Graph analysis** ranks entities by centrality and bridge score
4. **LLM classification** sorts entities into 9 taxonomy categories
5. **Card generation** produces structured cards with mantras, failure modes, tradeoffs
6. **spaCy** measures information density and flags cards for rewriting

## Graph schema

**Entity categories:** `MENTAL_MODEL`, `PATTERN`, `AZURE_SERVICE`, `PROCESS`, `CONCEPT`, `METRIC`, `TRADEOFF`, `ANTI_PATTERN`, `OTHER`

## Design principles

- 15px/1.65 body text, 66ch max line length
- Above-the-fold cards (40% fold rule)
- Instant search + progressive disclosure
- No italics on dark — accent borders instead
- `prefers-reduced-motion` support
- Keyboard accessible with visible focus rings
