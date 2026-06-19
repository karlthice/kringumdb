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
        # population / head-counts — keeps a 4-digit count (e.g. "1850 íbúar")
        # from being mistaken for a year by the year heuristic below.
        ("íbúi íbúar íbúa íbúum", "m"),
        ("manns", "m"),
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
    # A bare 4-digit number in the plausible year range, not counting a known
    # unit, is almost always a year in this corpus (settlement era onward), so
    # read it year-style ("1907" -> "nítján hundruð og sjö") rather than as a
    # huge cardinal. Heights/areas/prices/populations are followed by a unit or
    # count noun (metra, króna, íbúar, ...) and fall through to the cardinal
    # reading below. Years in an explicit "ár…"/month context are already
    # converted in normalize_text before this runs.
    if 1000 <= num <= 2099 and noun not in _UNIT_GENDER:
        return read_year(num) + tail
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


# --- Centuries --------------------------------------------------------------
# "18. öld" -> "átjánda öld"; neither engine reads the bare "18." as an ordinal.
# Century ordinals are weak feminine adjectives: the nominative singular ends in
# -a, and every other form (acc/dat/gen singular and the whole plural) ends in
# -u. The case is driven first by the inflected form of "öld" itself: the
# genitive "aldar"/"aldarinnar", the definite acc/dat "öldina"/"öldinni" and the
# plural forms are oblique in every context, so they always take the -u form
# ("í lok 18. aldar" -> "í lok átjándu aldar"). Only the bare "öld" (nom/acc/dat
# sg) and the definite nominative "öldin" can be nominative; for "öld" a
# governing preposition (á/í/um/frá/…) or a quantifier adjective (miðja/miðri/…)
# selects the -u form ("á 18. öld" -> "á átjándu öld", "um miðja 18. öld" -> "um
# miðja átjándu öld"), otherwise it stays nominative ("18. öld" -> "átjánda öld").
_CENTURY_ORDINAL = {
    #    nominative (-a)            oblique (-u)
    1:  ("fyrsta",                 "fyrstu"),
    2:  ("önnur",                  "annarri"),
    3:  ("þriðja",                 "þriðju"),
    4:  ("fjórða",                 "fjórðu"),
    5:  ("fimmta",                 "fimmtu"),
    6:  ("sjötta",                 "sjöttu"),
    7:  ("sjöunda",                "sjöundu"),
    8:  ("áttunda",                "áttundu"),
    9:  ("níunda",                 "níundu"),
    10: ("tíunda",                 "tíundu"),
    11: ("ellefta",                "elleftu"),
    12: ("tólfta",                 "tólftu"),
    13: ("þrettánda",              "þrettándu"),
    14: ("fjórtánda",              "fjórtándu"),
    15: ("fimmtánda",              "fimmtándu"),
    16: ("sextánda",               "sextándu"),
    17: ("sautjánda",              "sautjándu"),
    18: ("átjánda",                "átjándu"),
    19: ("nítjánda",               "nítjándu"),
    20: ("tuttugasta",             "tuttugustu"),
    21: ("tuttugasta og fyrsta",   "tuttugustu og fyrstu"),
}

# Prepositions that put a following bare "öld" in an oblique case and so select
# the -u ordinal form. A bare "öld" with no governing preposition (and no
# quantifier adjective, below) is read as nominative (-a).
_OBLIQUE_PREPS = (
    "á í um frá til eftir fyrir undir yfir gegnum kringum með að milli við úr"
).split()
_PREP_ALT = "|".join(_OBLIQUE_PREPS)

# Quantifier adjectives that sit between the preposition and the numeral
# ("um miðja 19. öld", "frá miðri 20. öld", "á öndverðri 18. öld"). They are
# themselves in an oblique (acc/dat) case agreeing with "öld", so their presence
# forces the -u form even when the governing preposition is not adjacent to the
# numeral. Listed as a closed set so the rule never swallows an arbitrary word.
_OBLIQUE_MODS = (
    "miðja miðri miðjan miðrar miðju síðari fyrri öndverðri öndverða "
    "ofanverðri ofanverða framanverðri endilanga alla allri hálfa hálfri"
).split()
_MOD_ALT = "|".join(_OBLIQUE_MODS)

# Inflected forms of "öld" (sg. + pl.), listed explicitly so the rule doesn't
# fire on unrelated words like "aldur" (age) or "öldungur" (elder).
_OLD_FORMS = (
    "öld öldin öldina öldinni aldar aldarinnar "
    "aldir aldirnar alda aldanna öldum öldunum"
).split()
# Only the bare "öld" (nom/acc/dat sg) and the definite nominative "öldin" can be
# nominative; every other form is oblique in all contexts. "öldin" is always
# nominative, so only "öld" still depends on a preposition/adjective trigger.
_OLD_NOMINATIVE_FORMS = {"öld", "öldin"}
# Optional governing preposition, optional quantifier adjective, a century
# number, an optional second number (range/coordination via –, -, "og", "til" or
# "eða"), then a form of "öld".
_CENTURY_RE = re.compile(
    r"\b((?:%s)\s+)?((?:%s)\s+)?(\d{1,2})\.\s*(?:([–-]|og|til|eða)\s*(\d{1,2})\.\s*)?(%s)\b"
    % (_PREP_ALT, _MOD_ALT, "|".join(_OLD_FORMS)),
    re.IGNORECASE,
)


