"""language() on a labelled set of short messages: Norwegian, English
and Spanish, short replies, and mixed text. None means "can't tell", which
is better than a wrong guess."""

import pytest

from si.lang import language

NO = [
    "Hei Ingrid. Vi har sett på saken din.",
    "Saken har nummer 48213.",
    "Takk for henvendelsen, vi ser på det i dag.",
    "Hei.",
    "Takk!",
    "Ha en fin dag!",
    "Jeg har sjekket loggen, og det ser ut som webhooken feilet.",
    "Kan du sende oss et skjermbilde av feilmeldingen?",
    "Ordren ble sendt 2. oktober og skal være fremme i løpet av uken.",
    "Vi har refundert beløpet, og du vil se det på kontoen om 3-5 dager.",
    "Det ser ut til at feilen skyldes et utløpt sertifikat i single "
    "sign-on-oppsettet, se «Getting started with the setup».",
    "Vi har deployet en fix for login-problemet i backend.",
    "Kunden bruker Chrome på Windows og får en 500 error når hun logger inn.",
    "Hei José, takk for svaret. Vi har sendt pakken.",
    "Hei María, vi har sendt pakken til Señora López i Málaga.",
    "Carlos Hernández har ringt oss om faktura 1043.",
    "Møtet med Sofía og Pablo er flyttet til fredag.",
    "Kan du be Juan García sende en ny idé til kafé-prosjektet?",
    "Hvis det ikke fungerer, må du starte appen på nytt.",
    "Dette gjelder bare kunder i Norge.",
    "God dag! Vi har mottatt bestillingen din.",
    "Feilen er rettet i versjon 2.3.1.",
    "Beklager ventetiden, vi jobber med saken.",
    "Pakken er levert til Posten.",
    "Logg inn med BankID og prøv igjen.",
    "Vennlig hilsen Kundeservice",
    "Nei.",
    "Hei Alejandro! Bestillingen din er på vei.",
    "Vi har oppdatert API-et, så du kan bruke the new endpoint nå.",
    "Bjørn Dæhlie",  # æøå count even in a name (unknown is Norwegian too)
]

EN = [
    "Hi Ingrid, we have looked at your case.",
    "It looks like the single sign-on setup expired.",
    "Thanks.",
    "Thanks for the reply!",
    "Please send us a screenshot of the error message.",
    "Your order 48213 has been shipped and should arrive on Friday.",
    "We have refunded the amount; it will show up in 3-5 business days.",
    "Hi José, thanks for your order from Guadalajara.",
    "The customer in Monterrey says the app crashes when she logs in.",
    "Can you ask María López to reset her password?",
    "If the problem persists, please contact our support team.",
    "This is fixed in version 2.3.1.",
    "The invoice was paid by Señor Ramírez on October 2.",
    "Hello, how are you?",
    "We are looking into it and will get back to you.",
    "Is there anything else we can help you with?",
    "Sorry for the wait, we're working on it.",
    "The package was delivered.",
    "Yes, that's right.",
    "Best regards, Customer Service",
    "We shipped it to Ciudad de México yesterday.",
]

ES = [
    "Hola.",
    "Gracias.",
    "¡Gracias!",
    "¿Cómo estás?",
    "Buenos días.",
    "Hola Mariana, tu pedido 48213 se envió ayer.",
    "Gracias por contactarnos, ya estamos revisando tu caso.",
    "No, el pedido no ha llegado todavía.",
    "El cargo de $1,250.50 se te reembolsará en 3 a 5 días hábiles.",
    "Por favor envíanos una captura de pantalla del error.",
    "¿Puedes intentar cerrar sesión y volver a entrar?",
    "El deploy falló porque el webhook del backend tuvo un timeout.",
    "Tu cuenta está activa y el pago quedó registrado.",
    "Lamentamos las molestias, te enviaremos un nuevo producto.",
    "Saludos desde Tromsø, gracias por tu mensaje.",
    "Hola Bjørn, gracias por tu paciencia.",
    "Estimada Ingrid: le informamos que su factura vence el lunes.",
    "Si el problema continúa, por favor llama a soporte.",
    "La app se cierra cuando le doy click en login.",
    "Me dice que la contraseña es incorrecta.",
    "Ya quedó, muchas gracias.",
    "Tu cita es mañana a las 2:30 pm.",
    "Nuestro horario es de 9:00 a 18:30.",
    "Es tu 2º reembolso del año.",
    "Disculpa la espera, estamos trabajando en tu caso.",
    "El paquete fue entregado.",
    "Sí, es correcto.",
    "Atentamente, Servicio al Cliente",
    "Inicia sesión de nuevo e inténtalo otra vez.",
    "Claro que sí.",
    "Te mandamos el reembolso a tu tarjeta.",
    "Hicimos un update al backend y ya funciona el login.",
    "¿Me puedes mandar tu número de pedido?",
    "De nada.",
    "Adiós.",
]

UNKNOWN = [
    "Ingrid Haugen, 48213",
    "OK.",
    "48213",
    "",
    "María López",
    "Señora López, Málaga",
    "José, Ingrid, John",
    "a la de en se me",  # in several languages
    "No.",  # English, Spanish
    "Perfecto, quedo atento.",  # Spanish, but no common word
]


@pytest.mark.parametrize("lang, text", [("no", t) for t in NO]
                         + [("en", t) for t in EN] + [("es", t) for t in ES]
                         + [(None, t) for t in UNKNOWN])
def test_language(lang, text):
    assert language(text) == lang
