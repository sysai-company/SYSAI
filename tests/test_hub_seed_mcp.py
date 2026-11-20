"""MCP-серверы хаба: каждый запускается, отвечает и объясняет, чего не хватает.

Агент на ПК зовёт эти инструменты через Hermes. Если сервер молчит, отвечает трейсбеком Python или
«Внутренняя ошибка: KeyError: 'path'», агент не может исправиться — он не знает, что передать. Проверка
поднимает каждый сервер так же, как синхронизатор (отдельный процесс, stdio, построчный JSON-RPC 2.0),
и требует: список инструментов с описаниями, ответ на вызов каждого, а на пустые аргументы — «нужны
параметры: path — …» вместо KeyError.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED = ROOT / "hub" / "seed"
PROTOCOL = "2025-06-18"
SERVERS = sorted(d.name for d in SEED.iterdir() if (d / "server.py").exists())


def _send(proc, msg):
    proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _read(proc, want_id):
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        got = json.loads(line)
        if got.get("id") == want_id:
            return got


def session(name):
    """Живой сервер: отдаёт (proc, call) и закрывается сам."""
    folder = SEED / name
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=str(folder), text=True, encoding="utf-8",
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1)
    _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                            "clientInfo": {"name": "tests", "version": "1"}}})
    assert _read(proc, 1).get("result", {}).get("serverInfo"), f"{name}: не поздоровался"
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    counter = {"id": 10}

    def call(tool, arguments):
        counter["id"] += 1
        _send(proc, {"jsonrpc": "2.0", "id": counter["id"], "method": "tools/call",
                     "params": {"name": tool, "arguments": arguments}})
        return _read(proc, counter["id"])

    return proc, call


def close(proc):
    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover — сервер не должен зависать
        proc.kill()


def tools_of(name):
    proc, call = session(name)
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}})
        return (_read(proc, 9) or {}).get("result", {}).get("tools") or []
    finally:
        close(proc)


def test_every_server_lists_its_tools_with_descriptions():
    """Инструмент без описания агент не вызовет: он выбирает по описанию, а не по имени."""
    assert SERVERS, "в хабе нет ни одного MCP-сервера"
    for name in SERVERS:
        tools = tools_of(name)
        assert tools, f"{name}: пустой список инструментов"
        for tool in tools:
            assert tool.get("description"), f"{name}/{tool.get('name')}: нет описания"
            schema = tool.get("inputSchema") or {}
            assert schema.get("type") == "object", f"{name}/{tool.get('name')}: аргументы не объект"
            assert isinstance(schema.get("properties"), dict), f"{name}/{tool.get('name')}: нет свойств"


def test_every_tool_answers_and_never_with_a_traceback():
    """Вызов с пустыми аргументами: обычный ответ или честная ошибка. Трейсбек — нет."""
    for name in SERVERS:
        proc, call = session(name)
        try:
            for tool in tools_of(name):
                answer = call(tool["name"], {})
                assert answer and "result" in answer, f"{name}/{tool['name']}: сервер не ответил"
                text = " ".join(c.get("text", "") for c in answer["result"].get("content", []))
                assert text.strip(), f"{name}/{tool['name']}: пустой ответ"
                for bad in ("Traceback", "KeyError", "TypeError", "AttributeError"):
                    assert bad not in text, f"{name}/{tool['name']}: {bad} вместо ответа — {text[:160]}"
        finally:
            close(proc)


def test_a_tool_asked_without_its_arguments_names_them():
    """«нужны параметры: path — Полный путь к файлу проекта» — по такому ответу агент исправляется сам."""
    checked = 0
    for name in SERVERS:
        needed = [t for t in tools_of(name) if (t.get("inputSchema") or {}).get("required")]
        if not needed:
            continue
        proc, call = session(name)
        try:
            for tool in needed:
                answer = call(tool["name"], {})
                text = " ".join(c.get("text", "") for c in answer["result"].get("content", []))
                assert answer["result"].get("isError") is True, f"{name}/{tool['name']}: пустые аргументы прошли"
                assert "нуж" in text.lower(), f"{name}/{tool['name']}: не сказал, чего не хватает — {text[:160]}"
                for field in (tool["inputSchema"].get("required") or []):
                    assert field in text, f"{name}/{tool['name']}: не назвал поле {field}"
                checked += 1
        finally:
            close(proc)
    assert checked >= 20, f"проверено всего {checked} инструментов с обязательными полями"