def _century_word(n: int, oblique: bool) -> str | None:
    forms = _CENTURY_ORDINAL.get(n)
    return None if forms is None else forms[1 if oblique else 0]


def _century_sub(m: "re.Match[str]") -> str:
    prep, mod, n1, sep, n2, noun = m.groups()
    noun_l = noun.lower()
    if noun_l == "öldin":
        oblique = False                        # definite nominative singular -> -a
    elif noun_l not in _OLD_NOMINATIVE_FORMS:
        oblique = True                         # gen sg, definite acc/dat, all plurals -> -u
    else:                                      # bare "öld": nominative unless governed
        oblique = prep is not None or mod is not None
    w1 = _century_word(int(n1), oblique)
    if w1 is None:
        return m.group(0)
    if n2:
        w2 = _century_word(int(n2), oblique)
        if w2 is None:
            return m.group(0)
        conj = sep if sep in ("og", "eða") else "til"  # "17.–18." / "17. til 18." -> "til"
        mid = f"{w1} {conj} {w2}"
    else:
        mid = w1
    return f"{prep or ''}{mod or ''}{mid} {noun}"


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


# All-caps acronyms (MH, KR, ÍSÍ, KFUM …) are spelled out letter by letter using
# the Icelandic names of the letters, so the voice says "emm há" for "MH" instead
# of trying to pronounce it as a word. Only short runs (2–4 letters) are treated
# as acronyms; longer all-caps tokens are almost always ordinary words set in
# capitals (headings, emphasis) and are left for the voice to read normally.
_LETTER_NAMES = {
    "A": "a", "Á": "á", "B": "bé", "C": "sé", "D": "dé", "Ð": "eð",
    "E": "e", "É": "é", "F": "eff", "G": "ge", "H": "há", "I": "i",
    "Í": "í", "J": "joð", "K": "ká", "L": "ell", "M": "emm", "N": "enn",
    "O": "o", "Ó": "ó", "P": "pé", "Q": "kú", "R": "err", "S": "ess",
    "T": "té", "U": "u", "Ú": "ú", "V": "vaff", "W": "tvöfalt vaff",
    "X": "ex", "Y": "ufsilon", "Ý": "ufsilon ý", "Z": "seta",
    "Þ": "þorn", "Æ": "æ", "Ö": "ö",
}

# All-caps tokens that are pronounced as a word (acronym read as a word, proper
# name, or an ordinary word set in capitals) and so must NOT be spelled out.
# Only 2–4-letter tokens need listing here; anything longer is left alone by the
# length cap in _ACRONYM_RE. Extend as new cases turn up.
_SPELL_EXCEPTIONS = frozenset((
    # acronyms read as a single word
    "NATO NATÓ NASA RÚV SÍS KEA LAVA RAF SKY RES SUP RIB NUTS "
    # company / brand names
    "EFLA DISA BYKO SAAB ASK ÍSOR "
    # ordinary Icelandic words written in capitals
    "VOR LÍF BÆR GOTT SALT ROK SÝN SÚM BARA HIN HINS FRÁ SKAL GÓÐA EMIR KLÓ "
    # ordinary English words written in capitals
    "YES NOT FLY TOUR OVER WOW"
).split())

# A run of 2–4 uppercase Icelandic letters, bounded on both sides; longer runs
# fall through untouched. Runs through after _TEXT_RULES so units (MW) and
# compass directions (NA/NV/SSV) have already been expanded to words.
_ACRONYM_RE = re.compile(r"\b[A-ZÁÉÍÓÚÝÞÆÖÐ]{2,4}\b")
# Tokens that look like Roman numerals (II, III, IX, VIII …) are left as-is so we
# don't read "II" as the letters "i i".
_ROMAN_RE = re.compile(r"^[IVXLCDM]+$")


def _spell_acronym(m: "re.Match[str]") -> str:
    tok = m.group(0)
    if tok in _SPELL_EXCEPTIONS or _ROMAN_RE.match(tok):
        return tok
    return " ".join(_LETTER_NAMES.get(ch, ch) for ch in tok)


def normalize_text(text: str) -> str:
    """Expand dates, years, abbreviations, units, directions, ranges, HTML breaks."""
    text = _NUMDATE_RE.sub(_numdate_sub, text)        # dd.mm.yyyy first
    text = _DAYMONTH_RE.sub(_daymonth_sub, text)      # then "8. júní"
    text = _YEAR_RANGE_RE.sub(_yearrange_sub, text)   # "1908-1912" (before generic range)
    text = _YEAR_CTX_RE.sub(_yearctx_sub, text)       # "árið 1783" / "febrúar 1784"
    text = _CENTURY_RE.sub(_century_sub, text)        # "18. öld" -> "átjánda öld"
    for rx, repl in _TEXT_RULES:
        text = rx.sub(repl, text)
    text = _ACRONYM_RE.sub(_spell_acronym, text)      # "MH" -> "emm há"
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
