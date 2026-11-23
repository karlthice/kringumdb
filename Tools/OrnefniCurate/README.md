# OrnefniCurate

Picks the most interesting LMÍ place names (örnefni) and gives them English
stories for the English version of KringumDB. The English text will be stored
in `curated.json`, keyed by each place name's LMÍ `uuid`, and
`Tools/OrnefniImport/import_ornefni.py` will apply it on import, so re-imports
never lose it.

| Step | Script | Output |
|---|---|---|
| 1. Fetch every importable place name from LMÍ's live WFS service | `fetch_ornefni.py` | `data/ornefni_all.json` |
| 2. Rule-based filter: cleaned description ≥ 150 characters, or a folklore / death / history keyword; offshore names dropped | `prefilter.py` | `data/candidates.json` |
| 3. AI scoring (0–5, category, reason) | not written yet | |
| 4. Pilot on a sample and choose the cut-off | not written yet | |
| 5. Write English stories | not written yet | `curated.json` |

`data/` is not committed: it is regenerated from the live service, which
LMÍ updates weekly.

```bash
python fetch_ornefni.py
python prefilter.py
```

Run on release IS 50V 19.11.2026 (fetched 2026-11-23): 57,682 place names,
15,218 candidates (13,153 unique descriptions).
