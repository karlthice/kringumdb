# TTS — Icelandic audio for `items.story`

Renders the Icelandic `story` text of each row in `items` (from `../kringum.db`)
to a mono MP3. Output goes to `audio/<id>.mp3`. Two engines:

| `--engine` | Voices | Quality | Cost | Notes |
|------------|--------|---------|------|-------|
| `piper` (default) | Talrómur: Búi, Salka, Steinn, Ugla | ok | free, offline | [Piper](https://github.com/OHF-Voice/piper1-gpl); numbers normalized to words first |
| `edge` | Azure neural: Guðrún, Gunnar | best | free, cloud | [edge-tts](https://github.com/rany2/edge-tts); handles numbers itself |

> ⚠️ The `edge` engine uses an **unofficial** Microsoft Edge endpoint. Great for
> evaluation/personal use, but for **published** audio use the official
> [Azure AI Speech](https://learn.microsoft.com/azure/ai-services/speech-service/)
> API (same Guðrún/Gunnar voices) to be properly licensed.

## Setup

Dependencies live in the project's `venv` (see `../requirements.txt`):

```bash
../venv/bin/python -m pip install -r ../requirements.txt   # installs piper-tts
```

Also requires **ffmpeg** on the system path (`brew install ffmpeg`).

Piper voice models are cached in `voices/` (downloaded automatically on first
use; ~80 MB each, git-ignored).

## Single paragraph / ad-hoc text

```bash
../venv/bin/python icelandic_tts.py -t "Halló, heimur." -o halló.mp3
../venv/bin/python icelandic_tts.py            # reads a built-in sample paragraph
```

## Batch over the database

```bash
# Quick sample
../venv/bin/python batch_tts.py --limit 5

# Specific items, two voices side by side for comparison
../venv/bin/python batch_tts.py --ids 9,10,13 -v is_IS-bui-medium --name-with-voice

# Full run (all ~6800 items with a story), 8 workers, with paragraph pauses
../venv/bin/python batch_tts.py --jobs 8 --paragraph-silence 0.6 --length-scale 1.05

# Same, but the better Azure neural voice Guðrún (free via edge-tts)
../venv/bin/python batch_tts.py --engine edge -v is-IS-GudrunNeural --jobs 6

# Alternate voices by item id (odd -> Gunnar, even -> Guðrún), small mono files
../venv/bin/python batch_tts.py --engine edge --alternate -b 32k --jobs 6
```

Every `edge` output is re-encoded through ffmpeg to **mono** at `--bitrate`
(default 64k; use `32k` for small speech files — ~210 KB per item, ~1.4 GB for
the whole corpus).

The batch is **resumable**: items whose MP3 already exists in `audio/` are
skipped, so it is safe to interrupt and restart.

### Useful flags

| Flag | Meaning |
|------|---------|
| `--engine` | `piper` (default) or `edge` |
| `-v, --voice` | piper: `is_IS-salka-medium` (default), `-bui-`, `-steinn-`, `-ugla-`; edge: `is-IS-GudrunNeural` (default), `is-IS-GunnarNeural` |
| `--jobs N` | worker processes (default 4) |
| `--paragraph-silence S` | extra silence (seconds) at paragraph breaks (piper only) |
| `--length-scale X` | speech pace; `>1.0` is slower/clearer (piper only) |
| `--retries N` | per-item retries for the `edge` engine (default 4) |
| `--alternate` | edge: odd ids → Gunnar, even ids → Guðrún |
| `-b, --bitrate` | output MP3 bitrate, always mono (e.g. `32k` for small speech files) |
| `--name-with-voice` | name files `<id>-<voice>.mp3` (for A/B comparison) |
| `--visible-only` | only `visibility = 1` |
| `--exclude-tag` | comma-separated tags to skip (substring match). Default `Örnefni`; pass `''` to disable |
| `--overwrite` | re-render even if the MP3 exists |

**Note:** items tagged `Örnefni` (the bulk-imported place-name gazetteer, ~54k
rows) are **excluded by default** and intentionally have no audio. Only the
~6,800 non-`Örnefni` stories are rendered.

## Text & number handling

Two normalization passes in `icelandic_tts.py`, applied before synthesis:

1. **`normalize_text()`** — engine-agnostic, run for **both** engines. Ported
   from the original C# pre-processor: expands abbreviations (`klst`,
   `u.þ.b.`, `t.d.`, `m.a.`, …), units (`m²`/`km²`/`km³`/`MW`/`ha`/`fm`/
   `m y.s` → full words), compass directions (`NV`→norðvestur, `SSA`→…),
   number/year ranges (`1908-1912` → "1908 til 1912"), HTML breaks
   (`<br>`/`<p>` → paragraph break), `&` → "og", and strips footnote markers
   like `(1,2,3)`. Edit `_TEXT_RULES` to add/remove rules.

   Note: bare `km`, `%`, `cm` are **left as-is** — the neural (edge) voices
   read them correctly with proper inflection. Add them to `_TEXT_RULES` if you
   need them spelled out for Piper.

2. **`normalize_icelandic_numbers()`** — **Piper only** (the neural voices read
   digits themselves). Spells digits as Icelandic words: years the natural way
   (`1908` → "nítján hundruð og átta"), numerals 1–4 agreeing with a following
   noun's gender, and the genitive in attributive measure phrases
   (`1682 metra hátt` → "...áttatíu og tveggja metra hátt"). Extend
   `_UNIT_GENDER` / `_DIM_ADJ` as new units show up.

## Layout

```
tts/
├── icelandic_tts.py   # core: normalization + Piper synthesis + MP3 encode
├── batch_tts.py       # DB-driven batch renderer (parallel, resumable)
├── voices/            # cached Piper models (git-ignored)
├── audio/             # rendered <id>.mp3 output (git-ignored)
└── compare/           # ad-hoc A/B comparison renders (git-ignored)
```
