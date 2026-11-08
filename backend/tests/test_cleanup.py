"""PDF/OCR matnini tozalash: kolontitullar, sahifa raqamlari, tire bilan boʻlingan soʻzlar,
mundarija orqali boblar va raqamlash. (Haqiqiy kitob matni repoga kiritilmaydi — sintetik namuna.)"""
from app.services.text.cleanup import clean_ocr_text, extract_toc, looks_hard_wrapped
from app.services.text.parsers import parse_book

FILLER = "Бу жумла китобнинг оддий матни бўлиб, у саҳифа кенглигида узилган ҳолда\nкелади ва ўқувчига"

TOC = """
                       МУНДАРИЖА

     КИРИШ. Менинг ҳикоям                              9

     АСОСИЙ ТАМОЙИЛЛАР. Нега кичик ўзгаришлар катта
     натижаларга олиб келади?                    21
        Одатларнинг ҳайратланарли кучи           22
        Шахсият қандай шаклланади?               41

     БИРИНЧИ ҚОИДА. Одат яққол бўлиши керак           73
        Кўриниши яхши бўлмаган одам                   74

     ХОТИМА. Давомли натижалар сири                  250
"""


def page(header: str, body: str, number: int) -> str:
    return f"\n       {header}\n\n{body}\n\n\n                                    | {number}\n"


def build_book() -> str:
    paras = []
    for i in range(6):
        paras.append(f" {FILLER} жуда фойдали маълумот бе-\nради. Бу {i}-параграфнинг охири.")
    body = "\n".join(paras)
    parts = [
        "© “Нашриёт” МЧЖ, 2022\nISBN 978-9943-23-194-8\n",
        TOC,
        "\n                     КИРИШ\n\n\n                 МЕНИНГ ҲИКОЯМ\n\n\n" + body,
        page("АТОМ ОДАТЛАР", body, 12),
        "\n\n       АСОСИЙ ТАМОЙИЛЛАР\n\n  НЕГА КИЧИК ЎЗГАРИШЛАР КАТТА\n  НАТИЖАЛАРГА ОЛИБ КЕЛАДИ?\n\n",
        "                        1\n          ОДАТЛАРНИНГ ҲАЙРАТЛАНАРЛИ\n                 КУЧИ\n\n\n" + body,
        page("АТОМ ОДАТ/1АР", body, 24),
        "\n          НАТИЖАЛАР Ж ЯХШИЛАНИШ Ж\n\n" + body,  # rasm yozuvi — sarlavha emas
        "\n                        2\n          ШАХСИЯТ ҚАНДАЙ ШАКЛЛАНАДИ?\n\n\n" + body,
        page("АТОМ ОДАТЛАР", body, 42),
        "\n\nБИРИНЧИ ҚОИДА\n\nОДАТ ЯҚҚОЛ БЎЛИШИ\nКЕРАК\n                        3\n"
        "          КЎРИНИШИ ЯХШИ БЎЛМАГАН\n                      ОДАМ\n\n\n"
        "Психолог бир воқеа айтиб берди.\n    -Менга кўринишингиз ёқмаяпти, — дейди у.\n"
        "Ўзини соғлом ҳис қилаётган қайнота кулди.\n" + body,
        page("БИРИНЧИ ҚОИДА: ОДАТ ЯҚҚОЛ БЎЛИШИ КЕРАК", body, 80),
        page("БИРИНЧИ ҚОИДА: ОДАТЯҚҚО/1 БЎЛИШИ КЕРАИ", body, 82),
        page("БИРИНЧИ ҚОИДА: ОДАТ ЯҚҚОЛ БЎЛИШИ КЕРАК", body, 84),
        page("БИРИНЧИ ҚОИДА: ОДАТ ЯҚҚОЛ БЎЛИШИ КЕРАК", body, 86),
        page("АТОМ ОДАТЛАР", body, 83),
        "\n          ХОТИМА\n\n   ДАВОМЛИ НАТИЖАЛАР СИРИ\n\n" + body,
    ]
    return "\n".join(parts)


def test_detects_hard_wrapped_text():
    assert looks_hard_wrapped(build_book())
    assert not looks_hard_wrapped("Bitta uzun paragraf. " * 200)


def test_toc_parsing_and_numbering():
    toc, region = extract_toc(build_book())
    assert region is not None
    assert [e.title for e in toc][:2] == [
        "КИРИШ. Менинг ҳикоям",
        "АСОСИЙ ТАМОЙИЛЛАР. Нега кичик ўзгаришлар катта натижаларга олиб келади?",
    ]
    assert [e.is_part for e in toc] == [False, True, False, False, True, False, False]
    assert [e.number for e in toc] == [None, None, 1, 2, None, 3, None]


def test_chapters_from_toc_and_cleanup():
    chapters = clean_ocr_text(build_book())
    assert [c.title for c in chapters] == [
        "Кириш. Менинг ҳикоям",
        "Асосий тамойиллар. Нега кичик ўзгаришлар катта натижаларга олиб келади?. "
        "1-bob. Одатларнинг ҳайратланарли кучи",
        "2-bob. Шахсият қандай шаклланади?",
        "Биринчи қоида. Одат яққол бўлиши керак. 3-bob. Кўриниши яхши бўлмаган одам",
        "Хотима. Давомли натижалар сири",
    ]
    text = "\n".join(p for c in chapters for p in c.paragraphs)
    assert "ISBN" not in text and "МЧЖ" not in text  # mualliflik sahifasi
    assert "АТОМ ОДАТ" not in text and "| 24" not in text  # kolontitul va sahifa raqami
    assert "НАТИЖАЛАР Ж" not in text  # rasm yozuvi
    assert "маълумот беради." in text  # tire bilan boʻlingan soʻz tiklandi
    assert "БИРИНЧИ ҚОИДА:" not in text
    third = chapters[3].paragraphs
    # OCR dialog tiresi ("-Менга") tiklanadi va yangi paragraf boshlanadi
    assert third[0] == "Психолог бир воқеа айтиб берди."
    assert third[1].startswith("— Менга кўринишингиз ёқмаяпти, — дейди у.")
    first = chapters[0].paragraphs
    assert len(first) == 12 and all(p.endswith("охири.") for p in first)  # tana + bitta sahifa


def test_parse_book_uses_cleanup_for_wrapped_txt():
    chapters = parse_book(build_book().encode("utf-8"), "txt")
    assert chapters[1].title.endswith("1-bob. Одатларнинг ҳайратланарли кучи")
