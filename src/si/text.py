"""Text preparation: make text speakable (numbers.py spells out the
numbers, in the language lang.py detects) and split it into chunks.

Pure Python (no model imports), so it can be tested without loading VoxCPM2.
"""

import re

from si.lang import language
from si.numbers import numbers

# The audio is streamed within a chunk, so a chunk's length doesn't delay
# the start; but each new chunk costs ~0.5 s of synthesis before its first
# audio, which a short chunk before it may not cover. So: few chunks.
MIN = 60     # shorter sentences are joined to the next (the last one: to
             # the one before)
MAX = 200    # longer sentences are cut at , ; : (else at a space)

# Abbreviations whose period doesn't end a sentence (lowercase, without the
# last period). A lowercase next word never starts a sentence, so this only
# matters before a capital or a digit; words that mostly end sentences
# ("osv.", "etc.") are left out.
ABBREV = {
    "f.eks", "bl.a", "dvs", "nr", "ca", "evt", "ev", "inkl", "ekskl", "kl",
    "tlf", "jf", "pga", "ift", "mht", "hhv", "ref", "pr", "vedr", "iht", "st",
    "e.g", "i.e", "dr", "mr", "mrs", "ms", "prof", "vs", "approx", "dept",
    "fig", "jr", "sr",
}

URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"'()\[\]]+", re.I)
BARE = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})/[^\s<>\"'()\[\]]*", re.I)


def host(url):
    """The speakable part of a URL: its host, without www."""
    h = re.sub(r"^[a-z]+://", "", url, flags=re.I)
    h = re.split(r"[/?#]", h, maxsplit=1)[0].split("@")[-1].split(":")[0]
    return re.sub(r"^www\.", "", h, flags=re.I).rstrip(".,;:!?")


def clean(text):
    """Make text speakable: a URL becomes its host (github.com/foo/bar ->
    github.com), markdown markup goes, and a heading or list item becomes
    a sentence of its own."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [text](url)
    text = re.sub(r"<((?:https?://|mailto:)[^>]+)>", r"\1", text)
    text = re.sub(r"\bmailto:", "", text)
    text = URL.sub(lambda m: host(m.group()) + m.group()[
        len(m.group().rstrip(".,;:!?")):], text)  # keep a sentence's period
    text = BARE.sub(r"\1", text)
    text = re.sub(r"^\s*(```|~~~).*$", "", text, flags=re.M)  # code fences
    text = re.sub(r"`+([^`]*)`+", r"\1", text)
    text = re.sub(r"(\*\*|__|~~)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])[*_](?=\S)([^*_\n]+?)(?<=\S)[*_](?![\w*])",
                  r"\1", text)
    text = re.sub(r"^\s*([-*_=])\1{2,}\s*$", "", text, flags=re.M)  # rules
    lines = []
    for line in text.splitlines():
        line, n = re.subn(r"^\s*(?:#{1,6}|>+|[-*+•·▪])\s+", "", line)
        line = line.strip()
        if (n or re.match(r"\d+[.)]\s", line)) and line \
                and not re.search(r"[.!?:;,]$", line):
            line += "."
        lines.append(line)
    return "\n".join(lines)


def sentences(text):
    """Split text into sentences; a blank line also ends one (with a
    period if it has none)."""
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        start = 0
        for m in re.finditer(r"[.!?…]+[\"')\]»”]*\s+(?=\S)", para):
            word = para[start:m.start()].rsplit(" ", 1)[-1].lstrip("(\"'«")
            if para[m.start()] == "." and (
                    para[m.end()].islower() or word.lower() in ABBREV
                    or (len(word) == 1 and word.isalpha())):  # an initial
                continue
            out.append(para[start:m.end()].strip())
            start = m.end()
        if tail := para[start:].strip():  # end it, so the voice ends too
            out.append(tail if re.search(r"[.!?…:;,]\W*$", tail)
                       else tail + ".")
    return out


def cut(s, pat, lo, hi, target):
    """The place nearest target to cut s at pat, within lo..hi (not in a
    quote or before a number)."""
    cuts = [m.end() for m in re.finditer(pat, s)
            if max(lo, MIN) <= m.end() <= hi and len(s) - m.end() >= MIN // 2
            and s.count('"', 0, m.end()) % 2 == 0 and not s[m.end()].isdigit()]
    return min(cuts, key=lambda c: abs(c - target)) if cuts else None


def split_long(s):
    """s in pieces of at most MAX chars, as even as can be, cut at , ; : if
    possible (else at a space)."""
    if len(s) <= MAX:
        return [s]
    target = len(s) / -(-len(s) // MAX)
    at = cut(s, r"[,;:–—]\s", target / 2, MAX, target) \
        or cut(s, r"\s", 0, MAX, target)
    if at is None:
        return [s]
    return [s[:at].strip()] + split_long(s[at:].strip())


def whole(text):
    """The text, made speakable, as one piece (for a designed voice, which
    differs on every generate())."""
    return numbers(" ".join(clean(text).split()), language(text))


def chunks(text):
    """The text, made speakable, as chunks to synthesize one at a time:
    sentences, short ones joined to the next and long ones split. Numbers
    are spelled out."""
    out, lang = [], language(text)
    for s in sentences(clean(text)):
        s = numbers(s, lang)
        if out and len(out[-1]) < MIN \
                and len(out[-1]) + len(s) < MAX:
            out[-1] += " " + s
        else:
            out.append(s)
    if len(out) > 1 and len(out[-1]) < MIN \
            and len(out[-2]) + len(out[-1]) < MAX:  # a short last sentence
        last = out.pop()
        out[-1] += " " + last
    return [p for c in out for p in split_long(c)]
