"""Numbers in words: VoxCPM2 misreads digits in Norwegian ("48213" ->
"4 2 10 13"), so numbers are spelled out in the text's language. Formats
not covered are left as they are.

A language is a Lang: its words and notation, its grammar where languages
differ (methods: Spanish overrides them), and its rules (shared rule
builders, in order)."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import cached_property

from si.lang import WORDS

CURRENCY = {"kr": "NOK", "kr.": "NOK", "nok": "NOK", "kroner": "NOK",
            "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD",
            "us$": "USD", "dólar": "USD", "dólares": "USD", "dolar": "USD",
            "dolares": "USD", "dll": "USD", "dlls": "USD",
            "mxn": "MXN", "mx$": "MXN", "peso": "MXN", "pesos": "MXN",
            "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR"}
# Numbers (3+ digits) after these are IDs, read digit by digit.
ID_WORDS = (r"(?:ordre|order|sak|case|ticket|faktura|invoice|kunde|customer"
            r"|referanse|reference|ref|id|pedido|orden|caso|folio|factura"
            r"|cliente|referencia|gu[ií]a)(?:nummer|nr\.?|number|no\.?)?"
            r"|nummer|number|n[uú]mero")
NUM = r"\d{1,3}(?:[ \xa0.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
LONE = r"(?<![^\W_])(?<![\d.,/]){}(?![^\W_]|[.,/]\d)"  # not in a word or 3/4
# Between the digits of an ID: with a pause the model reads them right far
# more often (whisper: 9/9 vs 3/9 with spaces). A fullwidth comma, which it
# pauses at like a comma, so chunks are never cut inside an ID.
PAUSE = "， "


# ------------------------------------------------------------- the words

def cardinal(n, L):
    """n (an int) in words."""
    if n < len(L.ones):
        return L.ones[n]
    if n < 100:
        return L.tens[n // 10] + (L.join + L.ones[n % 10] if n % 10 else "")
    if n >= 10**9:
        return digits(str(n), L)
    size = next(s for s in (10**6, 1000, 100) if n >= s)
    hi, lo = divmod(n, size)
    one, many = {100: L.hundred, 1000: L.thousand, 10**6: L.million}[size]
    head = L.hundreds[hi - 1] if size == 100 and L.hundreds and n > 100 \
        else one if hi == 1 else f"{L.un(cardinal(hi, L))} {many}"
    if not lo:
        return head
    return head + (f" {L.and_} " if lo < 100 and L.and_ else " ") \
        + cardinal(lo, L)


def ordinal(n, L):
    """1..99 as an ordinal (Spanish: 1..10)."""
    if n < 20:
        return L.ord[n - 1]
    t, o = divmod(n, 10)
    return L.tens[t] + L.join + L.ord[o - 1] if o else L.ordtens[t - 2]


def year(n, L):
    """1985 -> nitten åttifem, 2026 -> tjue tjueseks, 1905 -> nitten hundre
    og fem; 2000-2009 as a number, and every year in a language without
    year words (Spanish)."""
    hi, lo = divmod(n, 100)
    if not 11 <= hi <= 99 or 2000 <= n <= 2009 or not L.year_words:
        return cardinal(n, L)
    hundred, oh = L.year_words
    return f"{cardinal(hi, L)} " + (
        hundred if not lo else f"{oh} {cardinal(lo, L)}" if lo < 10
        else cardinal(lo, L))


def digits(s, L, sep=" "):
    """One digit at a time."""
    return sep.join(L.ones[int(c)] for c in s if c.isdigit())


def parse(s, L):
    """'1 250,50' -> (1250, '50'): the integer and its decimals (or None),
    in L's notation; None if s isn't a number there."""
    m = re.fullmatch(r"(\d{1,3}(?:([ \xa0.,])\d{3})(?:\2\d{3})*)"
                     r"(?:([.,])(\d+))?", s)
    if m and m[2] in L.group + " \xa0" and m[3] != m[2]:
        return int(re.sub(r"\D", "", m[1])), m[4]
    m = re.fullmatch(r"(\d+)(?:([.,])(\d+))?", s)
    if m and (not m[2] or m[2] == L.dec or len(m[3]) != 3):
        return int(m[1]), m[3]
    return None


def number(s, L, year_ok=True):
    """A number in words: a year, an ID (5+ digits but not 10000, or 3+
    with a leading 0: digit by digit), or an amount with its decimals."""
    if (p := parse(s, L)) is None:
        return s
    n, dec = p
    if s.isdigit():
        if (len(s) > 4 and not re.fullmatch(r"[1-9]\d{1,3}000", s)) \
                or (s[0] == "0" and len(s) > 2):
            return digits(s, L, PAUSE)
        if year_ok and len(s) == 4 and 1800 <= n <= 2099:
            return year(n, L)
    if not dec:
        return cardinal(n, L)
    return f"{cardinal(n, L)} {L.point} " + (
        cardinal(int(dec), L) if L.decwords and len(dec) <= 2
        and dec[0] != "0" else digits(dec, L))  # komma tjuefem; point two five


def money(s, cur, L):
    """12,50 kr -> tolv kroner og femti øre; Spanish $1,000,000 -> un
    millón de pesos. None if s isn't a number in L's notation."""
    one, many, cent = L.money[cur]
    if (p := parse(s, L)) is None:
        return None
    n, dec = p
    if dec and (len(dec) != 2 or dec == "00"):
        return f"{number(s, L, False)} {many}"
    w = L.un(cardinal(n, L), many) + (
        f" {L.of}" if L.of and n and n % 10**6 == 0 else "")
    w += f" {one if n == 1 else many}"
    return f"{w} {L.cents} {L.un(cardinal(int(dec), L), cent)} {cent}" \
        if dec else w


def clock(h, m, L, suffix=""):
    """14:30 -> fjorten tretti; 14:05 -> fjorten null fem; 9:00 -> nine
    o'clock; the suffix (am, pm) as L.ampm reads it."""
    h, m = int(h), int(m or 0)
    w = L.un(cardinal(h, L), "hora")  # la una
    if m:
        w += " " + (cardinal(m, L) if m >= 10 else f"{L.oh} {L.ones[m]}")
    elif not suffix and (o := L.oclock[h > 12]):
        w += " " + o  # nine o'clock, fourteen hundred
    return w + (L.ampm(suffix, h) if suffix else "")


