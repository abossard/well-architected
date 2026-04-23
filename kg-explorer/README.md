# Mission-Critical Knowledge Graph Explorer

Interactive force-directed graph of the Azure Well-Architected mission-critical docs.

## Research summary

| Option | Verdict |
|---|---|
| **A. LightRAG** | Installs cleanly via `pip install lightrag-hku` **but requires an LLM API key** (OpenAI / Gemini / Ollama) to extract entities from text. Slow first-run and adds runtime deps — overkill for 13 markdown files and not purely local without running Ollama. Not chosen. |
| **B. D3.js force graph** ✅ | One Python script + one static HTML. Zero runtime deps, pure-local, dark-mode, <30 min. **Chosen.** |
| C. Obsidian | Requires installing Obsidian; wikilink rewrite step; less control over layout. |
| D. Neo4j + Bloom | Heavyweight (Java, Docker); setup alone exceeds the time budget. |
| E. Other | `pyvis`, `mermaid` — pyvis is nice but less styled than a custom D3 build; mermaid doesn't do force layout at this scale. |

## Contents

- `build_graph.py` — parses the 13 markdown files, extracts docs / H2 / H3 / curated domain concepts, emits `graph.json`.
- `graph.json` — 271 nodes, 1991 edges.
- `index.html` — standalone D3 v7 visualization (loads D3 from CDN).

## Run

```bash
cd /Users/abossard/Desktop/cxe/well-architected/kg-explorer
python3 build_graph.py              # rebuild graph.json from source markdown
python3 -m http.server 8000         # serve locally (browsers block fetch() on file://)
open http://localhost:8000/
```

## Graph schema

- **Nodes:** `doc` (markdown file), `h2` (section), `h3` (subsection), `concept` (curated domain term).
- **Edges:** `contains` (doc→h2→h3), `links` (doc→doc markdown links), `mentions` (doc→concept), `related` (concept↔concept co-occurring in ≥2 docs).

## UI features

- Search/filter by label, node type, edge type.
- Slider: min concept mention count.
- Hover → tooltip + highlight neighborhood; click → sidebar with neighbors list.
- Drag nodes, zoom/pan, reheat layout, toggle labels.
- Dark-mode styled to match GitHub dark.
