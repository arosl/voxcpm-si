from si.numbers import NUMBERS, cardinal, numbers, year
from si.text import chunks

NO, EN = NUMBERS["no"], NUMBERS["en"]


def no(s):
    return numbers(s, "no")


def en(s):
    return numbers(s, "en")


def test_cardinal():
    assert cardinal(21, NO) == "tjueen"
    assert cardinal(101, NO) == "hundre og en"
    assert cardinal(1001, NO) == "tusen og en"
    assert cardinal(2026, NO) == "to tusen og tjueseks"
    assert cardinal(48213, NO) == "førtiåtte tusen to hundre og tretten"
    assert cardinal(2_500_000, NO) == "to millioner fem hundre tusen"
    assert cardinal(48213, EN) == \
        "forty-eight thousand two hundred and thirteen"
    assert cardinal(1_000_000, EN) == "one million"


def test_years():
    assert year(2026, NO) == "tjue tjueseks"
    assert year(1998, NO) == "nitten nittiåtte"
    assert year(1900, NO) == "nitten hundre"
    assert year(1905, NO) == "nitten hundre og fem"
    assert year(2005, NO) == "to tusen og fem"
    assert year(2026, EN) == "twenty twenty-six"
    assert year(1905, EN) == "nineteen oh five"
    assert no("berørt i 2025.") == "berørt i tjue tjuefem."
    assert no("fra 2020-2026") == "fra tjue tjue til tjue tjueseks"


def test_ids():
    assert no("Ordre 48213 er sendt.") == \
        "Ordre fire， åtte， to， en， tre er sendt."
    assert no("Saken har nummer #4521.") == "Saken har nummer fire， fem， to， en."
    assert no("Se sak #4521.") == "Se sak nummer fire， fem， to， en."
    assert no("ordre nr. 4521") == "ordre nummer fire， fem， to， en"
    assert no("Postnummer 0150 Oslo") == "Postnummer null， en， fem， null Oslo"
    assert no("Det gjelder 101 kunder.") == "Det gjelder hundre og en kunder."
    assert en("Ticket #4521, order 48213") == \
        "Ticket number four， five， two， one, " \
        "order four， eight， two， one， three"
    assert no("4G og mp3 og COVID-19") == "4G og mp3 og COVID-nitten"


def test_money():
    assert no("1 250 kr") == "tusen to hundre og femti kroner"
    assert no("kr 1.250,-") == "tusen to hundre og femti kroner"
    assert no("12 499,50 kr") == \
        "tolv tusen fire hundre og nittini kroner og femti øre"
    assert no("Det kostet 12.50 kr.") == \
        "Det kostet tolv kroner og femti øre."
    assert no("1 kr og 2,5 NOK") == "en krone og to komma fem kroner"
    assert no("1.000.000 kr") == "en million kroner"
    assert en("$40") == "forty dollars"
    assert en("$1,250.50") == \
        "one thousand two hundred and fifty dollars and fifty cents"
    assert en("€12.99") == "twelve euros and ninety-nine cents"


def test_decimals_and_percent():
    assert no("3,5 %") == "tre komma fem prosent"
    assert no("15%") == "femten prosent"
    assert no("3,25 og 0,05") == "tre komma tjuefem og null komma null fem"
    assert en("3.5% and 3.14") == \
        "three point five percent and three point one four"
    assert no("3 200 brukere") == "tre tusen to hundre brukere"


def test_dates_and_times():
    assert no("den 02.10.2026") == "den andre oktober tjue tjueseks"
    assert no("2026-10-02") == "andre oktober tjue tjueseks"
    assert no("innen 2. oktober") == "innen andre oktober"
    assert no("kl. 14:30") == "klokka fjorten tretti"
    assert no("kl 09.15") == "klokka ni femten"
    assert no("kl. 8-16") == "klokka åtte til seksten"
    assert no("23:05") == "tjuetre null fem"
    assert en("on October 2, 2026") == "on October second twenty twenty-six"
    assert en("2:30 pm, 9:00, 14:00") == \
        "two thirty pm, nine o'clock, fourteen hundred"
    assert en("the 1st and 23rd") == "the first and twenty-third"


def test_phone():
    assert no("+47 22 33 44 55") == \
        "pluss førtisju tjueto trettitre førtifire femtifem"
    assert no("90 12 34 56") == "nitti tolv trettifire femtiseks"
    assert no("901 23 456") == "ni null en tjuetre fire fem seks"
    assert no("tlf. 90123456") == "telefon nitti tolv trettifire femtiseks"
    assert en("call 555 123 4567") == \
        "call five five five one two three four five six seven"


def test_versions_ordinals_ranges():
    assert no("v2.3.1") == "versjon to punkt tre punkt én"
    assert no("Versjon v2.3.1") == "Versjon to punkt tre punkt én"
    assert en("version 2.3.1") == "version two point three point one"
    assert no("10-12 varer") == "ti til tolv varer"
    assert no("2. plass") == "andre plass"
    assert no("1. Gå til") == "en. Gå til"  # a list item, not an ordinal


def test_other_languages_untouched():
    assert numbers("Ordre 48213.", None) == "Ordre 48213."
    assert numbers("Bestellung 48213.", "de") == "Bestellung 48213."
    assert numbers("3/4 og 10/02/2026", "no") == "3/4 og 10/02/2026"
    assert no("den 10.02.26") == "den tiende februar tjueseks"