PHONE = re.compile(r"(?:\+(\d{1,3}(?=[\s-])|\d\d))?[\s-]*(.*)")


def phone(s, L, say=digits, sep=" "):
    """+1 555 123 4567 -> plus one five five five ...: the country code and
    the groups (as written, else in pairs if they fit), each read by say."""
    plus, rest = PHONE.fullmatch(s).groups()
    groups = re.split(r"[\s-]+", rest) if re.search(r"[\s-]", rest) \
        else re.findall(r"\d\d", rest) if len(rest) % 2 == 0 else [rest]
    return sep.join(([f"{L.plus} {say(plus, L)}"] if plus else [])
                    + [say(g, L) for g in groups])


def pair(g, L):
    """A group of a phone number: two digits as a number."""
    return cardinal(int(g), L) if len(g) == 2 and g[0] != "0" \
        else digits(g, L)


# ------------------------------------------------------------- the rules
# A rule builder gives a language its rules for one format: [(compiled
# pattern, replacement)]. A language applies its builders in order.

def rule(pat, say, flags=re.I):
    """A rule builder: the pattern pat (or pat(L)), replaced by say(m, L)."""
    def build(L):
        return [(re.compile(pat(L) if callable(pat) else pat, flags),
                 lambda m: say(m, L))]
    return build


def abbrevs(words):
    """A rule builder for abbreviations before a number ({pattern: word}):
    nr. 5 -> nummer 5."""
    def build(L):
        return [(re.compile(r"(?<!\w)" + p + r"(?=\s*[#+]?\d)", re.I), w)
                for p, w in words.items()]
    return build


def date(m, L):
    """A date from the groups d, m and y, as L.date says."""
    y = m["y"]
    return L.date.format(d=L.day(int(m["d"])), m=L.months[int(m["m"]) - 1],
                         y=year(int(y), L) if len(y) > 2 else number(y, L))


