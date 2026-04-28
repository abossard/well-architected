#!/usr/bin/env python3
"""Mine mental models from the LightRAG knowledge graph.

Reads the GraphML graph + entity/relation stores to:
1. Classify the 880 entities into mental model categories
2. Find clusters of strongly connected concepts
3. Identify the highest-leverage mental models (most connections)
4. Map tensions/tradeoffs between concepts
5. Output a structured taxonomy as JSON + a visual HTML report

Usage:
    python3 mine_mental_models.py
    python3 mine_mental_models.py --query "blast radius"
    python3 mine_mental_models.py --top 30

Requires: copilot-api proxy running on :11435 for LLM classification.
"""
import asyncio
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from functools import partial

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
DEFAULT_DOMAIN = "mission-critical"
OUT_DIR = pathlib.Path(__file__).parent / "mental_models"


def rag_dir_for_domain(domain: str) -> pathlib.Path:
    return pathlib.Path(__file__).parent / f"lightrag_data_{domain}"


def load_graph(domain: str = DEFAULT_DOMAIN):
    """Parse GraphML into nodes and edges."""
    rag_dir = rag_dir_for_domain(domain)
    tree = ET.parse(rag_dir / "graph_chunk_entity_relation.graphml")
    root = tree.getroot()

    # Find key definitions
    key_map = {}
    for elem in root.iter():
        if elem.tag.endswith("key"):
            kid = elem.get("id", "")
            kname = elem.get("attr.name", kid)
            key_map[kid] = kname

    nodes = {}
    edges = []

    for elem in root.iter():
        if elem.tag.endswith("node"):
            nid = elem.get("id", "")
            data = {}
            for d in elem:
                if d.tag.endswith("data"):
                    key = key_map.get(d.get("key", ""), d.get("key", ""))
                    data[key] = d.text or ""
            nodes[nid] = data

        elif elem.tag.endswith("edge"):
            source = elem.get("source", "")
            target = elem.get("target", "")
            data = {}
            for d in elem:
                if d.tag.endswith("data"):
                    key = key_map.get(d.get("key", ""), d.get("key", ""))
                    data[key] = d.text or ""
            edges.append({"source": source, "target": target, **data})

    return nodes, edges


def compute_centrality(nodes, edges):
    """Compute degree centrality for each node."""
    degree = Counter()
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    return degree


def find_neighbors(node_id, edges):
    """Get all neighbors of a node."""
    neighbors = set()
    for e in edges:
        if e["source"] == node_id:
            neighbors.add(e["target"])
        elif e["target"] == node_id:
            neighbors.add(e["source"])
    return neighbors


