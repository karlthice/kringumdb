# OrnefniCurate scoring pilot: run plan

These are the steps for a cloud session to run the pilot. Do not change code or commit.

## Environment setup (do this once in the environment's settings)

- **Network:** allow `gis.lmi.is` (for fetching the place names) and `api.anthropic.com` (for scoring).
- **Environment variable:** `ORNEFNI_KEY=<your Anthropic API key>`.
  In the last attempt, a variable named `ANTHROPIC_API_KEY` was saved on the
  environment but never reached the session's commands. Use the
  `ORNEFNI_KEY` name instead; the scoring step passes it to the script.

## Steps

1. Check the key is visible. Print only whether it is set and its length:
   `[ -n "$ORNEFNI_KEY" ] && echo "set, length ${#ORNEFNI_KEY}" || echo "NOT set"`
   If it is not set, stop and report.
2. `pip install anthropic requests`
3. `cd Tools/OrnefniCurate && python fetch_ornefni.py && python prefilter.py`
   (rebuilds `data/`, takes about 15 s)
4. Score a seeded sample of 300 descriptions with Claude Haiku 5.5. The run is resumable and costs a few cents:
   `env -u ANTHROPIC_BASE_URL ANTHROPIC_API_KEY="$ORNEFNI_KEY" python score_ornefni.py --pilot 300`
   (`env -u ANTHROPIC_BASE_URL` stops the session's own Claude endpoint
   setting from redirecting the script's API calls.)
5. `python report_scores.py --examples 4`

If a step fails, stop and report the exact error output.

## Report back

- The summary lines from `fetch_ornefni.py` and `prefilter.py`.
- The full output of `report_scores.py`.
- The number of rows in `data/scores_report.csv`.
- Every row in `data/scores_report.csv` with score 5 or 4, listed as
  `score | ornefni | nafnberi | category | gist`.
