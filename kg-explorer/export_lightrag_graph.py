#!/usr/bin/env python3
"""Export LightRAG's full knowledge graph to D3-compatible graph.json.

Reads the GraphML from LightRAG (4099 entities, 5896 relations from 221 docs)
and outputs a graph.json for the D3 force-directed visualization.

Usage: python3 export_lightrag_graph.py
"""
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
GRAPHML = ROOT / "lightrag_data" / "graph_chunk_entity_relation.graphml"
TAXONOMY = ROOT / "mental_models" / "taxonomy.json"
OUT = ROOT / "graph.json"

LEARN_BASE = "https://learn.microsoft.com/azure/well-architected"

# Map WAF directory → Learn URL segment
DIR_TO_URL = {
    "mission-critical": "mission-critical",
    "reliability": "reliability",
    "security": "security",
    "performance-efficiency": "performance-efficiency",
    "operational-excellence": "operational-excellence",
    "cost-optimization": "cost-optimization",
    "design-guides": "design-guides",
    "service-guides": "service-guides",
    "ai": "ai",
    "saas": "saas",
    "azure-virtual-desktop": "azure-virtual-desktop",
    "azure-vmware": "azure-vmware",
    "sustainability": "sustainability",
    "sap": "sap",
    "hpc": "hpc",
    "architect-role": "architect-role",
}

TYPE_COLORS = {
    "MENTAL_MODEL": "#f59e0b",
    "PATTERN": "#3b82f6",
    "AZURE_SERVICE": "#6366f1",
    "PROCESS": "#10b981",
    "CONCEPT": "#8b949e",
    "METRIC": "#ef4444",
    "TRADEOFF": "#7dd3fc",
    "ANTI_PATTERN": "#f87171",
    "OTHER": "#4b5563",
}


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def load_taxonomy():
    """Load entity classifications from taxonomy.json."""
    if not TAXONOMY.exists():
        return {}
    data = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    return {item["entity"]: item["category"] for item in data}


def parse_graphml():
    """Parse LightRAG's GraphML into nodes and edges."""
    tree = ET.parse(GRAPHML)
    root = tree.getroot()

    # Find key definitions
    key_map = {}
    for elem in root.iter():
        if elem.tag.endswith("key"):
            key_map[elem.get("id", "")] = elem.get("attr.name", elem.get("id", ""))

    nodes = {}
    edges = []

    for elem in root.iter():
        if elem.tag.endswith("node"):
            nid = elem.get("id", "")
            data = {}
            for d in elem:
                if d.tag.endswith("data"):
                    key = key_map.get(d.get("key", ""), d.get("key", ""))
                    data[key] = (d.text or "")
            nodes[nid] = data

        elif elem.tag.endswith("edge"):
            source = elem.get("source", "")
            target = elem.get("target", "")
            data = {}
            for d in elem:
                if d.tag.endswith("data"):
                    key = key_map.get(d.get("key", ""), d.get("key", ""))
                    data[key] = (d.text or "")
            edges.append({"source": source, "target": target, **data})

    return nodes, edges


def build_d3_graph():
    taxonomy = load_taxonomy()
    nodes_raw, edges_raw = parse_graphml()

    print(f"GraphML: {len(nodes_raw)} nodes, {len(edges_raw)} edges")

    # Compute degree for sizing
    degree = Counter()
    for e in edges_raw:
        degree[e["source"]] += 1
        degree[e["target"]] += 1

    # Build D3 nodes
    d3_nodes = []
    node_ids = set()

    for nid, data in nodes_raw.items():
        entity_type = data.get("entity_type", "")
        description = data.get("description", "")

        # Classify using taxonomy, fall back to entity_type
        category = taxonomy.get(nid, "OTHER")

        # Size based on degree
        deg = degree.get(nid, 0)
        size = 3 + min(deg * 2, 25)

        node = {
            "id": nid,
            "label": nid,
            "type": category,
            "size": size,
            "connections": deg,
            "description": description[:200] if description else "",
        }

        d3_nodes.append(node)
        node_ids.add(nid)

    # Build D3 edges (only between existing nodes)
    d3_edges = []
    for e in edges_raw:
        if e["source"] in node_ids and e["target"] in node_ids:
            edge = {
                "source": e["source"],
                "target": e["target"],
            }
            desc = e.get("description", "")
            if desc:
                edge["description"] = desc[:100]
            d3_edges.append(edge)

    # Type stats
    type_counts = Counter(n["type"] for n in d3_nodes)
    print(f"\nNode types:")
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")

    graph = {
        "nodes": d3_nodes,
        "edges": d3_edges,
        "meta": {
            "docs": 221,
            "nodes": len(d3_nodes),
            "edges": len(d3_edges),
            "source": "LightRAG full WAF corpus",
        }
    }

    OUT.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {OUT}: {len(d3_nodes)} nodes, {len(d3_edges)} edges")


if __name__ == "__main__":
    build_d3_graph()