def months(L):
    """A pattern for L's month names."""
    return "(" + "|".join(L.months) + ")"


D, M, Y = (r"(?P<d>0?[1-9]|[12]\d|3[01])", r"(?P<m>0?[1-9]|1[0-2])",
           r"(?P<y>\d{4}|\d\d)")
DAY = r"([1-9]|[12]\d|3[01])"
# 02.10.2026, 02.10.26; 2/10/2026, 2-10-2026 (d/m); 2026-10-02
DOTTED = rule(LONE.format(D + r"\." + M + r"\." + Y), date)
SLASHED = rule(LONE.format(D + r"(?P<s>[/-])" + M + r"(?P=s)" + Y), date)
ISO = rule(LONE.format(r"(?P<y>\d{4})-(?P<m>0[1-9]|1[0-2])"
                       r"-(?P<d>0[1-9]|[12]\d|3[01])"), date)
DAY_MONTH = rule(  # 2. oktober
    lambda L: r"\b" + DAY + r"\.\s+" + months(L) + r"\b",
    lambda m, L: f"{ordinal(int(m[1]), L)} {m[2]}")
DAY_DE_MONTH = rule(  # 2 de octubre (de 2026)
    lambda L: r"\b" + DAY + r"\s+de\s+" + months(L)
    + r"\b(?:\s+de\s+(\d{4})\b)?",
    lambda m, L: f"{L.day(int(m[1]))} de {m[2]}"
    + (f" de {year(int(m[3]), L)}" if m[3] else ""))
MONTH_DAY = rule(  # October 2(nd)(, 2026)
    lambda L: r"\b" + months(L) + r"\s+" + DAY
    + r"(?:st|nd|rd|th)?\b(?:,?\s+(\d{4})\b)?",
    lambda m, L: f"{m[1]} {ordinal(int(m[2]), L)}"
    + (f" {year(int(m[3]), L)}" if m[3] else ""))


def version(m, L):
    """v2.3.1 -> versjon to punkt tre punkt én (not 1.000.000)."""
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", m[3]):
        return m[0]
    return (m[1] or (L.version + " " if m[2] else "")) + f" {L.dot} ".join(
        L.one if p == "1" else cardinal(int(p), L) for p in m[3].split("."))


# versions and IP addresses: v2.3.1, 10.0.0.1
VERSIONS = rule(r"(?<![\w.])((?:versjon|versi[oó]n)\s+)?(v\s?)?"
                r"(\d+(?:\.\d+){2,}|(?<=v)\d+\.\d+)(?![\w]|\.\d)", version)


def say_time(m, L):
    """A time from the groups hour, minutes, suffix (keeping a period the
    suffix took from the end of the text)."""
    sfx = m[3] or ""
    w = clock(m[1], m[2], L, sfx)
    end = sfx.endswith(".") and m.end() == len(m.string)
    return w + "." if end and not w.endswith(".") else w


def kl_times(word):
    """kl. 14:30, kl. 8-16 -> word fjorten tretti, word åtte til seksten"""
    hm = r"(\d{1,2})(?:[:.](\d{2}))?"
    return rule(r"\bkl\.?\s*" + hm + r"(?:\s?[–-]\s?" + hm + r")?(?![\d:])",
                lambda m, L: f"{word} {clock(m[1], m[2], L)}"
                + (f" {L.to} {clock(m[3], m[4], L)}" if m[3] else ""))


AMPM = r"\s?[ap]\.?m\.?"


def clock_times(suffixes=AMPM):
    """14:30, 2:30 pm (and other suffixes: Spanish 14:30 hrs)"""
    return rule(LONE.format(r"([01]?\d|2[0-3]):([0-5]\d)(" + suffixes + ")?"),
                say_time)


AMPM_TIMES = rule(LONE.format(r"(1[0-2]|0?[1-9])()(" + AMPM + ")"),
                  say_time)  # 9 am


