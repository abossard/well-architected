import json, pathlib

CARDS_PATH = pathlib.Path("/Users/abossard/Desktop/cxe/well-architected/kg-explorer/mental_models/cards.json")
cards = json.loads(CARDS_PATH.read_text())
by_name = {c["name"]: c for c in cards}

# Merge groups: canonical -> [duplicates to remove]
groups = {
    "Zero Trust": [
        "Microsoft Zero Trust Model", "Zero Trust Model", "Zero-Trust Architecture",
        "Zero-Trust Model", "Zero Trust Architecture",
    ],
    "Defense in Depth": ["Defense-In-Depth", "Defense In Depth"],
    "Blast Radius": ["Blast Radius Reduction And Fault Isolation"],
    "Least Privilege": ["Least-Privilege Access"],
    "Automation": ["Drive Automation"],
    "Simplicity": ["Principle Of Simplicity", "Complexity Avoidance"],
}

removed = set()
# Handle "Defense in Depth" rename specially: canonical not in data
for canonical, dupes in groups.items():
    existing = [n for n in [canonical] + dupes if n in by_name]
    if not existing:
        continue
    # Pick best: prefer canonical-named if exists, else first
    keep_name = canonical if canonical in by_name else existing[0]
    keep = by_name[keep_name]
    # Sum connections across all group members to preserve graph weight
    total_conn = sum(by_name[n].get("connections", 0) for n in existing)
    keep["connections"] = total_conn
    # Rename to canonical
    keep["name"] = canonical
    by_name[canonical] = keep
    for n in existing:
        if n != keep_name:
            removed.add(n)
    if keep_name != canonical and keep_name in by_name:
        # We already renamed the card; remove old entry if different key
        if keep_name != canonical:
            removed.add(keep_name)

# Rebuild: preserve original order, skip removed, dedupe canonical
seen = set()
final = []
for c in cards:
    n = c["name"]
    if n in removed:
        continue
    canonical_name = n
    for can, dupes in groups.items():
        if n == can or n in dupes:
            canonical_name = can
            break
    if canonical_name in seen:
        continue
    seen.add(canonical_name)
    final.append(by_name[canonical_name])

# Also fix references inside builds_on/enables to renamed cards
rename_map = {}
for can, dupes in groups.items():
    for d in dupes:
        rename_map[d] = can

valid_names = {c["name"] for c in final}
for c in final:
    for key in ("builds_on", "enables"):
        new_list = []
        seen_refs = set()
        for ref in c.get(key, []):
            ref2 = rename_map.get(ref, ref)
            if ref2 == c["name"]:
                continue
            if ref2 in seen_refs:
                continue
            seen_refs.add(ref2)
            new_list.append(ref2)
        c[key] = new_list

CARDS_PATH.write_text(json.dumps(final, indent=2))
print(f"Final count: {len(final)}")
print(f"Removed {len(removed)}: {sorted(removed)}")
print("\nFinal cards:")
for c in final:
    print(f"  {c['name']} | {c['mantra']}")
