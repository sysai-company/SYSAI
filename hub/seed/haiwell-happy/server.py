"""MCP-сервер haiwell-happy: проект контроллера Haiwell Happy (`.gpc`, язык только LD).

Отдельный инструмент, а не часть `plc-kit`: Haiwell — своя среда со своим закрытым форматом, и путать её с
Schneider Machine Expert нельзя. Пока разобрано только то, что видно в заголовке; инструмент так и говорит.

Запускается синхронизатором на ПК (sysai-agent mcp haiwell-happy) и говорит по stdio построчным JSON-RPC 2.0.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hawell  # noqa: E402

PROTOCOL = "2025-06-18"
VERSION = "1.2.0"
PATH = {"type": "string", "description": r"Файл проекта Haiwell Happy (.gpc), например C:\Projects\line\plc\Line.gpc"}
SPEC = {"type": "string", "description": r"Файл спецификации проекта (_work\spec\project.spec.json) — его делает plc_spec"}
OUT = {"type": "string", "description": r"Папка проекта, куда положить hawell/, например C:\Projects\line"}
INSTRUCTIONS = (
    "Программа контроллера Haiwell Happy. Язык LD, и у среды есть язык инструкций (STL): LD ↔ STL по F7, "
    "в руководстве Haiwell у каждой инструкции стоит поддержка IL — поэтому программа отдаётся списком "
    "инструкций, это штатный язык среды, а не обходной путь. hawell_program показывает программу из "
    "спецификации, hawell_export пишет папку hawell/ (program.il, program.ld.txt, io.csv, comments.txt, README.txt), "
    "hawell_read читает её обратно. Сам .gpc не пишется и не читается: тело — закрытое сжатие вендора, его "
    "сохраняет только Haiwell Happy; hawell_info и hawell_check говорят об этом прямо. Программу Machine "
    "Expert / CODESYS делает plc-kit, экраны панели — oni-project и ebpro-cmtp."
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
    _ro("hawell_info", "Сведения о файле Haiwell Happy",
        "Что за файл .gpc: заголовок Haiwell, размер, энтропия тела, есть ли zlib-потоки. `decoded: false` "
        "значит, что схему LD из файла прочитать нельзя — это состояние формата (закрытое сжатие вендора), "
        "а не ошибка вызова. Программа для Haiwell делается из спецификации: hawell_export.",
        {"path": PATH}),
    _ro("hawell_check", "Проверка файла Haiwell Happy",
        "Подтверждает формат и говорит, чего в нём не хватает: заголовок, размер, состояние разбора. "
        "По строке на находку, без догадок о содержимом схемы.",
        {"path": PATH}),
    _ro("hawell_program", "Программа для Haiwell из спецификации (без записи)",
        "Собирает программу контроллера из спецификации проекта и показывает её, ничего не записывая: схемы "
        "списком инструкций (STL), таблицу сигналов и адресов X/Y/M/T/D, замечания. Годится, чтобы посмотреть "
        "до записи и согласовать с инженером.",
        {"spec_file": SPEC}, ("spec_file",)),
    _rw("hawell_export", "Записать программу для Haiwell Happy",
        "Пишет папку hawell/ рядом с проектом: program.il (список инструкций — штатный язык Haiwell Happy, "
        "LD ↔ STL по F7), program.ld.txt (та же схема лестницей), io.csv (сигналы и адреса), comments.txt "
        "(подписи для File → Import → Component comment table) и README.txt "
        "(что сделать в программе, по шагам). Сам .gpc не пишется: формат закрытый, его сохраняет Haiwell Happy.",
        {"spec_file": SPEC, "out_dir": OUT}, ("spec_file", "out_dir")),
    _ro("hawell_read", "Прочитать записанный экспорт",
        "Обратное чтение hawell/: адреса из io.csv, проверка, что адрес один на сигнал и что в program.il только "
        "инструкции Haiwell. Так видно, что записанное читается, а не только пишется.",
        {"out_dir": OUT}, ("out_dir",)),
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


def _spec(path):
    """Спецификация проекта: JSON, который делает plc_spec. Читаем здесь сами — инструмент должен работать и без
    второго сервера: файл спецификации самодостаточен."""
    import pathlib
    p = pathlib.Path(str(path))
    if not p.is_file():
        raise hawell.HawellError(f"нет файла спецификации: {p} (его делает plc_spec)")
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise hawell.HawellError(f"спецификация не читается как JSON: {exc}") from exc


def _missing(name, args):
    """Что не передали. Агент должен получить «нужен параметр: path», а не KeyError из глубины: по такому ответу
    он исправляется сам, по трейсбеку — нет. Схема инструмента — единственный источник правды о полях."""
    tool = next((t for t in TOOLS if t.get("name") == name), None)
    if not tool:
        return ""
    schema = tool.get("inputSchema") or {}
    need = [k for k in schema.get("required") or [] if args.get(k) in (None, "")]
    if not need:
        return ""
    props = schema.get("properties") or {}
    said = "; ".join(f"{k} — {props.get(k, {}).get('description', '')}".rstrip(" —") for k in need)
    return f"инструменту {name} нужны параметры: {said}"


def _call(name, args):
    said = _missing(name, args)
    if said:
        return _text(said, True)
    try:
        if name == "hawell_info":
            return _both(hawell.info(args["path"]))
        if name == "hawell_check":
            return _both(hawell.check(args["path"]))
        if name == "hawell_program":
            spec = _spec(args["spec_file"])
            prog = hawell.build(spec)
            return _both({"project": prog["project"], "rungs": prog["rungs"], "io": prog["io"],
                          "notes": prog["notes"], "il": hawell.il_text(prog)})
        if name == "hawell_export":
            return _both(hawell.export(args["spec_file"], args["out_dir"]))
        if name == "hawell_read":
            return _both(hawell.read_export(args["out_dir"]))
        return _text(f"неизвестный инструмент: {name}", True)
    except hawell.HawellError as exc:
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
                "serverInfo": {"name": "haiwell-happy", "title": "Haiwell Happy (.gpc, LD)", "version": VERSION},
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
        if method == "tools/call":
            import traceback
            where = traceback.extract_tb(exc.__traceback__)[-1:]
            at = f" ({os.path.basename(where[0].filename)}:{where[0].lineno})" if where else ""
            text = (f"Внутренняя ошибка инструмента {params.get('name')}: {type(exc).__name__}: {exc}{at}. Сервер "
                    "работает; проверьте аргументы и входные файлы и повторите.")
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
