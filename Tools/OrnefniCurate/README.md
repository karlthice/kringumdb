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
| 3. AI scoring with Claude Haiku 5.5: score 0–5, category, reason and an English gist. Shared descriptions are scored once | `score_ornefni.py` | `data/scores.jsonl` |
| 4. Review the scores and choose the cut-off | `report_scores.py` | `data/scores_report.csv` |
| 5. Write English stories | not written yet | `curated.json` |

`data/` is not committed: it is regenerated from the live service, which
LMÍ updates weekly.

```bash
python fetch_ornefni.py
python prefilter.py
python score_ornefni.py --pilot 300      # random sample of 300 descriptions
python report_scores.py
```

`score_ornefni.py` needs `ANTHROPIC_API_KEY` (environment or the repo's `.env`)
and the `anthropic` Python package. It appends to `data/scores.jsonl` and skips
descriptions already scored, so it can be stopped and restarted, and a full run
after the pilot only scores the rest. `--dry-run` prints the prompt without
calling the API.

Run on release IS 50V 19.11.2026 (fetched 2026-11-23): 57,682 place names,
15,218 candidates (13,153 unique descriptions).