def phones(sep=r"[ \xa0]", lengths=(8, 10, 11)):
    """Phone numbers of these lengths (digits), groups split by sep: +47 22
    33 44 55, 90 12 34 56, 901 23 456, +4790123456."""
    def say(m, L):
        if len(re.sub(r"\D", "", m[1])) not in lengths \
                or re.fullmatch(r"\d{1,3}(?: \d{3})+", m[1]):  # 12 500 000
            return m[1]
        return L.read_phone(m[1])
    return rule(r"(?<![\w+])((?:\+\d{1,3}\s?)?\d{2,3}(?:" + sep
                + r"\d{2,4}){2,4}|\+\d{9,12})(?![\w]|[.,]\d)", say)


def say_id(s, L):
    """An ID: 3+ digits one by one."""
    return digits(s, L, PAUSE) if len(s) > 2 else cardinal(int(s), L)


CALLED = rule(r"\b(telefon|mobil|ring|phone|call|tel[eé]fono|celular|cel"
              r"|whatsapp|ll[aá]ma(?:nos)?)(:?\s+)(\d{8}|\d{10})\b",
              lambda m, L: m[1] + m[2] + L.read_phone(m[3]))
# IDs: #4521, ordre 48213, nummer 12
HASH_IDS = rule(lambda L: r"(?<!\w)(" + L.number + r"\s+)?#(\d+)\b",
                lambda m, L: f"{m[1] or L.number + ' '}{say_id(m[2], L)}")
NAMED_IDS = rule(r"\b(" + ID_WORDS + r")(\s*)(\d+)\b(?![.,]\d)",
                 lambda m, L: m[1] + (m[2] or " ") + say_id(m[3], L))
# money: 1 250 kr, kr 1.250,-, $40, 12,50 NOK, $1,250.50 MXN
PRICES = rule(r"(?<![\w$€])(kr\.?|nok|usd|us\$|mxn|mx\$|eur|\$|€)\s?(" + NUM
              + r")(?:,-)?(?:\s?(mxn|usd|eur|nok)\b)?(?![\w]|[.,]\d)",
              lambda m, L: money(m[2], L.currency[(m[3] or m[1]).lower()],
                                 L) or m[0])
AMOUNTS = rule(LONE.format(r"(" + NUM + r")(?:,-)?\s?(kr|nok|kroner|usd|eur"
                           r"|euros?|dollars?|mxn|pesos?|d[oó]lar(?:es)?"
                           r"|dlls?|\$|€)(?!\w)"),
               lambda m, L: money(m[1], L.currency[m[2].lower()], L)
               or m[0])
PERCENT = rule(LONE.format(r"(" + NUM + r")\s?%"),
               lambda m, L: f"{number(m[1], L, False)} {L.percent}")
RANGES = rule(LONE.format(r"(\d{1,4})\s?[–-]\s?(\d{1,4})"),
              lambda m, L: f"{number(m[1], L)} {L.to} {number(m[2], L)}")
ORDINAL_DOTS = rule(  # 2. plass (not "1. Gå til": a list)
    r"(?<![\w.,])([1-9]\d?)\.(?=\s+[^\W\d_A-ZÆØÅ])",
    lambda m, L: ordinal(int(m[1]), L), 0)
ORDINAL_SUFFIXES = rule(r"\b([1-9]\d?)(st|nd|rd|th)\b",  # 1st, 23rd
                        lambda m, L: ordinal(int(m[1]), L))
PLAIN = rule(LONE.format("(" + NUM + ")"), lambda m, L: number(m[1], L))


# ------------------------------------------------------------- languages

