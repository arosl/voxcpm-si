"""Language detection: which of the languages with spelled-out numbers
(Norwegian, English, Spanish) a text is in."""

import re

# Common words that tell the languages apart (none is a word in the others:
# so not "a de del en se me la si sin te no han ha son vi favor").
WORDS = {
    "no": set("og er det som på til av med ikke jeg vi har et kan skal hvis "
              "fra ble nå deg seg hva hvordan også eller vil må blir var "
              "dette oss din ditt dere takk hei dag nei hilsen".split()),
    "en": set("the and is are of you we it that this with have was not "
              "your please if can will has our what how also or would should "
              "there they thanks regards sorry yes".split()),
    "es": set("el los las que y es por para con una un al lo le les su "
              "sus tu mi pero como cómo qué más muy ya hola gracias buenos "
              "buenas está están estás estamos hemos tiene tienes puedes "
              "puede usted cuando donde porque también hay fue este "
              "esta esto nos yo hasta desde ayer mañana saludos "
              "estimado estimada todavía nada adiós".split()),
}
# Letters only one of them uses; in a name (Bjørn, López) they say nothing
# about the text, so for Spanish only lowercase words count (Norwegian é:
# én, idé, kafé).
LETTERS = {"no": r"[æøå]", "es": r"[¿¡]|\b[a-zñáíóúü]*[ñáíóú]\w*"}


def language(text):
    """The language of text by its common words and letters ("no", "en" or
    "es"), or None if it can't tell (a tie)."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    score = {lang: sum(w in ws for w in words) for lang, ws in WORDS.items()}
    score["no"] += len(re.findall(LETTERS["no"], text.lower()))
    score["es"] += len(re.findall(LETTERS["es"], text))
    second, first = sorted(score.values())[-2:]
    return max(score, key=score.get) if first > second else None
