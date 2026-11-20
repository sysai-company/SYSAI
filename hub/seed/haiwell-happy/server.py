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
VERSION = "1.0.0"
PATH = {"type": "string", "description": r"Файл проекта Haiwell Happy (.gpc), например C:\Projects\line\plc\Line.gpc"}
INSTRUCTIONS = (
    "Программа контроллера Haiwell Happy: язык только LD (релейные схемы), проект — один файл .gpc. Формат "
    "закрытый: читается заголовок, тело не разобрано, поэтому схемы LD из файла пока не прочитать и проект не "
    "записать. hawell_info говорит, что за файл и что в нём известно; hawell_check — что не так; hawell_export "
    "честно отказывает, а не пишет похожий файл. Программу Machine Expert / CODESYS делает plc-kit, экраны "
    "панели — oni-project и ebpro-cmtp."
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
    _ro("hawell_info", "Сведения о проекте Haiwell Happy",
        "Что за файл .gpc: заголовок Haiwell, размер, энтропия тела, есть ли zlib-потоки. `decoded: false` "
        "значит, что схему LD из файла прочитать нельзя — это состояние формата, а не ошибка вызова.",
        {"path": PATH}),
    _ro("hawell_check", "Проверка файла Haiwell Happy",
        "Подтверждает формат и говорит, чего в нём не хватает: заголовок, размер, состояние разбора. "
        "По строке на находку, без догадок о содержимом схемы.",
        {"path": PATH}),
    _rw("hawell_export", "Записать проект Haiwell Happy",
        "Пока невозможно: тело .gpc не разобрано. Возвращает причину и не пишет файл — вместо того чтобы "
        "записать что-то похожее и потерять работу инженера.",
        {"path": {"type": "string", "description": r"Куда записать .gpc, например C:\Projects\line\plc\Line.gpc"},
         "src_dir": {"type": "string", "description": "Папка с программой (LD)"}},
        ("path", "src_dir")),
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
        if name == "hawell_info":
            return _both(hawell.info(args["path"]))
        if name == "hawell_check":
            return _both(hawell.check(args["path"]))
        if name == "hawell_export":
            return _text(_json(hawell.export(args["path"], args["src_dir"])))
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
