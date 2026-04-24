#!/usr/bin/env python3
"""Generate beautiful interactive HTML radial tree diagrams for mental model cards.

Reads the knowledge graph (GraphML), taxonomy, and cards, then emits a
self-contained HTML per card using D3.js. Usage:

    python3 generate_card_diagram.py "Zero Trust"
    python3 generate_card_diagram.py --all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import networkx as nx

ROOT = Path(__file__).resolve().parent
GRAPH_PATH = ROOT / "lightrag_data" / "graph_chunk_entity_relation.graphml"
TAXONOMY_PATH = ROOT / "mental_models" / "taxonomy.json"
CARDS_PATH = ROOT / "mental_models" / "cards.json"
OUT_DIR = ROOT / "mental_models" / "cards"

CATEGORY_ORDER = [
    "MENTAL_MODEL",
    "PATTERN",
    "AZURE_SERVICE",
    "PROCESS",
    "CONCEPT",
    "METRIC",
]

CATEGORY_COLORS = {
    "MENTAL_MODEL": "#f1c40f",
    "PATTERN":      "#3b82f6",
    "AZURE_SERVICE":"#6366f1",
    "PROCESS":      "#22c55e",
    "CONCEPT":      "#9ca3af",
    "METRIC":       "#ef4444",
    "OTHER":        "#64748b",
}

CATEGORY_LABELS = {
    "MENTAL_MODEL": "Mental Models",
    "PATTERN":      "Patterns",
    "AZURE_SERVICE":"Azure Services",
    "PROCESS":      "Processes",
    "CONCEPT":      "Concepts",
    "METRIC":       "Metrics",
    "OTHER":        "Other",
}


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "card"


def clean_description(raw: str | None) -> str:
    if not raw:
        return ""
    # GraphML merges multiple descriptions using the literal token <SEP>
    parts = [p.strip() for p in raw.split("<SEP>") if p.strip()]
    # Take the first couple of unique sentences, keep it short
    seen, out = set(), []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= 2:
            break
    text = " ".join(out)
    if len(text) > 500:
        text = text[:497].rstrip() + "…"
    return text


def load_taxonomy() -> dict[str, str]:
    data = json.loads(TAXONOMY_PATH.read_text())
    return {item["entity"]: item["category"] for item in data}


def build_tree(card: dict, graph: nx.Graph, tax: dict[str, str]) -> dict[str, Any]:
    name = card["name"]
    root_desc = clean_description(graph.nodes[name].get("d2") or graph.nodes[name].get("description"))

    # Gather neighbors from the graph + relationships declared in the card
    neighbors: dict[str, dict[str, Any]] = {}

    def add_neighbor(n: str, weight: float = 1.0, rel: str = "connected"):
        if n == name or n not in graph.nodes:
            return
        entry = neighbors.setdefault(n, {
            "name": n,
            "category": tax.get(n, "OTHER"),
            "description": clean_description(graph.nodes[n].get("d2") or graph.nodes[n].get("description")),
            "weight": 0.0,
            "relations": set(),
        })
        entry["weight"] = max(entry["weight"], weight)
        entry["relations"].add(rel)

    for nb in graph.neighbors(name):
        edge = graph.get_edge_data(name, nb) or {}
        w = float(edge.get("d7") or edge.get("weight") or 1.0)
        add_neighbor(nb, weight=w, rel="graph")

    for n in card.get("builds_on", []) or []:
        add_neighbor(n, weight=2.0, rel="builds_on")
    for n in card.get("enables", []) or []:
        add_neighbor(n, weight=2.0, rel="enables")

    # Bucket by category, keep MENTAL_MODEL bucket even if empty to anchor layout
    buckets: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_ORDER}
    for entry in neighbors.values():
        cat = entry["category"] if entry["category"] in buckets else "OTHER"
        buckets.setdefault(cat, []).append({
            "name": entry["name"],
            "category": cat,
            "description": entry["description"],
            "weight": round(entry["weight"], 2),
            "relations": sorted(entry["relations"]),
        })

    children = []
    for cat in CATEGORY_ORDER + ["OTHER"]:
        items = buckets.get(cat) or []
        if not items:
            continue
        items.sort(key=lambda x: (-x["weight"], x["name"]))
        children.append({
            "name": CATEGORY_LABELS[cat],
            "category": cat,
            "isGroup": True,
            "children": items,
        })

    return {
        "name": name,
        "category": "ROOT",
        "mantra": card.get("mantra", ""),
        "description": root_desc,
        "children": children,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>__TITLE__ · Mental Model Map</title>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<style>
  :root {
    --bg: #0d1117;
    --bg-alt: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --gold: #f1c40f;
  }
  * { box-sizing: border-box; }
  html, body { margin:0; padding:0; height:100%; background:var(--bg); color:var(--text);
    font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif; }
  a { color: var(--accent); }
  .app {
    display:grid; grid-template-columns: 1fr 380px; height:100vh; width:100vw;
  }
  @media (max-width: 900px) {
    .app { grid-template-columns: 1fr; grid-template-rows: 60vh 40vh; }
  }
  .viz { position:relative; overflow:hidden; background:
      radial-gradient(ellipse at center, #111827 0%, #0d1117 70%); }
  .viz svg { width:100%; height:100%; display:block; cursor: grab; }
  .viz svg:active { cursor: grabbing; }

  .toolbar {
    position:absolute; top:12px; left:12px; display:flex; gap:8px; flex-wrap:wrap; z-index:5;
  }
  .toolbar button, .legend-chip {
    background: rgba(22,27,34,0.85); color:var(--text); border:1px solid var(--border);
    padding:6px 10px; border-radius:6px; font-size:12px; cursor:pointer;
    backdrop-filter: blur(6px);
  }
  .toolbar button:hover { border-color: var(--accent); }

  .legend {
    position:absolute; bottom:12px; left:12px; display:flex; gap:6px; flex-wrap:wrap; z-index:5;
  }
  .legend-chip { display:flex; align-items:center; gap:6px; font-size:11px; cursor:default; }
  .legend-chip .dot { width:10px; height:10px; border-radius:50%; }

  .sidebar {
    background: var(--bg-alt); border-left:1px solid var(--border);
    padding: 20px; overflow-y:auto;
  }
  @media (max-width: 900px) {
    .sidebar { border-left:none; border-top:1px solid var(--border); }
  }
  .sidebar h1 { font-size: 22px; margin: 0 0 4px; color: var(--gold); }
  .sidebar .mantra { font-style:italic; color: var(--text-dim); margin: 0 0 16px; font-size: 14px; }
  .sidebar h2 {
    font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
    color: var(--text-dim); margin: 18px 0 6px; border-bottom:1px solid var(--border); padding-bottom:4px;
  }
  .sidebar ul { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.5; }
  .sidebar li { margin-bottom: 4px; }
  .tradeoff {
    background: #3d2a14; border-left: 3px solid #f59e0b; color: #fbe4b3;
    padding: 10px 12px; border-radius: 4px; font-size:13px; line-height:1.5;
  }
  .detail-card {
    margin-top: 18px; padding: 12px; border:1px solid var(--border); border-radius:6px;
    background: #0d1117; font-size: 13px; line-height: 1.5;
  }
  .detail-card .cat {
    display:inline-block; font-size:10px; text-transform:uppercase; letter-spacing:1px;
    padding: 2px 8px; border-radius: 10px; background: #21262d; margin-bottom:6px;
  }
  .detail-card h3 { margin: 4px 0 8px; font-size: 15px; }
  .detail-card .rels { margin-top:6px; font-size: 11px; color: var(--text-dim); }

  .link { fill:none; stroke-opacity:0.55; stroke-width:1.4px; }
  .node circle { stroke:#0d1117; stroke-width:2px; cursor:pointer;
    transition: r 0.2s ease, stroke-width 0.2s ease; }
  .node:hover circle { stroke:#fff; stroke-width:3px; }
  .node text { font-size:11px; fill: var(--text); pointer-events:none;
    text-shadow: 0 0 4px #0d1117, 0 0 4px #0d1117; }
  .node.root text { font-size: 14px; font-weight: 600; fill: var(--gold); }
  .node.group text { font-weight: 600; font-size: 12px; }

  .tooltip {
    position:absolute; pointer-events:none; background: rgba(22,27,34,0.95);
    border:1px solid var(--border); border-radius:6px; padding:8px 10px;
    font-size:12px; max-width:280px; color:var(--text);
    box-shadow: 0 6px 20px rgba(0,0,0,0.5); opacity:0; transition: opacity 0.15s;
    z-index: 10;
  }
  .tooltip strong { color: var(--gold); }
</style>
</head>
<body>
<div class="app">
  <div class="viz">
    <div class="toolbar">
      <button id="btn-reset">⟲ Reset view</button>
      <button id="btn-expand">⤢ Expand all</button>
      <button id="btn-collapse">⤡ Collapse</button>
      <button onclick="history.back()">← Back</button>
    </div>
    <svg id="chart"></svg>
    <div class="legend" id="legend"></div>
    <div class="tooltip" id="tooltip"></div>
  </div>
  <aside class="sidebar">
    <h1>__NAME__</h1>
    <p class="mantra">“__MANTRA__”</p>

    <h2>When to apply</h2>
    <ul id="when-list"></ul>

    <h2>Without it</h2>
    <ul id="without-list"></ul>

    <h2>Key tradeoff</h2>
    <div class="tradeoff" id="tradeoff-box"></div>

    <div id="detail-slot"></div>
  </aside>
</div>

<script>
const DATA = __DATA_JSON__;
const CARD = __CARD_JSON__;
const COLORS = __COLORS_JSON__;

// Populate sidebar
document.getElementById('when-list').innerHTML =
  (CARD.when_to_apply || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');
document.getElementById('without-list').innerHTML =
  (CARD.without_it || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');
document.getElementById('tradeoff-box').textContent = CARD.key_tradeoff || '';

// Legend
const catsUsed = new Set();
(function collect(n){ if(n.category) catsUsed.add(n.category); (n.children||[]).forEach(collect); })(DATA);
const legendEl = document.getElementById('legend');
['MENTAL_MODEL','PATTERN','AZURE_SERVICE','PROCESS','CONCEPT','METRIC','OTHER']
  .filter(c => catsUsed.has(c))
  .forEach(c => {
    const chip = document.createElement('div');
    chip.className = 'legend-chip';
    chip.innerHTML = `<span class="dot" style="background:${COLORS[c]}"></span>${c.replace('_',' ')}`;
    legendEl.appendChild(chip);
  });

function escapeHtml(s){ return String(s).replace(/[&<>"']/g, m =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

const svg = d3.select('#chart');
const tooltip = d3.select('#tooltip');
const container = svg.append('g');

const zoom = d3.zoom().scaleExtent([0.3, 3])
  .on('zoom', e => container.attr('transform', e.transform));
svg.call(zoom);

const root = d3.hierarchy(DATA);
// Track collapsed state
root.descendants().forEach(d => { d._children = d.children; });

function radius() {
  const r = svg.node().getBoundingClientRect();
  return Math.max(220, Math.min(r.width, r.height) / 2 - 60);
}

let currentRoot = root;

function centerTransform() {
  const bbox = svg.node().getBoundingClientRect();
  return d3.zoomIdentity.translate(bbox.width / 2, bbox.height / 2);
}

function render() {
  const R = radius();
  const treeLayout = d3.cluster().size([2 * Math.PI, R])
    .separation((a, b) => (a.parent === b.parent ? 1 : 2) / Math.max(a.depth, 1));
  treeLayout(currentRoot);

  // Center via zoom transform so reset works correctly
  svg.call(zoom.transform, centerTransform());

  // Links
  const linkGen = d3.linkRadial().angle(d => d.x).radius(d => d.y);
  const links = container.selectAll('path.link').data(currentRoot.links(), d => d.target.data.name);
  links.exit().remove();
  links.enter().append('path').attr('class','link')
    .merge(links)
    .attr('stroke', d => COLORS[d.target.data.category] || COLORS.OTHER)
    .attr('d', linkGen);

  // Nodes
  const nodes = container.selectAll('g.node').data(currentRoot.descendants(), d => d.data.name + d.depth);
  nodes.exit().remove();
  const nodesEnter = nodes.enter().append('g')
    .attr('class', d => 'node' + (d.depth===0?' root':'') + (d.data.isGroup?' group':''));
  nodesEnter.append('circle');
  nodesEnter.append('text');

  const all = nodesEnter.merge(nodes);
  all.attr('transform', d =>
    `translate(${Math.sin(d.x) * d.y},${-Math.cos(d.x) * d.y})`);

  all.select('circle')
    .attr('r', d => d.depth === 0 ? 14 : d.data.isGroup ? 8 : 5 + Math.min(4, (d.data.weight||1)))
    .attr('fill', d => d.depth === 0 ? COLORS.ROOT || '#f1c40f' : COLORS[d.data.category] || COLORS.OTHER)
    .on('mouseenter', (e,d) => showTooltip(e,d))
    .on('mousemove', (e,d) => moveTooltip(e))
    .on('mouseleave', hideTooltip)
    .on('click', (e,d) => onClick(e,d));

  all.select('text')
    .attr('dy', '0.32em')
    .attr('x', d => d.x < Math.PI ? 10 : -10)
    .attr('text-anchor', d => d.x < Math.PI ? 'start' : 'end')
    .attr('transform', d => {
      const deg = (d.x * 180 / Math.PI) - 90;
      return d.x < Math.PI ? `rotate(${deg})` : `rotate(${deg+180})`;
    })
    .text(d => d.data.name);
}

function onClick(event, d) {
  if (d.data.isGroup || d.depth === 0) {
    // toggle collapse
    if (d.children) { d._kids = d.children; d.children = null; }
    else if (d._kids) { d.children = d._kids; d._kids = null; }
    render();
    return;
  }
  showDetail(d.data);
}

function showDetail(data) {
  const slot = document.getElementById('detail-slot');
  const rels = (data.relations && data.relations.length)
    ? `<div class="rels">Linked via: ${data.relations.map(escapeHtml).join(', ')}</div>` : '';
  slot.innerHTML = `
    <div class="detail-card" style="border-left:3px solid ${COLORS[data.category]||COLORS.OTHER}">
      <span class="cat" style="color:${COLORS[data.category]||COLORS.OTHER}">${(data.category||'').replace('_',' ')}</span>
      <h3>${escapeHtml(data.name)}</h3>
      <div>${escapeHtml(data.description || 'No description available.')}</div>
      ${rels}
    </div>`;
  slot.scrollIntoView({behavior:'smooth', block:'nearest'});
}

function showTooltip(e, d) {
  const desc = d.data.description || d.data.mantra || '';
  tooltip.html(`<strong>${escapeHtml(d.data.name)}</strong>` +
    (desc ? `<br/><span>${escapeHtml(desc.slice(0,180))}${desc.length>180?'…':''}</span>` : ''))
    .style('opacity', 1);
  moveTooltip(e);
}
function moveTooltip(e) {
  tooltip.style('left', (e.clientX + 14) + 'px').style('top', (e.clientY + 14) + 'px');
}
function hideTooltip() { tooltip.style('opacity', 0); }

document.getElementById('btn-reset').onclick = () => {
  svg.transition().duration(500).call(zoom.transform, centerTransform());
};
document.getElementById('btn-expand').onclick = () => {
  root.descendants().forEach(d => { if (d._kids) { d.children = d._kids; d._kids = null; } });
  render();
};
document.getElementById('btn-collapse').onclick = () => {
  root.descendants().forEach(d => {
    if (d.depth >= 1 && d.children) { d._kids = d.children; d.children = null; }
  });
  render();
};

window.addEventListener('resize', render);
render();

// Show root detail by default
showDetail({name: CARD.name, category: 'MENTAL_MODEL',
  description: DATA.description || CARD.mantra, relations: []});
</script>
</body>
</html>
"""


