#!/usr/bin/env python3
"""Read an Icelandic paragraph aloud and save it as a small mono MP3.

Uses Piper (https://github.com/OHF-Voice/piper1-gpl) with the Talrómur
Icelandic voices, which were trained on the Talrómur speech corpus produced
by Reykjavik University's Language and Voice Lab.

The Piper voice model is downloaded automatically on first run and cached in
./voices, so subsequent runs are offline and fast.

Usage:
    python icelandic_tts.py                       # default voice + sample text
    python icelandic_tts.py -v is_IS-steinn-medium
    python icelandic_tts.py -t "Halló, heimur." -o halló.mp3
    echo "Texti úr stdin." | python icelandic_tts.py -t -
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig
from piper.download_voices import download_voice

# Talrómur voices available in the Piper voice repository. All are 22.05 kHz
# mono. "medium" is the quality tier (good balance of quality and size).
TALROMUR_VOICES = {
    "is_IS-bui-medium": "Búi — male",
    "is_IS-salka-medium": "Salka — female",
    "is_IS-steinn-medium": "Steinn — male",
    "is_IS-ugla-medium": "Ugla — female",
}
DEFAULT_VOICE = "is_IS-salka-medium"

# A short, natural Icelandic paragraph to read by default.
SAMPLE_PARAGRAPH = (
    "Herðubreið er 1682 metra hátt móbergsfjall í Ódauðahrauni norðan við "
    "Vatnajökul. Hún er stundum nefnd drottning íslenskra fjalla og í árið 2002 "
    "var hún kosin þjóðarfjall Íslendinga.\n\n"
    "Árið 1908 gengu Sigurður Sumarliðason og Hans Reck á topp Herðubreiðar, "
    "fyrstir manna svo vitað sé. Áður hafði slíkt verið talið ógjörningur.\n\n"
    "Sumir álíta að fjallið sé ein af 7 orkustöðvum Íslands."
)

VOICES_DIR = Path(__file__).resolve().parent / "voices"


# --- Icelandic number normalization -----------------------------------------
# Piper's espeak-ng Icelandic phonemizer mishandles bare digits (especially
# years), so we spell numbers out as words before synthesis. Neuter forms are
# used throughout — the citation form Icelandic uses for counting and years.

_ONES = [
    "núll", "eitt", "tvö", "þrjú", "fjögur", "fimm", "sex", "sjö", "átta", "níu",
    "tíu", "ellefu", "tólf", "þrettán", "fjórtán", "fimmtán", "sextán",
    "sautján", "átján", "nítján",
]
_TENS = [
    "", "", "tuttugu", "þrjátíu", "fjörutíu", "fimmtíu", "sextíu", "sjötíu",
    "áttatíu", "níutíu",
]

# Numerals 1–4 inflect for the gender AND case of the noun they count. Default
# is nominative neuter (the citation form used for years and abstract counting).
# In the genitive plural, 2–4 are gender-invariant (tveggja/þriggja/fjögurra).
_ONES_FORMS = {
    ("nom", "m"): {1: "einn", 2: "tveir", 3: "þrír", 4: "fjórir"},
    ("nom", "f"): {1: "ein", 2: "tvær", 3: "þrjár", 4: "fjórar"},
    ("nom", "n"): {1: "eitt", 2: "tvö", 3: "þrjú", 4: "fjögur"},
    ("gen", "m"): {1: "eins", 2: "tveggja", 3: "þriggja", 4: "fjögurra"},
    ("gen", "f"): {1: "einnar", 2: "tveggja", 3: "þriggja", 4: "fjögurra"},
    ("gen", "n"): {1: "eins", 2: "tveggja", 3: "þriggja", 4: "fjögurra"},
}


def _one(u: int, gender: str, case: str) -> str:
    return _ONES_FORMS[(case, gender)][u] if 1 <= u <= 4 else _ONES[u]


def _under_100(n: int, gender: str = "n", case: str = "nom") -> str:
    if n < 20:
        return _one(n, gender, case)
    t, u = divmod(n, 10)
    return _TENS[t] if u == 0 else f"{_TENS[t]} og {_one(u, gender, case)}"


def _join_og(parts: list[str]) -> str:
    """Join number components, placing the conjunction 'og' before the last
    component (unless it already contains one, e.g. 'áttatíu og tvö')."""
    if len(parts) > 1 and "og" not in parts[-1].split():
        parts = parts[:-1] + ["og " + parts[-1]]
    return " ".join(parts)


def read_cardinal(n: int, gender: str = "n", case: str = "nom") -> str:
    """Spell out a non-negative integer as an Icelandic cardinal.

    Only the trailing units (1–4) inflect for `gender`/`case`; the þúsund/hundrað
    multipliers are themselves neuter, so 'eitt þúsund'/'... hundruð' are fixed.
    """
    if n == 0:
        return "núll"
    parts: list[str] = []
    th, rem = divmod(n, 1000)
    if th:
        parts.append("eitt þúsund" if th == 1 else f"{read_cardinal(th)} þúsund")
    h, rem2 = divmod(rem, 100)
    if h:
        parts.append("hundrað" if h == 1 else f"{_ONES[h]} hundruð")
    if rem2:
        parts.append(_under_100(rem2, gender, case))
    return _join_og(parts)


def read_year(n: int) -> str:
    """Read a year the conventional Icelandic way: the 1100–1999 and 2100–2999
    ranges use the 'hundreds' idiom (1908 -> 'nítján hundruð og átta'), while
    2000–2099 reads as 'tvö þúsund ...' (2002 -> 'tvö þúsund og tvö')."""
    if 1100 <= n <= 1999 or 2100 <= n <= 2999:
        hh, rr = divmod(n, 100)
        parts = [f"{_under_100(hh)} hundruð"]
        if rr:
            parts.append(_under_100(rr))
        return _join_og(parts)
    if 2000 <= n <= 2099:
        parts = ["tvö þúsund"]
        if n - 2000:
            parts.append(_under_100(n - 2000))
        return _join_og(parts)
    return read_cardinal(n)


# Gender of common counted nouns, so the trailing numeral agrees. Keyed by the
# lowercased word as it appears after the number (various inflected forms).
# Extend this as you meet new units in the corpus; unknown nouns default neuter.
_UNIT_GENDER = {
    g: gender
    for words, gender in [
        # masculine
        ("metri metrar metra metrum metrunum", "m"),
        ("kílómetri kílómetrar kílómetra kílómetrum", "m"),
        ("sentimetri sentimetrar sentimetra", "m"),
        ("millimetri millimetrar millimetra", "m"),
        ("dagur dagar daga dögum", "m"),
        ("mánuður mánuðir mánuði mánuðum", "m"),
        ("klukkutími klukkutímar klukkutíma", "m"),
        # feminine
        ("króna krónur krónum króna", "f"),
        ("mínúta mínútur mínútum mínútna", "f"),
        ("sekúnda sekúndur sekúndum", "f"),
        ("klukkustund klukkustundir klukkustundum", "f"),
        ("vika vikur vikum vikna", "f"),
        ("milljón milljónir milljóna milljónum", "f"),
        # neuter (explicit, though neuter is also the default)
        ("ár árið árum ára", "n"),
        ("prósent prósentum", "n"),
        ("stig stigum stiga", "n"),
        ("kíló kílóum", "n"),
        ("tonn tonnum tonna", "n"),
    ]
    for g in words.split()
}

# Dimension adjectives: in "<number> <unit> <adj>" (e.g. "1682 metra hátt") the
# numeral takes the genitive. Inflected forms of hár/langur/breiður/djúpur/þykkur.
_DIM_ADJ = set(
    "hár há hátt háir háar háu háan "
    "langur löng langt langir langar löngu langan "
    "breiður breið breitt breiðir breiðar breiðu breiðan "
    "djúpur djúp djúpt djúpir djúpar djúpu djúpan "
    "þykkur þykk þykkt þykkir þykkar þykku þykkan".split()
)

# A 3–4 digit number right after a form of "ár" (árið/árin/ári/árs) is a year.
_YEAR_RE = re.compile(r"\b(ár(?:ið|in|i|s|sins)?)\s+(\d{3,4})\b", re.IGNORECASE)
# A number plus up to two following words (its counted noun and a possible
# dimension adjective), used to pick gender and case.
_NUM_RE = re.compile(r"(\d+)((?:\s+[^\W\d_]+){0,2})", re.UNICODE)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _cardinal_sub(m: "re.Match[str]") -> str:
    num = int(m.group(1))
    tail = m.group(2) or ""
    after = [w.lower() for w in _WORD_RE.findall(tail)]
    noun = after[0] if after else None
    adj = after[1] if len(after) > 1 else None
    gender = _UNIT_GENDER.get(noun, "n") if noun else "n"
    # Attributive measure phrase "<num> <unit> <dim-adj>" -> genitive numeral.
    case = "gen" if (noun in _UNIT_GENDER and adj in _DIM_ADJ) else "nom"
    return read_cardinal(num, gender, case) + tail


def normalize_icelandic_numbers(text: str) -> str:
    """Replace digit sequences with Icelandic words.

    Years (numbers after a form of 'ár') read year-style; every other number
    reads as a cardinal whose trailing 1–4 agrees with the gender of the noun
    that follows it, when that noun is known.
    """
    text = _YEAR_RE.sub(lambda m: f"{m.group(1)} {read_year(int(m.group(2)))}", text)
    text = _NUM_RE.sub(_cardinal_sub, text)
    return text


# --- Dates ------------------------------------------------------------------
# Day-of-month is read as an ordinal in the fixed date form ("8. júní" ->
# "áttunda júní"); neither engine does this from "8." on its own.
_MONTHS = [
    "", "janúar", "febrúar", "mars", "apríl", "maí", "júní",
    "júlí", "ágúst", "september", "október", "nóvember", "desember",
]
_DAY_ORDINAL = {
    1: "fyrsta", 2: "annan", 3: "þriðja", 4: "fjórða", 5: "fimmta",
    6: "sjötta", 7: "sjöunda", 8: "áttunda", 9: "níunda", 10: "tíunda",
    11: "ellefta", 12: "tólfta", 13: "þrettánda", 14: "fjórtánda",
    15: "fimmtánda", 16: "sextánda", 17: "sautjánda", 18: "átjánda",
    19: "nítjánda", 20: "tuttugasta", 30: "þrítugasta",
}


def day_ordinal(d: int) -> str | None:
    """Ordinal day-of-month word (1–31) used in spoken dates, else None."""
    if d in _DAY_ORDINAL:
        return _DAY_ORDINAL[d]
    if 21 <= d <= 29:
        return "tuttugasta og " + _DAY_ORDINAL[d - 20]
    if d == 31:
        return "þrítugasta og fyrsta"
    return None


_MONTH_ALT = "|".join(_MONTHS[1:])
# "8. júní" / "8.júní"  (day. monthname)
_DAYMONTH_RE = re.compile(r"\b(\d{1,2})\.\s*(%s)" % _MONTH_ALT, re.IGNORECASE)
# "10.06.1941" (numeric dd.mm.yyyy)
_NUMDATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")
# A 3–4 digit number is read as a YEAR when it follows a form of "ár" or a
# month name. Other 4-digit numbers (heights, populations, prices) stay as
# digits so they read as cardinals / are handled per-engine.
_YEAR_CTX_RE = re.compile(
    r"\b(ár(?:ið|in|i|s|inu|sins)?|%s)\s+(\d{3,4})\b" % _MONTH_ALT, re.IGNORECASE)
# Year ranges: "1908-1912" -> both read as years (run before the generic range).
_YEAR_RANGE_RE = re.compile(r"\b(\d{4})\s*[–-]\s*(\d{4})\b")


def _year_word(year: str) -> str:
    n = int(year)
    return read_year(n) if 1000 <= n <= 2099 else year


def _daymonth_sub(m: "re.Match[str]") -> str:
    ordn = day_ordinal(int(m.group(1)))
    return f"{ordn} {m.group(2)}" if ordn else m.group(0)


def _numdate_sub(m: "re.Match[str]") -> str:
    d, mo, year = int(m.group(1)), int(m.group(2)), m.group(3)
    ordn = day_ordinal(d)
    if ordn and 1 <= mo <= 12:
        return f"{ordn} {_MONTHS[mo]} {_year_word(year)}"
    return m.group(0)


def _yearctx_sub(m: "re.Match[str]") -> str:
    return f"{m.group(1)} {_year_word(m.group(2))}"


def _yearrange_sub(m: "re.Match[str]") -> str:
    a, b = int(m.group(1)), int(m.group(2))
    if 1000 <= a <= 2099 and 1000 <= b <= 2099:
        return f"{read_year(a)} til {read_year(b)}"
    return m.group(0)


# --- General Icelandic text normalization -----------------------------------
# Ported from the original C# pre-processor: expand abbreviations, units,
# compass directions, number ranges, and HTML breaks that the TTS engines
# (Piper and Azure/edge neural) would otherwise mispronounce. Engine-agnostic;
# run this BEFORE normalize_icelandic_numbers for Piper, and on its own for edge
# (where the neural voice reads bare numbers itself).
#
# Ordered list — earlier rules win, so longer/more specific tokens come first
# (e.g. km² before m², NNA before NA). Each entry is (compiled regex, repl).
_TEXT_RULES = [
    (re.compile(p), r) for p, r in [
        # HTML breaks -> paragraph break (Piper turns blank lines into a pause;
        # edge gets a sentence break). The original used SSML <break>, which
        # neither engine accepts as plain text.
        (r"<\s*br\s*/?>", "\n\n"),
        (r"</?\s*p\s*>", "\n\n"),
        # Footnote markers like (1,2,3) / (1,2,3,4) -> removed
        (r"\(\s*\d+(?:\s*,\s*\d+)+\s*\)", ""),
        # Number / year ranges:  5-7 -> "5 til 7",  1908-1912 -> "1908 til 1912"
        (r"(\d)\s*-\s*(\d)", r"\1 til \2"),
        # Area / volume units (both digit and Unicode-superscript forms);
        # km² must precede m² so it isn't partly matched.
        (r"\bkm[³3]", " rúmkílómetrar"),
        (r"\bkm[²2]", " ferkílómetrar"),
        (r"\bm[²2]", " fermetrar"),
        (r"\bm[³3]", " rúmmetrar"),
        (r"\bfm\b", " fermetrar"),
        (r"\bha\b", " hektarar"),
        (r"\bklst\b\.?", " klukkustundir"),
        (r"\bMW\b", " megavött"),
        (r"\bm\.?\s*y\.?\s*s\b\.?", " metra yfir sjávarmáli"),
        # Percent:  25% -> "25 prósent"
        (r"\s*%", " prósent"),
        # Compass directions (standalone, case-sensitive). Longest first.
        (r"\bNNA\b", "norð norðaustur"),
        (r"\bNNV\b", "norð norðvestur"),
        (r"\bSSA\b", "suð suð austur"),
        (r"\bSSV\b", "suð suð vestur"),
        (r"\bNA\b", "norðaustur"),
        (r"\bNV\b", "norðvestur"),
        (r"\bSA\b", "suðaustur"),
        (r"\bSV\b", "suðvestur"),
        # Misc abbreviations
        (r"\bk\.h\.", "konu hans"),
        (r"\bkh\b", "kona hans"),
        (r"[Uu]\.þ\.b\.", "um það bil"),
        (r"\bca\.", "sirka"),
        (r"\bþ\.(?=\s)", "þann"),
        (r"\s&\s", " og "),
        # Common Icelandic abbreviations (added — not in the original list;
        # remove any you don't want spoken out in full).
        (r"\bt\.d\.", "til dæmis"),
        (r"\bþ\.e\.a\.s\.", "það er að segja"),
        (r"\bþ\.e\.", "það er"),
        (r"\bm\.a\.", "meðal annars"),
        (r"\bo\.s\.frv\.", "og svo framvegis"),
        (r"\bo\.fl\.", "og fleira"),
    ]
]


def normalize_text(text: str) -> str:
    """Expand dates, years, abbreviations, units, directions, ranges, HTML breaks."""
    text = _NUMDATE_RE.sub(_numdate_sub, text)        # dd.mm.yyyy first
    text = _DAYMONTH_RE.sub(_daymonth_sub, text)      # then "8. júní"
    text = _YEAR_RANGE_RE.sub(_yearrange_sub, text)   # "1908-1912" (before generic range)
    text = _YEAR_CTX_RE.sub(_yearctx_sub, text)       # "árið 1783" / "febrúar 1784"
    for rx, repl in _TEXT_RULES:
        text = rx.sub(repl, text)
    # Collapse the runs of spaces left by substitutions, but keep newlines
    # (paragraph breaks) intact.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)  # no space before punctuation
    return text


# English text needs only language-neutral cleanup — the English neural voices
# read numbers, dates, units, and ranges correctly on their own. Crucially we do
# NOT apply the Icelandic rules (which would turn "&" into "og", etc.).
_EN_RULES = [
    (re.compile(p), r) for p, r in [
        (r"<\s*br\s*/?>", "\n\n"),
        (r"</?\s*p\s*>", "\n\n"),
        (r"\(\s*\d+(?:\s*,\s*\d+)+\s*\)", ""),  # footnote markers (1,2,3)
        (r"\s&\s", " and "),
    ]
]


def normalize_text_en(text: str) -> str:
    """Minimal, language-neutral cleanup for English text before synthesis."""
    for rx, repl in _EN_RULES:
        text = rx.sub(repl, text)
    return re.sub(r"[ \t]{2,}", " ", text)


def ensure_voice(voice: str, voices_dir: Path) -> Path:
    """Download the Piper voice if needed; return the path to the .onnx model."""
    voices_dir.mkdir(parents=True, exist_ok=True)
    model_path = voices_dir / f"{voice}.onnx"
    if not (model_path.exists() and (voices_dir / f"{voice}.onnx.json").exists()):
        print(f"Downloading voice {voice} ...", file=sys.stderr)
        download_voice(voice, voices_dir)
    return model_path


# Blank line(s) separate paragraphs.
_PARAGRAPH_RE = re.compile(r"\n\s*\n+")


def _synth_one_wav(voice: PiperVoice, text: str, cfg: SynthesisConfig) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file, syn_config=cfg)
    return buf.getvalue()


def synthesize_wav_bytes(
    voice: PiperVoice,
    text: str,
    length_scale: float = 1.0,
    noise_scale: float = 0.667,
    noise_w_scale: float = 0.8,
    paragraph_silence: float = 0.0,
) -> bytes:
    """Synthesize text to in-memory WAV bytes (no temp file needed).

    length_scale       > 1.0 slows speech (often clearer/calmer prosody).
    noise_scale        controls variability in the generated audio.
    noise_w_scale      controls variability in phoneme durations (cadence).
    paragraph_silence  seconds of extra silence inserted at blank-line
                       paragraph breaks (each paragraph is synthesized
                       separately and the clips are joined with a gap).
    """
    cfg = SynthesisConfig(
        length_scale=length_scale,
        noise_scale=noise_scale,
        noise_w_scale=noise_w_scale,
        normalize_audio=True,
    )

    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(text) if p.strip()]
    if paragraph_silence <= 0 or len(paragraphs) <= 1:
        return _synth_one_wav(voice, text, cfg)

    # Synthesize each paragraph, then concatenate the PCM frames with a gap.
    clips = [_synth_one_wav(voice, p, cfg) for p in paragraphs]
    out = io.BytesIO()
    writer: wave.Wave_write | None = None
    gap = b""
    for clip in clips:
        with wave.open(io.BytesIO(clip), "rb") as r:
            if writer is None:
                writer = wave.open(out, "wb")
                writer.setnchannels(r.getnchannels())
                writer.setsampwidth(r.getsampwidth())
                writer.setframerate(r.getframerate())
                n_silence = int(r.getframerate() * paragraph_silence)
                gap = b"\x00" * (n_silence * r.getsampwidth() * r.getnchannels())
            else:
                writer.writeframes(gap)
            writer.writeframes(r.readframes(r.getnframes()))
    assert writer is not None
    writer.close()
    return out.getvalue()


def wav_to_mono_mp3(wav_bytes: bytes, out_path: Path, bitrate: str = "64k") -> None:
    """Encode WAV bytes to a small mono MP3 using ffmpeg."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", "pipe:0",   # read WAV from stdin
        "-ac", "1",        # force mono
        "-b:a", bitrate,   # low bitrate keeps the file small; fine for speech
        str(out_path),
    ]
    proc = subprocess.run(cmd, input=wav_bytes, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed:\n" + proc.stderr.decode("utf-8", "replace")
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read an Icelandic paragraph to a mono MP3 using Piper Talrómur voices.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "-v", "--voice", default=DEFAULT_VOICE, choices=list(TALROMUR_VOICES),
        help="Talrómur voice to use (default: %(default)s).",
    )
    p.add_argument(
        "-t", "--text", default=SAMPLE_PARAGRAPH,
        help="Text to read. Use '-' to read from stdin. Defaults to a sample paragraph.",
    )
    p.add_argument(
        "-o", "--output", type=Path, default=Path("icelandic.mp3"),
        help="Output MP3 path (default: %(default)s).",
    )
    p.add_argument(
        "-b", "--bitrate", default="64k",
        help="MP3 audio bitrate (default: %(default)s; lower = smaller file).",
    )
    p.add_argument(
        "--length-scale", type=float, default=1.0,
        help="Speech pace; >1.0 is slower/clearer (default: %(default)s).",
    )
    p.add_argument(
        "--noise-scale", type=float, default=0.667,
        help="Audio variability (default: %(default)s).",
    )
    p.add_argument(
        "--noise-w-scale", type=float, default=0.8,
        help="Cadence/duration variability (default: %(default)s).",
    )
    p.add_argument(
        "--paragraph-silence", type=float, default=0.0,
        help="Seconds of extra silence at paragraph (blank-line) breaks (default: %(default)s).",
    )
    p.add_argument(
        "--raw-numbers", action="store_true",
        help="Disable Icelandic number/year normalization (send digits as-is).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    text = sys.stdin.read() if args.text == "-" else args.text
    text = text.strip()
    if not text:
        print("No text to synthesize.", file=sys.stderr)
        return 1

    text = normalize_text(text)
    if not args.raw_numbers:
        text = normalize_icelandic_numbers(text)
    print(f"Normalized text:\n{text}\n", file=sys.stderr)

    model_path = ensure_voice(args.voice, VOICES_DIR)

    print(f"Loading voice {args.voice} ({TALROMUR_VOICES[args.voice]}) ...", file=sys.stderr)
    voice = PiperVoice.load(model_path)

    print("Synthesizing speech ...", file=sys.stderr)
    wav_bytes = synthesize_wav_bytes(
        voice, text,
        length_scale=args.length_scale,
        noise_scale=args.noise_scale,
        noise_w_scale=args.noise_w_scale,
        paragraph_silence=args.paragraph_silence,
    )

    print(f"Encoding mono MP3 -> {args.output} ...", file=sys.stderr)
    wav_to_mono_mp3(wav_bytes, args.output, bitrate=args.bitrate)

    size_kb = args.output.stat().st_size / 1024
    print(f"Done: {args.output} ({size_kb:.1f} KB, mono)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
