# OrnefniCurate

Picks the most interesting LMÍ place names (örnefni) and turns them into full
KringumDB items: an English title and story, a cleaned Icelandic story, and a
standard category in front of the Örnefni tag (`Saga;Örnefni`,
`Menning;Örnefni`, `Náttúra;Örnefni`). Unlike plain `Örnefni` items, these show
on the map, are in the Auto Guide and the English export, and are rendered by
`tts/batch_tts.py` (render their audio before shipping an export, or the app
shows an audio button with nothing behind it).

The curated text lives in `curated.json` (committed), keyed by each place name's
LMÍ `uuid`. `Tools/OrnefniImport/import_ornefni.py` applies it on every import,
so **edit curated stories in `curated.json`, not in kringum.db**: the next
import overwrites the database copy. To drop a curated place name (such as a
duplicate of a nearby one), move its entry from `items` to `dropped` with a
`reason` and re-run the import: its row becomes a plain `Örnefni` item and
keeps its id, and `build_curated.py` never adds it back.

| Step | Script | Output |
|---|---|---|
| 1. Fetch every importable place name from LMÍ's live WFS service | `fetch_ornefni.py` | `data/ornefni_all.json` |
| 2. Rule-based filter: cleaned description ≥ 150 characters, or a folklore / death / history keyword; offshore names dropped | `prefilter.py` | `data/candidates.json` |
| 3. AI scoring with Claude Haiku 5.5: score 0–5, category, reason and an English gist. Shared descriptions are scored once | `score_ornefni.py` | `data/scores.jsonl` |
| 4. Review the scores and choose the cut-off | `report_scores.py` | `data/scores_report.csv` |
| 5. Write the English title and story and the cleaned Icelandic story for every place name scored ≥ 3 (Claude Opus 5.5). One request per place name; the writer skips names whose description has nothing to tell or is about a neighbour | `write_stories.py` | `data/stories.jsonl`, `data/stories_review.csv` |
| 6. Build the curation file (keeps existing entries, adds new ones) | `build_curated.py` | `curated.json` |
| 7. Import into kringum.db (matched on uuid, ids stay stable) | `../OrnefniImport/import_ornefni.py` | `kringum.db` |

`data/` is not committed: it is regenerated from the live service, which
LMÍ updates weekly.

```bash
python fetch_ornefni.py
python prefilter.py
python score_ornefni.py --pilot 300      # random sample of 300 descriptions
python report_scores.py
python write_stories.py                  # --scores data/pilot_scores.jsonl for a trial
python build_curated.py
python ../OrnefniImport/import_ornefni.py --dry-run   # then without --dry-run
```

`fetch_ornefni.py` asks the service for ISN93 (EPSG:3057) coordinates and
converts them itself, because the service rounds EPSG:4326 output to 4 decimals.

`score_ornefni.py` needs an API key in `ANTHROPIC_API_KEY` or `ORNEFNI_KEY`
(environment or the repo's `.env`; in Claude Code cloud sessions use
`ORNEFNI_KEY`, because `ANTHROPIC_API_KEY` is not passed through to commands)
and the `anthropic` Python package. It appends to `data/scores.jsonl` and skips
descriptions already scored, so it can be stopped and restarted, and a full run
after the pilot only scores the rest. `--dry-run` prints the prompt without
calling the API.

Run on release IS 50V 19.11.2026 (fetched 2026-11-23): 57,682 place names,
15,218 candidates (13,153 unique descriptions); 4,192 place names scored ≥ 3,
4,028 written (164 skipped); 6 same-name duplicates dropped, leaving 4,022:
2,273 Saga, 1,464 Menning, 285 Náttúra. Cost:
scoring $1.51 (Haiku 5.5), stories $51.53 (Opus 5.5).
