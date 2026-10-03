from si.text import MAX, chunks, clean, host, sentences


def test_abbreviations_dont_split():
    for s in ["Vi kan f.eks. gjøre det i morgen.",
              "Det gjelder bl.a. Oslo og Bergen.",
              "Ta med epler, pærer osv. og legg dem i kurven.",
              "Det gjelder ordre nr. 4521 fra i går.",
              "Det tar ca. 10 minutter.",
              "Møtet er kl. 14.30 den 02.10.2026 i Oslo.",
              "Ring Dr. Hansen i dag.",
              "Use a tool, e.g. Postman, for this.",
              "Prisen er 12.50 kr, dvs. litt mer enn før.",
              "Den 1. oktober kom svaret.",
              "Brevet er signert J. K. Rowling."]:
        assert sentences(s) == [s], s


def test_sentence_split():
    assert sentences("Hei Kari. Takk for svaret! Er alt i orden? Ja.") == [
        "Hei Kari.", "Takk for svaret!", "Er alt i orden?", "Ja."]
    assert sentences("Første avsnitt\n\nAndre avsnitt") == [
        "Første avsnitt.", "Andre avsnitt."]
    assert sentences('Han sa "hei"') == ['Han sa "hei".']
    assert sentences("Er det ok?") == ["Er det ok?"]
    assert sentences("En linje\nsom fortsetter.") == ["En linje som fortsetter."]


def test_urls():
    assert host("https://www.github.com/foo/bar?x=1") == "github.com"
    assert clean("Se https://github.com/openbmb/VoxCPM/issues/12.") == \
        "Se github.com."
    assert clean("Se www.vg.no/nyheter for mer") == "Se vg.no for mer"
    assert clean("Se github.com/foo/bar nå") == "Se github.com nå"
    assert clean("(https://example.com/a)") == "(example.com)"
    assert clean("[dokumentasjonen](https://docs.x.io/a/b)") == \
        "dokumentasjonen"
    assert clean("Mail ola.nordmann@firma.no i dag") == \
        "Mail ola.nordmann@firma.no i dag"
    assert clean("<mailto:ola@firma.no>") == "ola@firma.no"


def test_markdown():
    assert clean("# Oppsummering") == "Oppsummering."
    assert clean("Dette er **viktig** og `kode` og *kursiv*.") == \
        "Dette er viktig og kode og kursiv."
    assert clean("- første\n- andre punkt!") == "første.\nandre punkt!"
    assert clean("```\nx = 1\n```").strip() == "x = 1"
    assert clean("2 * 3 * 4") == "2 * 3 * 4"
    assert clean("snake_case_name") == "snake_case_name"
    assert clean("1. Gå til innstillinger") == "1. Gå til innstillinger."


def test_chunks():
    assert chunks("") == []
    assert chunks("Hei.") == ["Hei."]
    # short sentences join the next
    assert chunks("Hei. Takk for at du tok kontakt med oss i dag.") == [
        "Hei. Takk for at du tok kontakt med oss i dag."]
    assert chunks("Takk for henvendelsen. Ja. Vi ser på saken og svarer "
                  "deg så snart vi kan.") == [
        "Takk for henvendelsen. Ja. Vi ser på saken og svarer deg så snart "
        "vi kan."]
    # a short last sentence joins the one before
    long1 = ("Jeg har sjekket loggen i backend, og det ser ut som webhooken "
             "feilet med en timeout mot betalingsleverandøren.")
    assert chunks(long1 + " Ha en fin dag!") == [long1 + " Ha en fin dag!"]
    assert chunks("Takk for henvendelsen. " + long1) == [
        "Takk for henvendelsen. " + long1]
    assert chunks(long1 + " " + long1) == [long1, long1]
    # very long sentences are cut, nothing is lost
    words = " ".join(f"ord{i}" for i in range(200)) + "."
    text = "Kort start her. " + ", ".join([long1] * 4) + " " + words
    c = chunks(text)
    assert all(len(x) <= MAX for x in c), c
    assert " ".join(c).split() == text.split()


def test_whole_is_what_a_designed_voice_speaks():
    from si.text import whole
    assert whole("**Hei**, se https://github.com/a/b.\n\nDet\nkoster 40 kr.") \
        == "Hei, se github.com. Det koster førti kroner."
