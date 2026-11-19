"""Форматы, в которых работа уходит заказчику. Их два разных вида, и путать их нельзя:

* **ПЛК** — программа контроллера. Machine Expert (LD и ST), Haiwell Happy (только LD).
* **Панель** — экраны оператора. ONI Visual Studio (это русская сборка Flexem Studio), EasyBuilder (Weintek).

Один реестр, у каждого формата — свой адаптер. `read` и `write` — разные вещи: формат можно научиться
читать и ещё не уметь писать. «Готово» здесь значит «проверено на настоящем файле», а не «код написан».

У панелей разное разрешение экрана, и экран под 1024×768 на 800×480 не влезает. Поэтому разрешение — это
выбор инженера при создании проекта, а не константа: список лежит в `oniproj.RESOLUTIONS`.
"""
import oniproj

FORMATS = (
    {"id": "me", "title": "Machine Expert", "kind": "plc", "icon": "img/format-me.svg", "ext": ".project",
     "read": True, "write": True,
     "note": "настоящий .project: plc_project_build собирает его из папки ST и шаблона с тем же контроллером; "
             "языки — LD и ST"},
    {"id": "hawell", "title": "Haiwell Happy", "kind": "plc", "icon": "img/format-hawell.svg", "ext": ".gpc",
     "read": False, "write": False,
     "note": "проект .gpc с диска есть (600_S1_Благовещенск), но тело файла сжато своим способом: zlib-потоков "
             "нет, энтропия 7,06 бит/байт — структура ещё не снята. Язык у Haiwell только LD"},
    {"id": "oni", "title": "ONI", "kind": "hmi", "icon": "img/format-oni.svg", "ext": ".fsprj",
     "read": True, "write": False,
     "note": "экраны читаются: проект — папка с <имя>.fsprj и HMI/Frame/**/*.wcfg, окна и объекты это открытый "
             "XML (45 окон и 1206 объектов Достоево разобраны). Запись .wcfg ещё не сделана"},
    {"id": "easybuilder", "title": "EasyBuilder", "kind": "hmi", "icon": "img/format-me.svg", "ext": ".cmtp",
     "read": True, "write": True,
     "note": "экраны Weintek: ebpro-cmtp читает и правит проект .cmtp (окна, объекты, картинки)"},
)

KINDS = {"plc": "программа контроллера", "hmi": "экраны панели"}


class FormatError(Exception):
    pass


def listing(kind: str = "") -> list:
    """Все форматы: id, название, вид (ПЛК или панель), лого, что умеем, что нужно.

    По этому списку агент спрашивает «в каком формате»: у панелей рядом с вариантом ещё и разрешение.
    """
    out = []
    for f in FORMATS:
        if kind and f["kind"] != kind:
            continue
        one = dict(f)
        one["kind_title"] = KINDS.get(f["kind"], f["kind"])
        if f["kind"] == "hmi":
            one["resolutions"] = oniproj.resolutions()
        out.append(one)
    return out


def get(name: str) -> dict:
    key = str(name or "").strip().lower()
    for f in FORMATS:
        if key in (f["id"], f["title"].lower()):
            one = dict(f)
            one["kind_title"] = KINDS.get(f["kind"], f["kind"])
            if f["kind"] == "hmi":
                one["resolutions"] = oniproj.resolutions()
            return one
    raise FormatError(f"формат «{name}» неизвестен: бывают {', '.join(f['id'] for f in FORMATS)}")


def need(name: str) -> dict:
    """Что нужно, чтобы формат заработал: читаем ли, пишем ли и чем именно не готов."""
    f = get(name)
    if f["write"]:
        return {"format": f["id"], "kind": f["kind"], "read": True, "write": True, "note": f["note"]}
    return {"format": f["id"], "kind": f["kind"], "read": f["read"], "write": False, "note": f["note"],
            "blocked_by": ("структура файла ещё не снята: нужен разбор настоящего файла"
                           if not f["read"] else "чтение есть, запись ещё не сделана")}