def find_bridges(edges):
    """Find edges that connect otherwise separate clusters (bridge concepts)."""
    # Simplified: find nodes that appear in many different neighborhoods
    node_neighbors = defaultdict(set)
    for e in edges:
        node_neighbors[e["source"]].add(e["target"])
        node_neighbors[e["target"]].add(e["source"])

    bridge_scores = {}
    for node, neighbors in node_neighbors.items():
        # How many of this node's neighbors are NOT connected to each other?
        disconnected_pairs = 0
        neighbor_list = list(neighbors)
        for i in range(len(neighbor_list)):
            for j in range(i + 1, len(neighbor_list)):
                if neighbor_list[j] not in node_neighbors.get(neighbor_list[i], set()):
                    disconnected_pairs += 1
        total_pairs = max(1, len(neighbor_list) * (len(neighbor_list) - 1) // 2)
        bridge_scores[node] = disconnected_pairs / total_pairs if total_pairs > 0 else 0

    return bridge_scores


async def classify_entities(entities, descriptions):
    """Use LLM to classify entities into mental model categories."""
    from lightrag.llm.openai import openai_complete_if_cache

    # Build a batch prompt
    entity_list = "\n".join(f"- {e}: {descriptions.get(e, '(no description)')[:150]}" for e in entities)

    prompt = f"""Classify each entity below into EXACTLY ONE category. Return JSON array of objects with "entity" and "category" fields.

Categories:
- MENTAL_MODEL: A way of thinking, a principle, a design philosophy (e.g. "Blast Radius", "Zero Trust", "Assume Failure")
- PATTERN: An architectural or design pattern (e.g. "Circuit Breaker", "Blue/Green Deployment", "CQRS")
- AZURE_SERVICE: A specific Azure product or service (e.g. "Azure Cosmos DB", "AKS")
- METRIC: A measurable indicator or objective (e.g. "RTO", "SLA", "Latency")
- PROCESS: A practice, workflow, or methodology (e.g. "Chaos Engineering", "CI/CD")
- CONCEPT: A technical concept that is NOT a mental model (e.g. "Availability Zone", "TLS", "Partition Key")
- TRADEOFF: A tension between competing concerns (e.g. "Reliability vs Cost")
- ANTI_PATTERN: Something to avoid (e.g. "Noisy Neighbor", "Retry Storm")
- OTHER: Doesn't fit above

Entities:
{entity_list}

Return ONLY valid JSON array. No markdown fences."""

    result = await openai_complete_if_cache(
        LLM_MODEL,
        prompt,
        base_url=PROXY_URL,
        api_key=API_KEY,
    )

    try:
        # Extract JSON from response
        match = re.search(r"\[.*\]", result, re.DOTALL)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass
    return []


async def extract_facts(entities, descriptions, nodes, edges):
    """Extract and classify facts vs timeless principles.

    Returns a list of fact objects with shelf-life metadata.
    Timeless principles (theory) don't need verification.
    Time-sensitive facts (specific numbers, versions, limits) do.
    """
    from lightrag.llm.openai import openai_complete_if_cache

    all_facts = []
    batch_size = 30

    for i in range(0, len(entities), batch_size):
        batch = entities[i:i + batch_size]
        entity_context = []
        for e in batch:
            desc = descriptions.get(e, "(no description)")[:300]
            neighbors = sorted(find_neighbors(e, edges))[:10]
            entity_context.append(f"- {e}: {desc} [connected to: {', '.join(neighbors[:5])}]")

        prompt = f"""Analyze these entities from the Azure Well-Architected Framework knowledge graph.
For each entity, extract specific FACTS — concrete, verifiable claims embedded in the description.

Classify each fact as:
- "timeless": A principle, theory, or design philosophy that doesn't expire
  (e.g., "Minimize blast radius", "Design for failure", "Use defense in depth")
- "perishable": A specific claim about a service, limit, version, or capability that may change
  (e.g., "Cosmos DB supports up to 100K RU/s", "AKS supports Kubernetes 1.28", "SLA of 99.99%")

For perishable facts, estimate shelf_life_months (how long before this fact should be re-verified).

Return a JSON array of objects:
[{{
  "entity": "entity name",
  "fact": "the specific factual claim",
  "type": "timeless" or "perishable",
  "shelf_life_months": number (0 for timeless, 3-24 for perishable),
  "verification_hint": "how to verify this fact" (for perishable only),
  "confidence": "high" or "medium" or "low"
}}]

Entities:
{chr(10).join(entity_context)}

Extract ALL facts you can find — be thorough. A single entity may have multiple facts.
Return ONLY valid JSON array. No markdown fences."""

        try:
            result = await openai_complete_if_cache(
                LLM_MODEL, prompt, base_url=PROXY_URL, api_key=API_KEY
            )
            match = re.search(r"\[.*\]", result, re.DOTALL)
            if match:
                facts = json.loads(match.group())
                all_facts.extend(facts)
                print(f"  Batch {i // batch_size + 1}: extracted {len(facts)} facts")
        except Exception as e:
            print(f"  Batch {i // batch_size + 1} ERROR: {e}")

    return all_facts


async def extract_mental_model_cards(mental_models, nodes, edges, max_cards=54):
    """For top mental models, generate structured cards using LLM + graph context."""
    from lightrag.llm.openai import openai_complete_if_cache

    cards = []
    for mm in mental_models[:max_cards]:
        name = mm["entity"]
        neighbors = find_neighbors(name, edges)
        neighbor_names = sorted(neighbors)[:20]
        description = nodes.get(name, {}).get("description", nodes.get(name, {}).get("entity_type", ""))

        prompt = f"""Given this concept from the Azure Well-Architected Framework knowledge graph:

Entity: {name}
Description: {description[:500]}
Connected to: {', '.join(neighbor_names)}

Create a mental model card as JSON with these fields:
- "name": the concept name
- "mantra": one punchy sentence (imperative, memorable)
- "layer": one of ["foundational", "structural", "operational", "security", "organizational", "data"]
- "when_to_apply": list of 3-5 situations (short bullets)
- "without_it": list of 3-5 failure modes
- "key_tradeoff": one sentence about the primary tension
- "builds_on": list of prerequisite mental models from: {', '.join(neighbor_names)}
- "enables": list of downstream mental models from: {', '.join(neighbor_names)}
- "connections": count of graph connections ({len(neighbors)})

Return ONLY valid JSON. No markdown."""

        try:
            result = await openai_complete_if_cache(
                LLM_MODEL, prompt, base_url=PROXY_URL, api_key=API_KEY
            )
            match = re.search(r"\{.*\}", result, re.DOTALL)
            if match:
                card = json.loads(match.group())
                cards.append(card)
                print(f"  ✅ {name}")
        except Exception as e:
            print(f"  ❌ {name}: {e}")

    return cards


def generate_html_report(taxonomy, cards, centrality, bridge_scores, nodes, edges):
    """Generate an interactive HTML report of mental models."""
    # Build graph data for D3
    graph_nodes = []
    graph_edges = []

    category_colors = {
        "MENTAL_MODEL": "#f59e0b",
        "PATTERN": "#3b82f6",
        "PROCESS": "#10b981",
        "METRIC": "#ef4444",
        "AZURE_SERVICE": "#6366f1",
        "CONCEPT": "#8b949e",
        "TRADEOFF": "#f97316",
        "ANTI_PATTERN": "#dc2626",
        "OTHER": "#4b5563",
    }

    # Only include classified entities
    classified_ids = {item["entity"] for item in taxonomy}
    for item in taxonomy:
        eid = item["entity"]
        cat = item["category"]
        graph_nodes.append({
            "id": eid,
            "label": eid,
            "type": cat,
            "color": category_colors.get(cat, "#8b949e"),
            "size": 4 + min(centrality.get(eid, 0), 30),
            "centrality": centrality.get(eid, 0),
            "bridge": round(bridge_scores.get(eid, 0), 3),
        })

    for e in edges:
        if e["source"] in classified_ids and e["target"] in classified_ids:
            graph_edges.append({
                "source": e["source"],
                "target": e["target"],
                "description": e.get("description", "")[:100],
            })

    report_data = {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "cards": cards,
        "stats": {
            "total_entities": len(nodes),
            "classified": len(taxonomy),
            "mental_models": sum(1 for t in taxonomy if t["category"] == "MENTAL_MODEL"),
            "patterns": sum(1 for t in taxonomy if t["category"] == "PATTERN"),
            "tradeoffs": sum(1 for t in taxonomy if t["category"] == "TRADEOFF"),
            "anti_patterns": sum(1 for t in taxonomy if t["category"] == "ANTI_PATTERN"),
        },
        "categories": dict(Counter(t["category"] for t in taxonomy).most_common()),
    }

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Mental Model Mining — Mission-Critical WAF</title>
<style>
  :root {{
    --bg:#0d1117; --panel:#161b22; --border:#30363d; --fg:#c9d1d9;
    --muted:#8b949e; --accent:#58a6ff;
  }}
  html,body {{ margin:0; height:100%; background:var(--bg); color:var(--fg);
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  #app {{ display:flex; height:100vh; }}
  #sidebar {{ width:400px; background:var(--panel); border-right:1px solid var(--border);
    padding:16px; box-sizing:border-box; overflow-y:auto; }}
  h1 {{ font-size:18px; margin:0 0 8px; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--muted); margin:16px 0 8px; font-weight:600; }}
  .stat {{ display:inline-block; background:#21262d; border:1px solid var(--border);
    border-radius:8px; padding:8px 12px; margin:4px; text-align:center; }}
  .stat .n {{ font-size:22px; font-weight:700; color:var(--accent); }}
  .stat .l {{ font-size:11px; color:var(--muted); }}
  .card {{ background:#21262d; border:1px solid var(--border); border-radius:8px;
    padding:12px; margin:8px 0; }}
  .card h3 {{ margin:0 0 4px; font-size:14px; color:var(--accent); }}
  .card .mantra {{ font-style:italic; color:#e6edf3; margin:4px 0 8px; font-size:13px; }}
  .card .meta {{ font-size:11px; color:var(--muted); }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px;
    margin:2px; font-weight:600; }}
  .list {{ font-size:12px; margin:4px 0; padding-left:16px; }}
  .list li {{ margin:2px 0; }}
  #graph {{ flex:1; position:relative; }}
  svg {{ width:100%; height:100%; }}
  .node circle {{ stroke:#0d1117; stroke-width:1.5; cursor:pointer; }}
  .node text {{ fill:var(--fg); font-size:9px; pointer-events:none;
    paint-order:stroke; stroke:#0d1117; stroke-width:3px; }}
  .link {{ stroke:var(--border); stroke-opacity:0.3; }}
  .node.dim {{ opacity:0.06; }}
  .link.dim {{ stroke-opacity:0.03; }}
  .link.hi {{ stroke:#ffd33d; stroke-opacity:0.8; }}
  input[type=search] {{ width:100%; box-sizing:border-box; background:#0d1117;
    border:1px solid var(--border); color:var(--fg); padding:6px 8px;
    border-radius:6px; font-size:13px; }}
  .chip {{ display:inline-flex; align-items:center; gap:4px; padding:2px 8px;
    background:#21262d; border:1px solid var(--border); border-radius:10px;
    font-size:11px; cursor:pointer; margin:2px; }}
  .chip input {{ margin:0; }}
  .swatch {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
  button {{ background:#21262d; color:var(--fg); border:1px solid var(--border);
    border-radius:6px; padding:4px 10px; font-size:12px; cursor:pointer; }}
  button:hover {{ border-color:var(--accent); }}
</style>
</head>
<body>
<div id="app">
  <aside id="sidebar">
    <h1>🧠 Mental Model Mining</h1>
    <div style="color:var(--muted);font-size:12px;margin-bottom:12px;">
      Extracted from {report_data['stats']['total_entities']} entities in the WAF knowledge graph
    </div>

    <div>
      <div class="stat"><div class="n">{report_data['stats']['mental_models']}</div><div class="l">Mental Models</div></div>
      <div class="stat"><div class="n">{report_data['stats']['patterns']}</div><div class="l">Patterns</div></div>
      <div class="stat"><div class="n">{report_data['stats']['tradeoffs']}</div><div class="l">Tradeoffs</div></div>
      <div class="stat"><div class="n">{report_data['stats']['anti_patterns']}</div><div class="l">Anti-patterns</div></div>
    </div>

    <h2>Search</h2>
    <input id="q" type="search" placeholder="Filter by name…"/>

    <h2>Filter by type</h2>
    <div id="filters"></div>

    <h2>Top Mental Model Cards</h2>
    <div id="cards"></div>
  </aside>
  <div id="graph"><svg></svg></div>
</div>

<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const DATA = {json.dumps(report_data)};

const COLORS = {json.dumps(category_colors)};

(function() {{
  // Filters
  const filterDiv = document.getElementById("filters");
  const activeTypes = new Set(Object.keys(DATA.categories));
  for (const [cat, count] of Object.entries(DATA.categories)) {{
    const label = document.createElement("label");
    label.className = "chip";
    label.innerHTML = `<input type="checkbox" data-type="${{cat}}" checked/>` +
      `<span class="swatch" style="background:${{COLORS[cat]||'#8b949e'}}"></span>${{cat}} (${{count}})`;
    filterDiv.appendChild(label);
  }}

  // Cards
  const cardsDiv = document.getElementById("cards");
  for (const card of DATA.cards) {{
    const div = document.createElement("div");
    div.className = "card";
    div.innerHTML = `
      <h3>${{card.name}}</h3>
      <div class="mantra">"${{card.mantra}}"</div>
      <div class="meta">
        <span class="badge" style="background:${{COLORS.MENTAL_MODEL}}40;color:${{COLORS.MENTAL_MODEL}}">${{card.layer}}</span>
        <span class="badge" style="background:#21262d">${{card.connections}} connections</span>
      </div>
      <div style="margin-top:8px">
        <strong style="font-size:11px">🎯 When to apply:</strong>
        <ul class="list">${{(card.when_to_apply||[]).map(w => '<li>'+w+'</li>').join('')}}</ul>
        <strong style="font-size:11px">💥 Without it:</strong>
        <ul class="list">${{(card.without_it||[]).map(w => '<li>'+w+'</li>').join('')}}</ul>
        <strong style="font-size:11px">⚖️ Tradeoff:</strong>
        <div style="font-size:12px;margin:4px 0">${{card.key_tradeoff||''}}</div>
      </div>`;
    cardsDiv.appendChild(div);
  }}

  // Graph
  const svg = d3.select("svg");
  const g = svg.append("g");
  const w = document.getElementById("graph").clientWidth;
  const h = document.getElementById("graph").clientHeight;
  svg.attr("viewBox", [-w/2,-h/2,w,h]);

  const zoom = d3.zoom().scaleExtent([0.1,5]).on("zoom", e => g.attr("transform", e.transform));
  svg.call(zoom);

  let allNodes = DATA.nodes.map(d => ({{...d}}));
  let allEdges = DATA.edges.map(d => ({{...d}}));

  const sim = d3.forceSimulation()
    .force("link", d3.forceLink().id(d=>d.id).distance(80).strength(0.4))
    .force("charge", d3.forceManyBody().strength(-120))
    .force("center", d3.forceCenter())
    .force("collide", d3.forceCollide().radius(d => d.size + 3));

  const linkG = g.append("g");
  const nodeG = g.append("g");
  let linkSel, nodeSel;
  let query = "";

  function render() {{
    const nodes = allNodes.filter(n => {{
      if (!activeTypes.has(n.type)) return false;
      if (query && !n.label.toLowerCase().includes(query)) return false;
      return true;
    }});
    const ids = new Set(nodes.map(n=>n.id));
    const edges = allEdges.filter(e =>
      ids.has(typeof e.source==="object"?e.source.id:e.source) &&
      ids.has(typeof e.target==="object"?e.target.id:e.target));

    linkSel = linkG.selectAll("line").data(edges, d=>(d.source.id||d.source)+"->"+(d.target.id||d.target))
      .join("line").attr("class","link").attr("stroke-width",0.5);

    nodeSel = nodeG.selectAll("g.node").data(nodes, d=>d.id)
      .join(enter => {{
        const ge = enter.append("g").attr("class","node")
          .call(d3.drag()
            .on("start",(e,d)=>{{if(!e.active)sim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y;}})
            .on("drag",(e,d)=>{{d.fx=e.x;d.fy=e.y;}})
            .on("end",(e,d)=>{{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null;}}))
          .on("mouseover",(e,d)=>highlight(d))
          .on("mouseout",()=>highlight(null));
        ge.append("circle").attr("r",d=>Math.max(3,d.size)).attr("fill",d=>d.color);
        ge.append("text").attr("dx",10).attr("dy",4).text(d=>d.label);
        return ge;
      }});

    sim.nodes(nodes).on("tick",()=>{{
      linkSel.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y)
             .attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);
      nodeSel.attr("transform",d=>`translate(${{d.x}},${{d.y}})`);
    }});
    sim.force("link").links(edges);
    sim.alpha(0.8).restart();
  }}

  function highlight(d) {{
    if (!d) {{ nodeSel.classed("dim",false); linkSel.classed("hi",false).classed("dim",false); return; }}
    const nb = new Set([d.id]);
    linkSel.each(function(l){{
      const s=l.source.id||l.source, t=l.target.id||l.target;
      if(s===d.id||t===d.id){{ nb.add(s);nb.add(t); }}
    }});
    nodeSel.classed("dim",n=>!nb.has(n.id));
    linkSel.classed("hi",l=>nb.has(l.source.id||l.source)&&nb.has(l.target.id||l.target))
           .classed("dim",l=>!(nb.has(l.source.id||l.source)&&nb.has(l.target.id||l.target)));
  }}

  document.getElementById("q").addEventListener("input", e => {{
    query = e.target.value.trim().toLowerCase();
    render();
  }});
  document.getElementById("filters").addEventListener("change", e => {{
    const t = e.target.dataset.type;
    if (t) {{ e.target.checked ? activeTypes.add(t) : activeTypes.delete(t); render(); }}
  }});

  render();
}})();
</script>
</body>
</html>"""
    return html


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mine mental models from LightRAG graph")
    parser.add_argument("--top", type=int, default=20, help="Number of top mental models to card")
    parser.add_argument("--query", type=str, help="Filter entities by name")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM classification, use cached")
    parser.add_argument("--domain", default=DEFAULT_DOMAIN, help="domain for RAG data (default: mission-critical)")
    args = parser.parse_args()

    print("Loading graph...")
    nodes, edges = load_graph(args.domain)
    print(f"  {len(nodes)} nodes, {len(edges)} edges")

    print("Computing centrality...")
    centrality = compute_centrality(nodes, edges)

    print("Computing bridge scores...")
    bridge_scores = find_bridges(edges)

    # Get descriptions from nodes
    descriptions = {}
    for nid, data in nodes.items():
        desc = data.get("description", data.get("entity_type", ""))
        descriptions[nid] = desc

    # Sort by centrality (most connected first)
    sorted_entities = sorted(nodes.keys(), key=lambda n: centrality.get(n, 0), reverse=True)

    if args.query:
        sorted_entities = [e for e in sorted_entities if args.query.lower() in e.lower()]
        print(f"  Filtered to {len(sorted_entities)} entities matching '{args.query}'")

    taxonomy_path = OUT_DIR / "taxonomy.json"
    OUT_DIR.mkdir(exist_ok=True)

    if args.skip_llm and taxonomy_path.exists():
        print("Loading cached taxonomy...")
        taxonomy = json.loads(taxonomy_path.read_text())
    else:
        # Classify in batches of 40
        print(f"Classifying {len(sorted_entities)} entities with {LLM_MODEL}...")
        taxonomy = []
        batch_size = 40
        for i in range(0, len(sorted_entities), batch_size):
            batch = sorted_entities[i:i + batch_size]
            print(f"  Batch {i // batch_size + 1}/{(len(sorted_entities) + batch_size - 1) // batch_size}...")
            try:
                results = await classify_entities(batch, descriptions)
                taxonomy.extend(results)
            except Exception as e:
                print(f"  Error: {e}")
                # Fallback: classify as OTHER
                taxonomy.extend([{"entity": e, "category": "OTHER"} for e in batch])

        # Save taxonomy
        taxonomy_path.write_text(json.dumps(taxonomy, indent=2))
        print(f"  Saved taxonomy to {taxonomy_path}")

    # Stats
    cat_counts = Counter(t["category"] for t in taxonomy)
    print("\n=== CLASSIFICATION RESULTS ===")
    for cat, count in cat_counts.most_common():
        print(f"  {cat}: {count}")

    # Extract mental models sorted by centrality
    mental_models = [
        t for t in taxonomy if t["category"] == "MENTAL_MODEL"
    ]
    mental_models.sort(key=lambda t: centrality.get(t["entity"], 0), reverse=True)

    print(f"\n=== TOP {args.top} MENTAL MODELS (by graph centrality) ===")
    for i, mm in enumerate(mental_models[:args.top], 1):
        name = mm["entity"]
        deg = centrality.get(name, 0)
        bridge = bridge_scores.get(name, 0)
        print(f"  {i:2d}. {name} (connections:{deg}, bridge:{bridge:.2f})")

    # Generate mental model cards
    print(f"\nGenerating {min(args.top, len(mental_models))} mental model cards...")
    cards = await extract_mental_model_cards(mental_models[:args.top], nodes, edges)

    cards_path = OUT_DIR / "cards.json"
    cards_path.write_text(json.dumps(cards, indent=2))
    print(f"  Saved {len(cards)} cards to {cards_path}")

    # Extract facts (timeless vs perishable)
    print(f"\nExtracting facts from {len(sorted_entities)} entities...")
    facts = await extract_facts(sorted_entities, descriptions, nodes, edges)

    timeless = [f for f in facts if f.get("type") == "timeless"]
    perishable = [f for f in facts if f.get("type") == "perishable"]

    facts_path = OUT_DIR / "facts.json"
    facts_path.write_text(json.dumps(facts, indent=2))
    print(f"  Saved {len(facts)} facts ({len(timeless)} timeless, {len(perishable)} perishable)")

    # Find tradeoffs
    tradeoffs = [t for t in taxonomy if t["category"] == "TRADEOFF"]
    print(f"\n=== TRADEOFFS ({len(tradeoffs)}) ===")
    for t in tradeoffs:
        print(f"  ⚖️  {t['entity']}")

    # Find anti-patterns
    anti_patterns = [t for t in taxonomy if t["category"] == "ANTI_PATTERN"]
    print(f"\n=== ANTI-PATTERNS ({len(anti_patterns)}) ===")
    for t in anti_patterns:
        print(f"  🚫 {t['entity']}")

    # Generate HTML report
    print("\nGenerating HTML report...")
    html = generate_html_report(taxonomy, cards, centrality, bridge_scores, nodes, edges)
    html_path = OUT_DIR / "index.html"
    html_path.write_text(html)
    print(f"  Saved to {html_path}")

    # Summary JSON
    summary = {
        "total_entities": len(nodes),
        "total_edges": len(edges),
        "classified": len(taxonomy),
        "categories": dict(cat_counts.most_common()),
        "top_mental_models": [
            {
                "name": mm["entity"],
                "centrality": centrality.get(mm["entity"], 0),
                "bridge_score": round(bridge_scores.get(mm["entity"], 0), 3),
            }
            for mm in mental_models[:args.top]
        ],
        "tradeoffs": [t["entity"] for t in tradeoffs],
        "anti_patterns": [t["entity"] for t in anti_patterns],
        "facts": {
            "total": len(facts),
            "timeless": len(timeless),
            "perishable": len(perishable),
            "perishable_by_shelf_life": dict(Counter(
                f.get("shelf_life_months", 0) for f in perishable
            )),
        },
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n✅ Done! Open {html_path} or run:")
    print(f"   open {html_path}")
    print(f"   python3 -m http.server 8767 -d {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
