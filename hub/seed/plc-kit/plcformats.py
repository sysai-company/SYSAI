"""Форматы, в которых программа ПЛК уходит заказчику: Machine Expert, ONI, Haiwell Happy.

Один реестр, у каждого формата — свой адаптер. Формат, который ещё не разобран, честно говорит об этом, а не
делает вид, что файл записан: «готово» здесь значит «проверено на настоящем файле», а не «код написан».
"""

FORMATS = (
    {"id": "me", "title": "Machine Expert", "icon": "img/format-me.svg", "ext": ".project", "ready": True,
     "note": "настоящий .project: plc_project_build собирает его из папки ST и шаблона с тем же контроллером"},
    {"id": "oni", "title": "ONI", "icon": "img/format-oni.svg", "ext": "", "ready": False,
     "note": "формат ONI ещё не разобран: нужен проект ONI с диска, чтобы снять структуру (T20)"},
    {"id": "hawell", "title": "Haiwell Happy", "icon": "img/format-hawell.svg", "ext": "", "ready": False,
     "note": "формат Haiwell Happy ещё не разобран: нужен проект с диска, чтобы снять структуру (T19)"},
)


class FormatError(Exception):
    pass


def listing() -> list:
    """Все форматы: id, название, лого, готов ли, что нужно. По этому агент спрашивает «в каком формате»."""
    return [dict(f) for f in FORMATS]


def get(name: str) -> dict:
    key = str(name or "").strip().lower()
    for f in FORMATS:
        if key in (f["id"], f["title"].lower()):
            return dict(f)
    raise FormatError(f"формат «{name}» неизвестен: бывают {', '.join(f['id'] for f in FORMATS)}")


def need(name: str) -> dict:
    """Что нужно, чтобы формат заработал: готов ли и чем именно не готов."""
    f = get(name)
    if f["ready"]:
        return {"format": f["id"], "ready": True, "note": f["note"]}
    return {"format": f["id"], "ready": False, "note": f["note"],
            "blocked_by": "нужен настоящий файл этого формата с диска: без него структура не снимается"}
