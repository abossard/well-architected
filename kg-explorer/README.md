# Mission-Critical Mental Models — Knowledge Graph Explorer

Interactive knowledge graph and mental model mining toolkit for the Azure Well-Architected Framework.

**Live site:** https://abossard.github.io/well-architected/

## What's here

| Tool | Description |
|------|-------------|
| [Landing page](https://abossard.github.io/well-architected/) | Entry point with stats and navigation |
| [Mental Model Cards](https://abossard.github.io/well-architected/mental_models/) | 43 cards with mantras, failure modes, tradeoffs — filterable and searchable |
| [Knowledge Graph](https://abossard.github.io/well-architected/graph.html) | D3 force-directed graph of 880 entities and 980 relations |
| [Card Trees](https://abossard.github.io/well-architected/mental_models/cards/) | Radial tree diagrams showing each model's connections |

## How it works

1. **LightRAG** ingests 34 WAF docs (13 mission-critical + 21 pillar docs) into a knowledge graph
2. **Claude Opus 4.6** (via [copilot-api](https://github.com/ericc-ch/copilot-api)) extracts 880 entities and 980 relations
3. **Graph analysis** ranks entities by centrality and bridge score
4. **LLM classification** sorts entities into 9 categories (mental models, patterns, services, etc.)
5. **Card generation** creates structured cards with mantras, failure modes, and tradeoffs
6. **spaCy** measures information density; fluffy cards get rewritten

## Scripts

| Script | What it does |
|--------|-------------|
| `build_graph.py` | Parse markdown → D3 concept graph (8 node types) |
| `ingest_lightrag.py` | Ingest docs into LightRAG via copilot-api proxy |
| `query_lightrag.py` | CLI query tool (hybrid/local/global/naive modes) |
| `mine_mental_models.py` | Classify entities, generate cards, create HTML report |
| `build_pages.py` | Generate formatted mental models page from cards.json |
| `generate_card_diagram.py` | Generate radial tree diagrams per card |
| `densify_cards.py` | Measure info density with spaCy, rewrite sparse cards |
| `gh_proxy.py` | Minimal proxy routing to GitHub Models API (alternative to copilot-api) |

## Run locally

```bash
# 1. Start copilot-api proxy (needs GitHub Copilot subscription)
npx copilot-api start --port 11435

# 2. Setup
cd kg-explorer
python3 -m venv .venv && source .venv/bin/activate
pip install lightrag-hku spacy
python3 -m spacy download en_core_web_sm

# 3. Ingest docs into LightRAG
python3 ingest_lightrag.py

# 4. Mine mental models
python3 mine_mental_models.py --top 43

# 5. Build pages
python3 build_pages.py
python3 generate_card_diagram.py --all

# 6. Query
python3 query_lightrag.py --mode hybrid "What is blast radius thinking?"

# 7. Serve locally
python3 -m http.server 8767 -d mental_models
```

## Graph schema

**Nodes:** doc, h2, h3, product, pattern, process, concept, metric

**Edges:** contains (doc→h2→h3), links (doc→doc), mentions (doc→term), related (term↔term co-occurrence)

**Entity categories:** MENTAL_MODEL, PATTERN, AZURE_SERVICE, PROCESS, CONCEPT, METRIC, TRADEOFF, ANTI_PATTERN

## Design principles

Built for neurodivergent, fast-thinking architects:
- 15px/1.65 body text, 66ch max line length
- Cards visible above the fold (40% fold rule)
- Instant search, layer filters, progressive disclosure
- No italic on dark backgrounds — accent borders instead
- `prefers-reduced-motion` support
- Keyboard accessible with focus rings
- Semantic color tokens (gold=foundational, blue=structural, green=operational, red=security)

## Data

- **880 entities**, **980 relations** from 34 WAF docs
- **43 mental model cards** (deduplicated from 54)
- **9 anti-patterns**, **5 tradeoffs**
- Knowledge graph: 1.1MB GraphML