def test_chunks_spell_out():
    assert chunks("Ordre 48213 er sendt, og vi svarer innen 2. oktober.") == [
        "Ordre fire， åtte， to， en， tre er sendt, og vi svarer innen andre "
        "oktober."]
    assert chunks("Hello, your order 48213 is on its way.") == [
        "Hello, your order four， eight， two， one， three is on its way."]


# ------------------------------------------------------------ Spanish (MX)
ES = NUMBERS["es"]


def es(s):
    return numbers(s, "es")


def test_es_cardinal():
    assert cardinal(26, ES) == "veintiséis"
    assert cardinal(31, ES) == "treinta y uno"
    assert cardinal(100, ES) == "cien"
    assert cardinal(101, ES) == "ciento uno"
    assert cardinal(555, ES) == "quinientos cincuenta y cinco"
    assert cardinal(1001, ES) == "mil uno"
    assert cardinal(2026, ES) == "dos mil veintiséis"
    assert cardinal(21_000, ES) == "veintiún mil"
    assert cardinal(100_000, ES) == "cien mil"
    assert cardinal(1_000_000, ES) == "un millón"
    assert cardinal(2_500_000, ES) == "dos millones quinientos mil"
    assert es("1 día, 21 días, 1 hora, 1 vez, 31 personas") == \
        "un día, veintiún días, una hora, una vez, treinta y una personas"
    assert es("Es el 1.") == "Es el uno."


def test_es_years_and_dates():
    assert year(2026, ES) == "dos mil veintiséis"
    assert es("en 1998") == "en mil novecientos noventa y ocho"
    for d in ("02/10/2026", "2/10/2026", "02-10-2026", "2026-10-02",
              "2 de octubre de 2026"):
        assert es(d) == "dos de octubre de dos mil veintiséis", d
    assert es("antes del 9 de octubre") == "antes del nueve de octubre"
    assert es("el 1 de mayo") == "el primero de mayo"
    assert es("vence el 31/12/26") == \
        "vence el treinta y uno de diciembre de veintiséis"


def test_es_times():
    assert es("14:30") == "catorce treinta"
    assert es("a las 2:30 pm") == "a las dos treinta de la tarde"
    assert es("a las 9 am") == "a las nueve de la mañana"
    assert es("a la 1:00 pm") == "a la una de la tarde"
    assert es("a las 10:15 p.m.") == "a las diez quince de la noche."
    assert es("de 9:00 a 18:30 hrs") == "de nueve a dieciocho treinta horas"
    assert es("14:05") == "catorce cero cinco"


def test_es_money():
    assert es("$1,250.50") == \
        "mil doscientos cincuenta pesos con cincuenta centavos"
    assert es("$1,250.50 MXN") == es("$1,250.50")
    assert es("299 MXN") == "doscientos noventa y nueve pesos"
    assert es("25 USD y 1 USD") == "veinticinco dólares y un dólar"
    assert es("US$40") == "cuarenta dólares"
    assert es("150 dólares") == "ciento cincuenta dólares"
    assert es("€12.99") == "doce euros con noventa y nueve céntimos"
    assert es("$1,000,000") == "un millón de pesos"
    assert es("21 pesos") == "veintiún pesos"
    assert en("$40") == "forty dollars"  # $ is pesos in Spanish text only


def test_es_decimals_percent_ordinals():
    assert es("3.5") == "tres punto cinco"
    assert es("3.14 y 0.05") == "tres punto catorce y cero punto cero cinco"
    assert es("35% y 12.25%") == \
        "treinta y cinco por ciento y doce punto veinticinco por ciento"
    assert es("3-5 días") == "tres a cinco días"
    assert es("el 1er pago, el 2º, la 3ra, el 2do, la 1ª, el 10mo") == \
        "el primer pago, el segundo, la tercera, el segundo, la primera, " \
        "el décimo"
    assert es("el 1er fue de 750 pesos; el 3er.") == \
        "el primero fue de setecientos cincuenta pesos; el tercero."
    assert es("2er") == "2er"  # doesn't fit: left alone


def test_es_phone_and_ids():
    mx = "cincuenta y cinco， doce treinta y cuatro， cincuenta y seis " \
        "setenta y ocho"
    assert es("55 1234 5678") == mx
    assert es("55-1234-5678") == mx
    assert es("tel. 5512345678") == "teléfono " + mx
    assert es("+52 55 1234 5678") == "más cincuenta y dos， " + mx
    assert es("pedido 48213") == "pedido cuatro， ocho， dos， uno， tres"
    assert es("No. 4521 y #4521") == \
        "número cuatro， cinco， dos， uno y número cuatro， cinco， dos， uno"
    assert es("factura número 1043") == \
        "factura número uno， cero， cuatro， tres"
    assert es("versión 2.3.1") == "versión dos punto tres punto uno"
    assert no("3/4 og 10/02/2026") == "3/4 og 10/02/2026"  # only Spanish: d/m


def test_es_chunks():
    assert chunks("Hola Mariana, tu pedido 48213 se envió el 02/10/2026 y "
                  "llegará antes del 9 de octubre.") == [
        "Hola Mariana, tu pedido cuatro， ocho， dos， uno， tres se envió el "
        "dos de octubre de dos mil veintiséis y llegará antes del nueve de "
        "octubre."]


def test_unparsed_amount_keeps_its_currency():
    # dots as thousands aren't Mexican or English notation: leave it as is
    assert numbers("Cuesta $3.111.369 en total.", "es") == \
        "Cuesta $3.111.369 en total."
    assert numbers("It costs $3.111.369.", "en") == "It costs $3.111.369."
