"""MCP-сервер oni-project: экраны панели оператора ONI Visual Studio (русская сборка Flexem Studio).

ONI — это экраны, а не программа ПЛК: здесь окна, объекты, адреса, которые они читают, и сборка экранов из
спецификации объекта. Программа контроллера — не этот инструмент (plc-kit, machine-expert, haiwell-happy).

Запускается синхронизатором на ПК (sysai-agent mcp oni-project) и говорит по stdio построчным JSON-RPC 2.0.
Доступы (папки на чтение/запись) проверяет сам SYSAI по подписанным правилам до вызова — здесь только файлы.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oniproj  # noqa: E402
import oniscreens  # noqa: E402

PROTOCOL = "2025-06-18"
VERSION = "1.0.0"
PATH = {"type": "string", "description": r"Папка проекта экранов ONI (в ней <имя>.fsprj), например C:\Projects\line\hmi"}
WINDOW = {"type": "string", "description": "GUID окна, имя файла .wcfg или имя окна"}
INSTRUCTIONS = (
    "Экраны панели оператора ONI (ONI Visual Studio — русская сборка Flexem Studio). Это не программа ПЛК: "
    "здесь окна и то, что на них нарисовано. Читать: oni_windows → oni_objects (что на окне, подпись, "
    "координаты, к чему привязано) → oni_addresses (какие адреса ПЛК читают и пишут экраны); что не так — "
    "oni_check. Разрешение панели — oni_panel: панели разные, экран под 1024×768 на 800×480 не влезает, поэтому "
    "это выбор инженера. Создавать: oni_new_project (пустой проект под выбранное разрешение) или oni_screens — "
    "экраны из спецификации объекта: мнемосхема с механизмами, экран на каждый механизм и карта Modbus-адресов, "
    "которую надо задать в контроллере. Правки — oni_write_window, он же читает окно обратно и показывает, что "
    "получилось. Чего инструмент не гарантирует: что ONI Visual Studio откроет проект без замечаний — программы "
    "здесь нет, проверить нечем; проверяется разбором обратно."
)


def _ro(name, title, description, props, required=("path",)):
    return {"name": name, "title": title, "description": description,
            "inputSchema": {"type": "object", "properties": props, "required": list(required),
                            "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "openWorldHint": False}}


def _rw(name, title, description, props, required):
    t = _ro(name, title, description, props, required)
    t["annotations"] = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
    return t


TOOLS = [
    _ro("oni_windows", "Окна проекта ONI",
        "Экраны проекта ONI Visual Studio (панель оператора, не ПЛК). path — папка проекта (в ней <имя>.fsprj) "
        "или сам .fsprj. В ответе: имя, версия, программа, ПЛК из ConnectInfo.cfg, стартовое окно и список окон "
        "(id, имя, папка, число объектов, размер). Имя окна — первый текст на нём: своих имён у окон нет, "
        "личность — GUID.",
        {"path": PATH}),
    _ro("oni_objects", "Объекты окна ONI",
        "Что нарисовано на окне: тип (клавиша, число, текст, картинка, линия…), подпись, координаты и размер, "
        "привязка к ПЛК (адрес, устройство, тип) и есть ли картинка. window — GUID окна, имя файла или имя окна.",
        {"path": PATH, "window": WINDOW}),
    _ro("oni_addresses", "Адреса ПЛК на экранах ONI",
        "Какие адреса читают и пишут экраны: адрес, тип (Word/Bit), сколько объектов его используют и на каких "
        "окнах. Адрес берётся из Abbreviation, а если её нет — собирается из RegisterId и MainAddress "
        "(257 → SRB, 65791 → LW, 65792 → SRW, 65788 → SRWR, 6 → 4X_bit, 65540 → 4X).",
        {"path": PATH}),
    _ro("oni_check", "Проверка экранов ONI",
        "Что не так с экранами, по строке на окно: объект целиком за окном (ошибка), объект выходит за окно "
        "больше чем на 20 точек, клавиша или число ни к чему не привязаны, в проекте не описан ПЛК. Клавиша "
        "перехода на другое окно адреса не читает и мёртвой не считается.",
        {"path": PATH}),
    _ro("oni_panel", "Разрешение панели ONI",
        "Под какое разрешение нарисованы экраны (самое большое окно проекта) и из чего выбирать при создании "
        "нового: 800×480, 1024×600, 1024×768, 1280×800, 1366×768, 1920×1080, 640×480, 480×272. Панели разные — "
        "экран под 1024×768 на 800×480 не влезает, поэтому разрешение это выбор инженера, а не константа.",
        {"path": PATH}),
    _rw("oni_new_project", "Новый проект экранов ONI",
        "Создать проект экранов под выбранное разрешение: папка с <имя>.fsprj, одно окно нужного размера, "
        "описание ПЛК (Modbus TCP) и стартовое окно. Разрешение — выбор инженера, а не константа (список — "
        "oni_panel). Структура снята с настоящего проекта Достоево. Чего не гарантирует: что ONI Visual Studio "
        "откроет файл без замечаний — программы здесь нет, проверить нечем.",
        {"path": {"type": "string", "description": r"Папка, где создать проект, например C:\Projects\line\hmi"},
         "name": {"type": "string", "description": "Имя проекта: папка и <имя>.fsprj"},
         "resolution": {"type": "string", "description": "Разрешение панели: 800x480, 1024x768, 1920x1080…"},
         "device": {"type": "string", "description": "Протокол ПЛК, по умолчанию Modbus_TCP"},
         "title": {"type": "string", "description": "Заголовок на первом экране"}},
        ("path", "name", "resolution")),
    _rw("oni_write_window", "Записать окно ONI обратно",
        "Записать окно проекта ONI и прочитать его снова — в ответе не «задумано», а что получилось: объекты, "
        "размер, совпало ли разобранное окно с исходным. Байт-в-байт не совпадёт (ElementTree поднимает "
        "неймспейсы к корню), но для ONI это одно и то же — сверяется разобранное окно. Проверено на всех 45 "
        "окнах Достоево: расхождений 0.",
        {"path": PATH, "window": WINDOW,
         "out_file": {"type": "string", "description": "Куда записать; пусто — в тот же файл"}},
        ("path", "window")),
    _rw("oni_screens", "Экраны ONI из спецификации",
        "Нарисовать экраны из спецификации объекта: главный экран с плитками механизмов (лампа работы, лампа "
        "аварии, переход внутрь), экран на каждый механизм (сигналы лампами, задание числом, пуск и стоп) и "
        "карту Modbus-адресов. Адреса раздаёт этот вызов — ту же карту надо задать в контроллере (Modbus "
        "mapping), иначе панель будет читать пустоту; в ответе `map` — что за сигнал, бит или слово, регистр. "
        "Объектные сигналы (аварийный стоп, режим) стоят отдельной строкой сверху, а не внутри чьей-то плитки. "
        "Сигнал без канала в спецификации не выкидывается: он на экране есть, а в `unwired` сказано, что читать "
        "ему нечего. Разрешение — выбор инженера (`oni_panel`).",
        {"path": {"type": "string", "description": r"Куда собрать проект экранов, например C:\Projects\line\hmi"},
         "spec": {"type": "string", "description": r"Файл спецификации project.spec.json (plc_spec)"},
         "resolution": {"type": "string", "description": "Разрешение панели: 800x480, 1024x768, 1920x1080…"},
         "device": {"type": "string", "description": "Протокол ПЛК, по умолчанию Modbus_TCP"},
         "title": {"type": "string", "description": "Заголовок главного экрана"}},
        ("path", "spec")),
]


def _text(s, is_error=False, data=None):
    r = {"content": [{"type": "text", "text": s}]}
    if is_error:
        r["isError"] = True
    if data is not None:
        r["structuredContent"] = data
    return r


def _json(obj):
    return json.dumps(obj, ensure_ascii=False)


def _both(obj):
    """Текст для человека и структура для программы — одно и то же значение, два вида."""
    return _text(_json(obj), data=obj)


def _call(name, args):
    try:
        if name == "oni_screens":
            return _both(oniscreens.screens(args["spec"], args["path"],
                                            args.get("resolution") or "1024x768",
                                            args.get("device") or "Modbus_TCP",
                                            args.get("title") or ""))
        if name == "oni_new_project":
            return _both(oniproj.new_project(args["path"], args["name"], args["resolution"],
                                             args.get("device") or "Modbus_TCP",
                                             args.get("title") or ""))
        if name == "oni_write_window":
            p = oniproj.load(args["path"])
            w = p.window(args["window"])
            if w is None:
                return _text(f"нет окна «{args['window']}»", True)
            return _both(oniproj.write_window(w, args.get("out_file") or None))
        if name == "oni_windows":
            return _both(oniproj.windows(args["path"]))
        if name == "oni_objects":
            return _both(oniproj.objects(args["path"], args["window"]))
        if name == "oni_addresses":
            return _both(oniproj.addresses(args["path"]))
        if name == "oni_check":
            return _both(oniproj.check(args["path"]))
        if name == "oni_panel":
            return _both(oniproj.panel(args["path"]))
        return _text(f"неизвестный инструмент: {name}", True)
    except (oniproj.OniError, oniscreens.ScreenError) as exc:
        return _text(str(exc), True)


def _out(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _handle(msg):
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        return
    mid, method = msg.get("id"), msg["method"]
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if mid is None:
        return  # notification
    try:
        if method == "initialize":
            _out({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": str(params.get("protocolVersion") or PROTOCOL),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "oni-project", "title": "Экраны ONI (панель оператора)", "version": VERSION},
                "instructions": INSTRUCTIONS}})
        elif method == "ping":
            _out({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif method == "tools/list":
            _out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            _out({"jsonrpc": "2.0", "id": mid,
                  "result": _call(str(params.get("name") or ""), params.get("arguments") or {})})
        else:
            _out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}})
    except Exception as exc:  # noqa: BLE001 — одна ошибка не должна ронять сервер
        if method == "tools/call":  # a crash of one tool is its answer, not a dead server
            import traceback
            where = traceback.extract_tb(exc.__traceback__)[-1:]
            at = f" ({os.path.basename(where[0].filename)}:{where[0].lineno})" if where else ""
            text = (f"Внутренняя ошибка инструмента {params.get('name')}: {type(exc).__name__}: {exc}{at}. Сервер "
                    "работает; проверьте аргументы и входные файлы (формат, обязательные поля) и повторите — если "
                    "ошибка та же, сообщите инженеру этот текст.")
            _out({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": True}})
        else:
            _out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(exc)}})


def main():
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        for item in (msg if isinstance(msg, list) else [msg]):
            _handle(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