@dataclass(frozen=True, kw_only=True)
class Lang:
    """A language's number words, notation, grammar and rules. The grammar
    (the methods) is the Norwegian and English way; Spanish has its own."""
    # words: 0..19 (Spanish ..29), tens, 1st..19th (Spanish ..10th), 20th..
    ones: Sequence[str]
    tens: Sequence[str]
    ord: Sequence[str]
    ordtens: Sequence[str] = ()
    join: str  # tens and ones: tjuefem, twenty-five
    and_: str  # before a last part under 100: to hundre og fem
    hundred: tuple[str, str]  # (1 x, n x)
    hundreds: Sequence[str] = ()  # 100..900 if not n x (100 alone: 1 x)
    thousand: tuple[str, str]
    million: tuple[str, str]
    year_words: tuple[str, ...] = ()  # 1900, 1905: nitten hundre (og fem)
    months: Sequence[str]
    date: str  # "{d} {m} {y}"
    # notation and the words for it
    dec: str
    group: str  # besides a space
    point: str  # dec read
    decwords: bool  # 2 decimals as a number: komma tjuefem
    dot: str  # versions: to punkt tre
    one: str  # 1 in a version
    percent: str
    to: str  # ranges
    plus: str  # country codes
    number: str  # #4521
    version: str  # v2.3
    oh: str  # 14:05: fjorten null fem
    oclock: tuple[str, str] = ("", "")  # 9:00, 14:00
    pairs: bool = False  # a phone number's groups of two as numbers
    money: dict[str, tuple[str, str, str]]  # code: (1, n, cents)
    currency: dict[str, str] = field(default_factory=CURRENCY.copy)  # $: USD
    cents: str  # tolv kroner og femti øre
    of: str = ""  # un millón de pesos
    rules: tuple[Callable, ...]  # rule builders, in the order they apply

    @cached_property
    def compiled(self):
        """The rules, built for this language."""
        return [r for build in self.rules for r in build(self)]

    def un(self, w: str, noun: str = "") -> str:
        """The number w (in words) before noun (Spanish: un día)."""
        return w

    def day(self, n: int) -> str:
        """The day of a date: andre (oktober)."""
        return ordinal(n, self)

    def ampm(self, suffix: str, h: int) -> str:
        """A time's suffix (am, pm) after the hour h, as it is read."""
        return suffix

    def read_phone(self, s: str) -> str:
        """A phone number: digit by digit, or in pairs (pluss førtisju)."""
        return phone(s, self, pair if self.pairs else digits)


NO = Lang(
    ones="null en to tre fire fem seks sju åtte ni ti elleve tolv tretten "
         "fjorten femten seksten sytten atten nitten".split(),
    tens="_ ti tjue tretti førti femti seksti sytti åtti nitti".split(),
    ord="første andre tredje fjerde femte sjette sjuende åttende niende "
        "tiende ellevte tolvte trettende fjortende femtende sekstende "
        "syttende attende nittende".split(),
    ordtens="tjuende trettiende førtiende femtiende sekstiende syttiende "
            "åttiende nittiende".split(),
    join="", and_="og", hundred=("hundre", "hundre"),
    thousand=("tusen", "tusen"), million=("en million", "millioner"),
    year_words=("hundre", "hundre og"),
    months="januar februar mars april mai juni juli august september "
           "oktober november desember".split(),
    date="{d} {m} {y}",
    dec=",", group=".", point="komma", decwords=True, dot="punkt",
    one="én",  # stressed: "punkt en fikser" was heard as "punkt. En"
    percent="prosent", to="til", plus="pluss", number="nummer",
    version="versjon", oh="null", pairs=True,
    money={"NOK": ("krone", "kroner", "øre"),
           "USD": ("dollar", "dollar", "cent"),
           "EUR": ("euro", "euro", "cent"),
           "MXN": ("peso", "pesos", "centavos")}, cents="og",
    rules=(abbrevs({r"nr\.?": "nummer", r"tlf\.?": "telefon",
                    r"ca\.": "cirka"}),
           DOTTED, ISO, DAY_MONTH, VERSIONS, kl_times("klokka"),
           clock_times(), phones(), CALLED, HASH_IDS, NAMED_IDS, PRICES,
           AMOUNTS, PERCENT, RANGES, ORDINAL_DOTS, ORDINAL_SUFFIXES, PLAIN))

