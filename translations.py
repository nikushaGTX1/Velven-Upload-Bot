import asyncio

from deep_translator import GoogleTranslator

MAP = {
    "tbilisi": "Тбилиси", "თბილისი": "Тбилиси", "batumi": "Батуми", "ბათუმი": "Батуми",
    "kutaisi": "Кутаиси", "ქუთაისი": "Кутаиси", "rustavi": "Рустави", "რუსთავი": "Рустави",
    "saburtalo": "Сабуртало", "საბურთალო": "Сабуртало", "vake": "Ваке", "ვაკე": "Ваке",
    "isani": "Исани", "ისანი": "Исани", "samgori": "Самгори", "სამგორი": "Самгори",
    "gldani": "Глдани", "გლდანი": "Глдани", "didube": "Дидубе", "დიდუბე": "Дидубе",
    "chugureti": "Чугурети", "ჩუღურეთი": "Чугурети", "nadzaladevi": "Надзаладеви", "ნაძალადევი": "Надзаладеви",
    "mtatsminda": "Мтацминда", "მთაწმინდა": "Мтацминда", "krtsanisi": "Крцаниси", "კრწანისი": "Крцаниси",
    "new": "новый", "new building": "новый", "ახალი": "новый", "ახალი კორპუსი": "новый",
    "old": "старый", "old building": "старый", "ძველი": "старый", "ძველი კორპუსი": "старый",
    "yes": "да", "y": "да", "yeah": "да", "კი": "да", "no": "нет", "n": "нет", "nope": "нет", "არა": "нет",
}


def translate(value: str) -> str:
    mapped = MAP.get(value.strip().casefold())
    if mapped:
        return mapped
    try:
        return GoogleTranslator(source="auto", target="ru").translate(value)
    except Exception:
        return value


async def translate_listing_fields(values):
    results = await asyncio.gather(*(asyncio.to_thread(translate, values[key]) for key in ("city", "district", "building", "pets")))
    for key, result in zip(("city", "district", "building", "pets"), results):
        values[key] = result
