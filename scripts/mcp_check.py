"""Проверка MCP-серверов хаба: каждый запускается, отдаёт список инструментов и отвечает на вызов.

Зачем: на ПК инструмент вызывает агент, и «ошибка» там означает не «нет пути», а непонятный текст или
молчание сервера. Здесь каждый сервер запускается как на ПК — отдельным процессом, по stdio, построчным
JSON-RPC 2.0, — и по каждому инструменту проверяется: ответ пришёл, это result, а если ошибка (не хватает
параметра, нет папки) — она написана человеку, а не трейсбек Python.

  python scripts/mcp_check.py            все серверы
  python scripts/mcp_check.py plc-kit    один
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED = ROOT / "hub" / "seed"
PROTOCOL = "2025-06-18"


def _send(proc, msg):
    proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _read(proc, want_id):
    """Ждёт ответ с нужным id; уведомления и чужие ответы пропускает."""
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            got = json.loads(line)
        except ValueError:
            return {"error": {"message": f"не JSON-RPC: {line[:200]}"}}
        if got.get("id") == want_id:
            return got


def check(name: str) -> dict:
    """Один сервер: список инструментов и ответ на вызов каждого без аргументов."""
    folder = SEED / name
    server = folder / "server.py"
    if not server.exists():
        return {"name": name, "ok": False, "problem": "нет server.py"}
    proc = subprocess.Popen([sys.executable, str(server)], cwd=str(folder), text=True, encoding="utf-8",
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1)
    out = {"name": name, "ok": True, "tools": [], "problems": []}
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                                "clientInfo": {"name": "mcp_check", "version": "1"}}})
        hello = _read(proc, 1)
        if not hello or "result" not in hello:
            out["ok"] = False
            out["problems"].append(f"initialize: {hello}")
            return out
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = _read(proc, 2)
        tools = (listed or {}).get("result", {}).get("tools") if listed else None
        if not tools:
            out["ok"] = False
            out["problems"].append(f"tools/list: {listed}")
            return out
        out["tools"] = [t["name"] for t in tools]
        for i, tool in enumerate(tools, start=200):
            schema = tool.get("inputSchema") or {}
            if schema.get("type") != "object" or not isinstance(schema.get("properties", {}), dict):
                out["problems"].append(f"{tool['name']}: схема аргументов не объект")
            if not tool.get("description"):
                out["problems"].append(f"{tool['name']}: нет описания — агент не поймёт, когда звать")
            _send(proc, {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                         "params": {"name": tool["name"], "arguments": {}}})
            answer = _read(proc, i)
            if not answer:
                out["ok"] = False
                out["problems"].append(f"{tool['name']}: сервер замолчал (упал?)")
                break
            if "result" not in answer:
                out["problems"].append(f"{tool['name']}: protocol error {answer.get('error', {}).get('message')}")
                continue
            text = " ".join(c.get("text", "") for c in answer["result"].get("content", []) if isinstance(c, dict))
            if "Traceback" in text or "KeyError" in text or "TypeError" in text:
                out["problems"].append(f"{tool['name']}: трейсбек вместо ответа — {text[:160]}")
            elif not text.strip():
                out["problems"].append(f"{tool['name']}: пустой ответ без объяснения")
            elif not answer["result"].get("isError") and tool["name"].endswith("_check") is False:
                pass  # обычный ответ на пустые аргументы — тоже нормально
    except Exception as exc:  # noqa: BLE001 — проверка не должна падать вместе с сервером
        out["ok"] = False
        out["problems"].append(f"сломался сам: {exc}")
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        err = (proc.stderr.read() or "").strip()
        if err and out["ok"]:
            out["problems"].append(f"писал в stderr: {err.splitlines()[-1][:160]}")
    return out


def main():
    only = sys.argv[1:]
    names = sorted(d.name for d in SEED.iterdir() if (d / "server.py").exists())
    if only:
        names = [n for n in names if n in only]
    bad = 0
    total = 0
    for name in names:
        got = check(name)
        total += len(got["tools"])
        mark = "ok  " if got["ok"] and not got["problems"] else "БЕДА"
        print(f"{mark} {name}: {len(got['tools'])} инструментов")
        for p in got["problems"]:
            print(f"      · {p}")
        if not got["ok"] or got["problems"]:
            bad += 1
    print(f"\nсерверов: {len(names)}, инструментов: {total}, с замечаниями: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