EN = Lang(
    ones="zero one two three four five six seven eight nine ten eleven "
         "twelve thirteen fourteen fifteen sixteen seventeen eighteen "
         "nineteen".split(),
    tens="_ ten twenty thirty forty fifty sixty seventy eighty "
         "ninety".split(),
    ord="first second third fourth fifth sixth seventh eighth ninth tenth "
        "eleventh twelfth thirteenth fourteenth fifteenth sixteenth "
        "seventeenth eighteenth nineteenth".split(),
    ordtens="twentieth thirtieth fortieth fiftieth sixtieth seventieth "
            "eightieth ninetieth".split(),
    join="-", and_="and", hundred=("one hundred", "hundred"),
    thousand=("one thousand", "thousand"), million=("one million", "million"),
    year_words=("hundred", "oh"),
    months="January February March April May June July August September "
           "October November December".split(),
    date="{m} {d} {y}",
    dec=".", group=",", point="point", decwords=False, dot="point",
    one="one", percent="percent", to="to", plus="plus", number="number",
    version="version", oh="oh", oclock=("o'clock", "hundred"),
    money={"NOK": ("krone", "kroner", "øre"),
           "USD": ("dollar", "dollars", "cents"),
           "EUR": ("euro", "euros", "cents"),
           "MXN": ("peso", "pesos", "centavos")}, cents="and",
    rules=(abbrevs({r"no\.": "number", r"tel\.": "phone",
                    r"approx\.": "approximately"}),
           DOTTED, ISO, MONTH_DAY, VERSIONS, clock_times(), phones(), CALLED,
           HASH_IDS, NAMED_IDS, PRICES, AMOUNTS, PERCENT, RANGES,
           ORDINAL_SUFFIXES, PLAIN))


# ------------------------------------------------- Spanish (Mexican usage)

DAYTIME = {"a": "de la mañana", "p": "de la tarde", "n": "de la noche",
        "h": "horas"}
APOCOPE = {"primero": "primer", "tercero": "tercer"}  # 1er, 3er
# uno before a noun: un (masculine, and the default) or una
MASC = set("día días mapa mapas problema problemas programa programas "
           "sistema sistemas tema temas idioma idiomas clima".split())
FEM = set("vez veces red redes clave claves llave llaves noche noches tarde "
          "tardes parte partes calle calles mano manos foto fotos imagen "
          "imágenes orden órdenes".split())
FEM_END = r"(?:a|ión|dad|tad|tud)s?$|iones$|des$"
# Words after a number that aren't its noun: el 1 de mayo, el 1er fue
NOT_NOUNS = WORDS["es"]  # Spanish's common words


class Spanish(Lang):
    """Spanish grammar: un día, una hora; el primero de mayo, el dos de
    mayo; de la tarde; phone numbers in groups of 2+4+4."""

    def un(self, w: str, noun: str = "") -> str:
        """uno before a noun: un (veintiún), or una before a feminine one."""
        if not w.endswith("uno") or noun in NOT_NOUNS:
            return w
        noun = noun.lower()
        if noun in FEM or noun not in MASC and re.search(FEM_END, noun):
            return w[:-1] + "a"
        return w[:-3] + ("ún" if w.endswith("veintiuno") else "un")

    def day(self, n: int) -> str:
        """The day of a date: dos de octubre (1: primero)."""
        return ordinal(n, self) if n == 1 else cardinal(n, self)

    def ampm(self, suffix: str, h: int) -> str:
        """2:30 pm: de la tarde (from 8: de la noche); 14:30 hrs: horas."""
        k = suffix.strip()[0].lower()
        k = "n" if k == "p" and h % 12 >= 8 or k == "a" and h % 12 == 0 else k
        return " " + DAYTIME[k]

    def read_phone(self, s: str) -> str:
        """55 1234 5678 -> cincuenta y cinco， doce treinta y cuatro， ...:
        the groups (10 digits: 2+4+4) with a pause between them (no plain
        comma: a chunk may be cut at one)."""
        plus, rest = PHONE.fullmatch(s).groups()
        if len(rest) == 10 and rest.isdigit():
            s = f"+{plus} " * bool(plus) + f"{rest[:2]} {rest[2:6]} {rest[6:]}"
        return phone(s, self, es_group, PAUSE)


def es_group(g, L):
    """A group of a phone number: 2 or 3 digits as a number, 4 as two."""
    if len(g) == 4:
        return f"{es_group(g[:2], L)} {es_group(g[2:], L)}"
    return cardinal(int(g), L) if len(g) in (2, 3) and g[0] != "0" \
        else digits(g, L)


