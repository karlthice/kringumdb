#!/usr/bin/env python3
"""Batch-render Icelandic `items.story` text from the Kringum SQLite DB to MP3.

Reads rows from ../kringum.db (the project's database, one level up from this
tts/ folder) and writes one mono MP3 per item into ./audio. Two engines:

  piper  (default) — local Talrómur voices (Búi/Salka/...), free & offline.
                     Numbers are normalized to Icelandic words first.
  edge             — Microsoft Edge neural voices (Guðrún/Gunnar) via edge-tts.
                     Cloud, free, no key. Handles numbers/dates itself.
                     NOTE: uses an unofficial endpoint — fine for evaluation,
                     but use official Azure AI Speech for published output.

Resumable: items whose output MP3 already exists are skipped, so the job can
be interrupted and restarted. Parallelism via worker processes.

Examples:
    python batch_tts.py --limit 5                          # piper sample
    python batch_tts.py --engine edge -v is-IS-GudrunNeural --limit 5
    python batch_tts.py --jobs 8                            # full piper run
    python batch_tts.py --engine edge --jobs 6              # full Guðrún run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import icelandic_tts as itts

DEFAULT_DB = Path(__file__).resolve().parent.parent / "kringum.db"
DEFAULT_OUT = Path(__file__).resolve().parent / "audio"

# Edge (Azure neural) voices, used with --engine edge. Icelandic + English.
EDGE_VOICES = {
    # Icelandic (--lang is)
    "is-IS-GudrunNeural": "Guðrún — IS female",
    "is-IS-GunnarNeural": "Gunnar — IS male",
    # English (--lang en)
    "en-US-AndrewNeural": "Andrew — US male",
    "en-GB-SoniaNeural": "Sonia — UK female",
    "en-US-AvaNeural": "Ava — US female",
    "en-GB-RyanNeural": "Ryan — UK male",
    "en-US-AriaNeural": "Aria — US female",
}

# Per-language config: which story column to read, the default single voice,
# the odd/even alternation pair (male, female), and the valid voice set.
LANGS = {
    "is": {
        "field": "story",
        "default_voice": "is-IS-GudrunNeural",
        "alternate": ("is-IS-GunnarNeural", "is-IS-GudrunNeural"),
        "voices": ("is-IS-GudrunNeural", "is-IS-GunnarNeural"),
        "out_subdir": "audio",
    },
    "en": {
        "field": "story_eng",
        "default_voice": "en-US-AndrewNeural",
        "alternate": ("en-US-AndrewNeural", "en-GB-SoniaNeural"),
        "voices": ("en-US-AndrewNeural", "en-GB-SoniaNeural",
                   "en-US-AvaNeural", "en-GB-RyanNeural", "en-US-AriaNeural"),
        "out_subdir": "audio_en",
    },
}

# One Piper voice per worker process (piper engine only), loaded lazily.
_WORKER_VOICE = None  # type: ignore[var-annotated]
_WORKER_VOICE_NAME: str | None = None


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# Tags that should never be rendered. "Örnefni" (place-name gazetteer) was bulk-
# imported and is audio-out-of-scope. Tags are stored ';'-separated, so match as
# a substring.
DEFAULT_EXCLUDE_TAGS = ["Örnefni"]


def fetch_items(
    db_path: Path,
    *,
    field: str = "story",
    ids: list[int] | None = None,
    visible_only: bool = False,
    limit: int | None = None,
    exclude_tags: list[str] | None = None,
) -> list[sqlite3.Row]:
    """Return items whose `field` (story / story_eng) is non-empty.

    The chosen column is aliased to `story` so the rest of the pipeline is
    language-agnostic."""
    if field not in ("story", "story_eng"):  # guard against SQL injection
        raise ValueError(f"unsupported field: {field}")
    where = [f"{field} IS NOT NULL", f"TRIM({field}) <> ''"]
    params: list[object] = []
    if visible_only:
        where.append("visibility = 1")
    for tag in exclude_tags or []:
        where.append("(tag IS NULL OR tag NOT LIKE ?)")
        params.append(f"%{tag}%")
    if ids:
        where.append(f"id IN ({','.join('?' * len(ids))})")
        params.extend(ids)
    sql = (f"SELECT id, name, {field} AS story FROM items "
           f"WHERE {' AND '.join(where)} ORDER BY id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    with _connect(db_path) as conn:
        return conn.execute(sql, params).fetchall()


def _init_worker(engine: str, voice_name: str) -> None:
    """Per-process setup. For piper, load the voice once and reuse it."""
    global _WORKER_VOICE, _WORKER_VOICE_NAME
    if engine == "piper":
        from piper import PiperVoice
        model_path = itts.ensure_voice(voice_name, itts.VOICES_DIR)
        _WORKER_VOICE = PiperVoice.load(model_path)
        _WORKER_VOICE_NAME = voice_name
    # edge needs no per-worker state (each render is an independent network call)


def out_path_for(item_id: int, out_dir: Path, voice_tag: str | None = None) -> Path:
    # voice_tag = short voice name (e.g. "salka") for side-by-side comparison.
    if voice_tag:
        return out_dir / f"{item_id}-{voice_tag}.mp3"
    return out_dir / f"{item_id}.mp3"


def voice_tag_of(voice: str) -> str:
    # edge: "is-IS-GudrunNeural" -> "gudrun", "en-US-AndrewNeural" -> "andrew"
    if voice in EDGE_VOICES:
        return voice.split("-")[-1].replace("Neural", "").lower()
    # piper: "is_IS-salka-medium" -> "salka"
    return voice.split("-")[1] if "-" in voice else voice


def _has_speech(text: str) -> bool:
    """True if the text contains at least one letter (something to pronounce)."""
    return any(c.isalpha() for c in text)


def _render_piper(item_id: int, story: str, out: Path, opts: dict) -> tuple[int, str]:
    text = itts.normalize_icelandic_numbers(itts.normalize_text(story.strip()))
    if not _has_speech(text):
        return item_id, "empty"
    wav_bytes = itts.synthesize_wav_bytes(
        _WORKER_VOICE, text,
        length_scale=opts["length_scale"],
        noise_scale=opts["noise_scale"],
        noise_w_scale=opts["noise_w_scale"],
        paragraph_silence=opts["paragraph_silence"],
    )
    itts.wav_to_mono_mp3(wav_bytes, out, bitrate=opts["bitrate"])
    return item_id, "ok"


def _render_edge(item_id: int, story: str, out: Path, voice: str, opts: dict) -> tuple[int, str]:
    """Render via edge-tts (Azure neural). Network call with retries.

    The neural voice handles Icelandic numbers/dates itself, so the text is
    sent raw. The service returns 48 kbps mono MP3; we re-encode through ffmpeg
    to the requested (smaller) mono bitrate so every output is small + mono."""
    import asyncio
    import edge_tts

    # Icelandic gets the full abbreviation/unit/date/year expansion; English
    # gets only neutral cleanup (the English neural voice reads the rest).
    if opts.get("lang") == "en":
        text = itts.normalize_text_en(story.strip())
    else:
        text = itts.normalize_text(story.strip())
    if not _has_speech(text):  # nothing but punctuation/digits -> skip, don't error
        return item_id, "empty"

    async def _collect() -> bytes:
        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return bytes(buf)

    last_err = None
    for attempt in range(opts["retries"]):
        try:
            data = asyncio.run(_collect())
            if data:
                # ffmpeg decodes the edge MP3 and re-encodes to mono @ bitrate.
                itts.wav_to_mono_mp3(data, out, bitrate=opts["bitrate"])
                if out.exists() and out.stat().st_size > 0:
                    return item_id, "ok"
            last_err = "empty output"
        except Exception as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))  # back off before retrying
    out.unlink(missing_ok=True)  # don't leave a partial file (keeps resume sane)
    return item_id, f"error: {last_err}"


def _render_one(engine: str, item_id: int, story: str, out: Path, voice: str, opts: dict) -> tuple[int, str]:
    """Synthesize one item to MP3. Returns (id, status). Never raises."""
    try:
        if engine == "edge":
            return _render_edge(item_id, story, out, voice, opts)
        return _render_piper(item_id, story, out, opts)
    except Exception as e:  # keep the batch going; report the failure
        return item_id, f"error: {e}"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to kringum.db (default: %(default)s).")
    p.add_argument("--out", type=Path, default=None,
                   help="Output directory (default: tts/audio for --lang is, tts/audio_en for --lang en).")
    p.add_argument("--lang", choices=["is", "en"], default="is",
                   help="Language: 'is' reads story (default), 'en' reads story_eng. 'en' requires --engine edge.")
    p.add_argument("--engine", choices=["piper", "edge"], default="piper",
                   help="TTS engine (default: %(default)s). 'edge' = Azure neural voices.")
    p.add_argument("-v", "--voice", default=None,
                   help="Voice. piper: %s. edge: %s. Defaults to Salka (piper) / Guðrún (edge)."
                        % (", ".join(itts.TALROMUR_VOICES), ", ".join(EDGE_VOICES)))
    p.add_argument("--ids", help="Comma-separated item ids to render (default: all with a story).")
    p.add_argument("--visible-only", action="store_true", help="Only items with visibility=1.")
    p.add_argument("--exclude-tag", default=",".join(DEFAULT_EXCLUDE_TAGS),
                   help="Comma-separated tags to skip (substring match). Default: %(default)s. "
                        "Pass '' to disable.")
    p.add_argument("--limit", type=int, help="Render at most N items (after filtering).")
    p.add_argument("--jobs", type=int, default=4, help="Worker processes (default: %(default)s).")
    p.add_argument("--overwrite", action="store_true", help="Re-render items whose MP3 already exists.")
    p.add_argument("-b", "--bitrate", default="64k", help="MP3 bitrate (piper only; edge uses its own).")
    p.add_argument("--length-scale", type=float, default=1.0)
    p.add_argument("--noise-scale", type=float, default=0.667)
    p.add_argument("--noise-w-scale", type=float, default=0.8)
    p.add_argument("--paragraph-silence", type=float, default=0.0,
                   help="Seconds of extra silence at paragraph breaks (piper only).")
    p.add_argument("--retries", type=int, default=4, help="Retries per item for the edge engine (default: %(default)s).")
    p.add_argument("--alternate", action="store_true",
                   help="edge: alternate voices by item id — odd ids -> male, even ids -> female "
                        "(is: Gunnar/Guðrún, en: Andrew/Sonia).")
    p.add_argument("--name-with-voice", action="store_true",
                   help="Append the voice name to filenames (e.g. 9-gudrun.mp3) for comparison.")
    return p.parse_args()


def voice_for_item(item_id: int, args: argparse.Namespace) -> str:
    """The voice to use for one item (handles --alternate, per language)."""
    if args.alternate:  # odd -> male, even -> female
        male, female = LANGS[args.lang]["alternate"]
        return male if item_id % 2 else female
    return args.voice


def main() -> int:
    args = parse_args()
    lang = LANGS[args.lang]

    if args.lang == "en" and args.engine != "edge":
        sys.exit("--lang en requires --engine edge (Piper voices are Icelandic only).")
    if args.alternate and args.engine != "edge":
        sys.exit("--alternate only applies to --engine edge.")

    # Default output dir depends on language (keeps is/en MP3s in separate folders).
    if args.out is None:
        args.out = Path(__file__).resolve().parent / lang["out_subdir"]
    args.out.mkdir(parents=True, exist_ok=True)

    # Resolve / validate the voice for the chosen engine + language.
    if args.engine == "piper":
        valid = itts.TALROMUR_VOICES
        if args.voice is None:
            args.voice = itts.DEFAULT_VOICE
    else:  # edge
        valid = lang["voices"]
        if args.voice is None:
            args.voice = lang["default_voice"]
    if args.voice not in valid:
        sys.exit(f"Voice '{args.voice}' is not valid for {args.engine}/{args.lang}. "
                 f"Choose one of: {', '.join(valid)}")

    opts = {
        "lang": args.lang,
        "voice": args.voice, "bitrate": args.bitrate,
        "length_scale": args.length_scale, "noise_scale": args.noise_scale,
        "noise_w_scale": args.noise_w_scale, "paragraph_silence": args.paragraph_silence,
        "retries": args.retries,
    }

    exclude_tags = [t.strip() for t in args.exclude_tag.split(",") if t.strip()]
    ids = [int(x) for x in args.ids.split(",")] if args.ids else None
    items = fetch_items(args.db, field=lang["field"], ids=ids, visible_only=args.visible_only,
                        limit=args.limit, exclude_tags=exclude_tags)
    if exclude_tags:
        print(f"Excluding tags: {', '.join(exclude_tags)}", file=sys.stderr)

    # Per-item voice (for --alternate) and output path. With --name-with-voice
    # the tag follows the per-item voice; otherwise each id maps to one voice,
    # so a plain <id>.mp3 stays resume-safe.
    def item_out(r) -> Path:
        tag = voice_tag_of(voice_for_item(r["id"], args)) if args.name_with_voice else None
        return out_path_for(r["id"], args.out, tag)

    if not args.overwrite:
        items = [r for r in items if not item_out(r).exists()]

    total = len(items)
    if total == 0:
        print("Nothing to render (all done or no matching items).", file=sys.stderr)
        return 0
    if args.alternate:
        male, female = lang["alternate"]
        label = f"{args.engine}/{args.lang}:alternate(odd→{voice_tag_of(male)}/even→{voice_tag_of(female)})"
    else:
        label = f"{args.engine}/{args.lang}:{args.voice}"
    print(f"Rendering {total} item(s) -> {args.out}  "
          f"[{label}, {args.jobs} workers, mono {args.bitrate}]", file=sys.stderr)

    done = ok = 0
    failures: list[tuple[int, str]] = []
    with ProcessPoolExecutor(
        max_workers=args.jobs, initializer=_init_worker, initargs=(args.engine, args.voice)
    ) as ex:
        futs = [
            ex.submit(
                _render_one, args.engine, r["id"], r["story"],
                item_out(r), voice_for_item(r["id"], args), opts,
            )
            for r in items
        ]
        for fut in as_completed(futs):
            item_id, status = fut.result()
            done += 1
            if status == "ok":
                ok += 1
            else:
                failures.append((item_id, status))
            if done % 25 == 0 or done == total:
                print(f"  {done}/{total} done ({ok} ok, {len(failures)} failed)", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} failure(s):", file=sys.stderr)
        for item_id, status in failures[:20]:
            print(f"  item {item_id}: {status}", file=sys.stderr)
    print(f"Finished: {ok}/{total} MP3s written to {args.out}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