def render_html(card: dict, tree: dict) -> str:
    html = HTML_TEMPLATE
    colors = {**CATEGORY_COLORS, "ROOT": "#f1c40f"}
    replacements = {
        "__TITLE__":      card["name"],
        "__NAME__":       card["name"],
        "__MANTRA__":     card.get("mantra", "").replace('"', "&quot;"),
        "__DATA_JSON__":  json.dumps(tree, ensure_ascii=False),
        "__CARD_JSON__":  json.dumps(card, ensure_ascii=False),
        "__COLORS_JSON__":json.dumps(colors),
    }
    for k, v in replacements.items():
        html = html.replace(k, v)
    return html


def generate_for_card(card: dict, graph: nx.Graph, tax: dict[str, str]) -> Path:
    tree = build_tree(card, graph, tax)
    html = render_html(card, tree)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{slugify(card['name'])}.html"
    out.write_text(html, encoding="utf-8")
    return out


def generate_index(cards: list[dict]) -> Path:
    items = "\n".join(
        f'<li><a href="{slugify(c["name"])}.html"><strong>{c["name"]}</strong>'
        f'<span class="mantra">{c.get("mantra","")}</span></a></li>'
        for c in cards
    )
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Mental Model Diagrams</title>
<style>
 body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
   background:#0d1117; color:#e6edf3; padding:40px 24px; }}
 h1 {{ color:#f1c40f; margin-top:0; }}
 ul {{ list-style:none; padding:0; display:grid; gap:12px;
   grid-template-columns: repeat(auto-fill,minmax(280px,1fr)); max-width:1200px; margin:0 auto; }}
 li a {{ display:block; padding:16px; background:#161b22; border:1px solid #30363d;
   border-radius:8px; text-decoration:none; color:#e6edf3; transition: all .15s; }}
 li a:hover {{ border-color:#58a6ff; transform: translateY(-2px); }}
 li strong {{ display:block; color:#f1c40f; margin-bottom:6px; }}
 .mantra {{ font-size:13px; color:#8b949e; font-style:italic; }}
 .wrap {{ max-width:1200px; margin:0 auto; }}
</style></head><body>
<div class="wrap"><h1>Mental Model Diagrams</h1>
<p style="color:#8b949e;">Interactive radial tree visualizations of each mental model and its neighborhood in the Well-Architected knowledge graph.</p>
<ul>{items}</ul></div></body></html>"""
    out = OUT_DIR / "index.html"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", help="Mental model name (exact match)")
    ap.add_argument("--all", action="store_true", help="Generate for all cards")
    args = ap.parse_args()

    if not args.name and not args.all:
        ap.print_help()
        return 2

    graph = nx.read_graphml(GRAPH_PATH)
    tax = load_taxonomy()
    cards = json.loads(CARDS_PATH.read_text())
    by_name = {c["name"]: c for c in cards}

    targets: list[dict]
    if args.all:
        targets = cards
    else:
        if args.name not in by_name:
            matches = [n for n in by_name if args.name.lower() in n.lower()]
            if len(matches) == 1:
                targets = [by_name[matches[0]]]
            else:
                print(f"Unknown card: {args.name!r}. Available:", file=sys.stderr)
                for n in by_name: print(f"  - {n}", file=sys.stderr)
                return 1
        else:
            targets = [by_name[args.name]]

    for c in targets:
        out = generate_for_card(c, graph, tax)
        print(f"✓ {c['name']:40s} → {out.relative_to(ROOT)}")

    if args.all or len(targets) > 1:
        idx = generate_index(cards)
        print(f"✓ index {'':35s} → {idx.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