def es_ordinal(m, L):
    """1er, 1º, 1ª, 2do, 3ra -> primer (before a noun, else primero),
    primero, primera, segundo, tercera; left alone if the suffix doesn't
    fit the number (2er)."""
    w, suffix, noun = L.ord[int(m[1]) - 1], m[2].lower(), m[3] or ""
    if suffix == "er":  # el 1er pago, but el 1er fue: el primero fue
        short = noun and noun.lower() not in NOT_NOUNS
        return (APOCOPE[w] if short else w) if w in APOCOPE else m[0]
    if suffix in "º°":
        return w
    return w[:-1] + "a" if suffix == "ª" else next(
        (f for f in (w, w[:-1] + "a") if f.endswith(suffix)), m[0])


ES_ORDINALS = rule(r"(?<![\w.,])(10|[1-9])\.?(º|ª|°|ero|era|er|ro|ra|do|da"
                   r"|to|ta|mo|ma|vo|va|no|na)(?!\w)(?=\s+([^\W\d_]+)|)",
                   es_ordinal)
ES_NOUNS = rule(  # 1 día, 21 días, 1 hora: un día, veintiún días, una hora
    LONE.format(r"(1|[1-9]\d{0,2}1)") + r"(?=\s+([^\W\d_]{3,}))",
    lambda m, L: L.un(number(m[1], L), m[2]))

ES = Spanish(
    ones="cero uno dos tres cuatro cinco seis siete ocho nueve diez once "
         "doce trece catorce quince dieciséis diecisiete dieciocho "
         "diecinueve veinte veintiuno veintidós veintitrés veinticuatro "
         "veinticinco veintiséis veintisiete veintiocho veintinueve".split(),
    tens="_ diez veinte treinta cuarenta cincuenta sesenta setenta ochenta "
         "noventa".split(),
    ord="primero segundo tercero cuarto quinto sexto séptimo octavo noveno "
        "décimo".split(),
    join=" y ", and_="",  # treinta y uno; ciento uno
    hundred=("cien", ""), thousand=("mil", "mil"),
    hundreds="ciento doscientos trescientos cuatrocientos quinientos "
             "seiscientos setecientos ochocientos novecientos".split(),
    million=("un millón", "millones"),
    months="enero febrero marzo abril mayo junio julio agosto septiembre "
           "octubre noviembre diciembre".split(),
    date="{d} de {m} de {y}",
    dec=".", group=",", point="punto", decwords=True, dot="punto",
    one="uno", percent="por ciento", to="a", plus="más", number="número",
    version="versión", oh="cero",
    money={"MXN": ("peso", "pesos", "centavos"),
           "USD": ("dólar", "dólares", "centavos"),
           "EUR": ("euro", "euros", "céntimos"),
           "NOK": ("corona", "coronas", "øre")},
    currency=CURRENCY | {"$": "MXN"},  # $ in Mexican text is pesos
    cents="con", of="de",  # un millón de pesos con cincuenta centavos
    rules=(abbrevs({r"n[uú]m\.?": "número", r"no\.": "número",
                    r"tel\.?": "teléfono", r"aprox\.": "aproximadamente"}),
           DOTTED, SLASHED, ISO, DAY_DE_MONTH, VERSIONS,
           clock_times(AMPM + r"|\s?hrs?\.?"), AMPM_TIMES,
           phones(r"[ \xa0-]", (10, 12)), CALLED, HASH_IDS, NAMED_IDS, PRICES,
           AMOUNTS, PERCENT, RANGES, ES_ORDINALS, ES_NOUNS, PLAIN))

NUMBERS = {"no": NO, "en": EN, "es": ES}


def numbers(text, lang):
    """Spell out the numbers in text in lang ("no", "en", "es"): dates,
    times, phone numbers, IDs, money, percentages, ranges, ordinals, years
    and plain numbers. Text in another language is left as it is."""
    L = NUMBERS.get(lang)
    if not L or not re.search(r"\d", text):
        return text
    for pat, f in L.compiled:
        text = pat.sub(f, text)
    return text
