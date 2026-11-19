"""«sysai-agent mcp <name>»: a hub MCP server started for Hermes inside a guard. The guard checks the signed rules
(access.json, the key pinned at connection) itself — whatever the harness is told: the server must be allowed,
tools/list shows only the allowed tools, tools/call of others is refused, paths must be in the allowed folders,
commands must not match the forbidden patterns, sites must be allowed. The rules are reloaded when the file changes."""
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import fsutil, paths, rules as R, signing

PATH_KEYS = ("path", "file", "dir", "folder", "cwd", "directory")
COMMAND_KEYS = ("command", "cmd", "commandline", "command_line", "shell", "powershell")
WAIT_TRIES, WAIT_STEP = 16, 0.5  # up to eight seconds for the synchronizer to finish what it is doing
PLC_KEYS = {"plc", "plcs", "plc_host", "plc_hosts", "plc_network"}  # arguments that name a controller or its network
WRITE_TOKENS = {"write", "save", "delete", "remove", "move", "rename", "create", "put", "edit", "update", "export",
                "out", "output", "dest", "destination", "target"}


def _tokens(name: str) -> set:
    """«saveProject», «out_dir», «files-write» → {"save", "project"}, {"out", "dir"}, {"files", "write"}."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name or "")
    return {t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t}


def _path_key(key: str) -> bool:
    low = (key or "").lower()
    return any(low.startswith(w) or low.endswith(w) for w in PATH_KEYS)


def _looks_like_path(value: str, key: str) -> bool:
    v = value.strip()
    if len(v) < 2:
        return False
    if v[1:3] in (":\\", ":/") or v.startswith(("\\\\", "//", "/", "~")) or "\\" in v:
        return True
    return ("/" in v or v.startswith(".")) and _path_key(key)


class Guard:
    def __init__(self, home: Path, name: str, access_file: Path):
        self.home, self.name, self.file = Path(home), name, Path(access_file)
        self.mtime, self.rules = None, None
        self.agent = fsutil.read_json(self.home / "agent.json", {}) or {}

    def load(self) -> dict | None:
        """The rules, reloaded when access.json changed; None — not trusted (no file, broken, another key)."""
        try:
            mtime = self.file.stat().st_mtime
        except OSError:
            self.rules = None
            return None
        if mtime != self.mtime:
            self.mtime = mtime
            signed = fsutil.read_json(self.file, None)
            ok = self.agent.get("public_key") and signing.verify(signed, self.agent["public_key"], self.agent.get("key_id", ""))
            try:
                self.rules = signed["doc"]["rules"] if ok else None
            except (KeyError, TypeError):  # a signed doc without «rules»: not trusted, but the wrapper must not crash
                self.rules = None
        return self.rules

    def server_allowed(self) -> bool:
        rules = self.load()
        return bool(rules) and self.name in (rules.get("mcp") or {})

    def check_call(self, tool: str, args) -> str:
        """Why the call is refused ("" — allowed)."""
        rules = self.load()
        if not rules:
            return "нет подписанных доступов SYSAI (access.json) — синхронизатор ещё не получил их или подпись не сходится"
        if self.name not in (rules.get("mcp") or {}):
            return f"MCP-сервер {self.name} агенту не разрешён"
        if not R.tool_allowed(rules, self.name, tool):
            return f"инструмент {tool} сервера {self.name} агенту не разрешён"
        writes = bool(_tokens(tool) & WRITE_TOKENS)
        for key, value in _strings(args):
            if value.startswith(("http://", "https://")):
                if not R.site_allowed(rules, value):
                    return f"сайт {value[:80]} не в разрешённых"
                continue
            low = key.lower()
            if low in PLC_KEYS or value.lower().startswith("opc.tcp://"):  # a controller is reached only when named in
                if not R.plc_allowed(rules, value):                         # «Доступы → Сеть контроллеров»
                    return (f"контроллер {value[:80]} агенту не открыт: адрес добавляют в SYSAI → Агенты → Доступы → "
                            "«Сеть контроллеров»")
                continue
            if low in COMMAND_KEYS or low.endswith("command"):
                pattern = R.command_denied(rules, value)
                if pattern:
                    return "команды агенту запрещены" if pattern == "*" else f"команда попадает под запрет «{pattern}»"
                continue
            if _looks_like_path(value, key):
                write = writes or bool(_tokens(key) & WRITE_TOKENS)
                if not R.path_allowed(rules, value, write=write):
                    return f"папка {value[:120]} не разрешена агенту" + (" на запись" if write else "")
        return ""


def _strings(obj, key: str = ""):
    """(key, text) of every string inside the arguments; the key is the nearest name above."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, key)
    elif isinstance(obj, str):
        yield key, obj


def command(spec: dict, folder: Path, python: str = "") -> list:
    """The tool's run line as arguments: «python …» starts with its own environment or the synchronizer's Python."""
    run = (spec or {}).get("run") or ""
    args = shlex.split(run, posix=not paths.WINDOWS)
    args = [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in args]
    if not args:
        raise ValueError("у инструмента нет команды запуска (run)")
    if args[0].lower() in ("python", "python3", "py", "python.exe", "pythonw"):
        args[0] = python or sys.executable
        # the script by its full path: the server is started outside its folder (see serve), so that the folder is
        # not held and the synchronizer can swap it for a new version while the agent works
        for i in range(1, len(args)):
            if not args[i].startswith("-"):
                if not os.path.isabs(args[i]) and (folder / args[i]).exists():
                    args[i] = str(folder / args[i])
                break
    elif not os.path.isabs(args[0]) and (folder / args[0]).exists():
        args[0] = str(folder / args[0])
    return args


def _error(msg_id, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32001, "message": f"SYSAI: {text}"}}


# Hermes counts every failed call of a server — a JSON-RPC error and a result with isError alike — and after three in a
# row it stops calling the WHOLE server for a minute («MCP server … is unreachable / rejected the last 3 calls»). A
# refused path, an incomplete specification or a wrong argument is not a broken server, yet three of them in a row
# made every tool of plc-kit «unavailable» for the agent, plc_stage_update included: the agent told the engineer that
# the server stopped answering and gave up. So a call that failed is answered as a result whose text says so; only the
# same call failing the same way again and again (a loop) keeps isError and lets Hermes stop it.
REPEATS = 3
RESTARTS, RESTART_WINDOW = 3, 60  # a tool that died is started again, but not in an endless loop
REINIT = "sysai-reinit-"


def _failed_text(name: str, text: str, tool: str) -> str:
    return (f"ОШИБКА ({name}/{tool}): {text}\n"
            f"[SYSAI: сервер {name} работает и ответил — это ответ на ЭТОТ вызов, а не обрыв связи. Исправьте аргументы "
            "или данные по тексту ошибки и вызовите снова; другие инструменты сервера доступны.]")


def _failed(msg_id, name: str, tool: str, text: str, is_error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": _failed_text(name, text, tool)}],
              "structuredContent": {"ok": False, "error": text}}
    if is_error:
        result["isError"] = True
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _call_key(tool: str, args) -> str:
    try:
        return tool + "\0" + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return tool + "\0" + repr(args)


class Repeats:
    """How many times in a row a call with exactly these arguments failed — a loop is what Hermes may stop."""
    def __init__(self):
        self.last, self.count = None, 0

    def failed(self, key: str) -> bool:
        """Count a failure; True — the same call failed REPEATS times in a row."""
        self.count = self.count + 1 if key == self.last else 1
        self.last = key
        return self.count >= REPEATS

    def ok(self, key: str) -> None:
        if key == self.last:
            self.last, self.count = None, 0


def _result_text(result: dict) -> str:
    parts = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts) or "инструмент сообщил об ошибке без текста"


def serve(name: str, home: Path | None = None, stdin=None, stdout=None) -> int:
    home = Path(home or paths.home())
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    access_file = Path(os.environ.get("SYSAI_ACCESS_FILE") or home / "access.json")
    guard = Guard(home, name, access_file)
    folder = Path(os.environ.get("SYSAI_TOOL_DIR") or home / "tools" / name)
    # The synchronizer may be in the middle of its work at this very moment: writing state.json or access.json anew,
    # swapping the folder of the tool for a new version. Hermes starts a server once and marks it «not connected» for
    # the whole session when it exits — so what is missing is waited for a little before giving up.
    tool = {}
    for attempt in range(WAIT_TRIES):
        state = fsutil.read_json(home / "state.json", {}) or {}
        tool = (state.get("tools") or {}).get(name) or {}
        if guard.server_allowed() and tool and folder.is_dir():
            break
        guard.mtime = None  # read access.json again next time
        if attempt + 1 < WAIT_TRIES:
            time.sleep(WAIT_STEP)
    if not guard.server_allowed():
        sys.stderr.write(f"SYSAI: MCP-сервер {name} агенту не разрешён (или нет подписанных доступов)\n")
        return 2
    if not tool or not folder.is_dir():
        sys.stderr.write(f"SYSAI: инструмента {name} нет на компьютере — синхронизатор поставит его из SYSAI_Hub\n")
        return 2
    try:
        args = command(tool.get("spec") or {}, folder, tool.get("python") or "")
    except ValueError as exc:
        sys.stderr.write(f"SYSAI: {exc}\n")
        return 2
    env = {**os.environ, "SYSAI_HOME": str(home), "SYSAI_TOOL_DIR": str(folder)}
    lock = threading.Lock()
    lists = set()  # ids of tools/list requests: their answers are filtered
    calls = {}     # id of a tools/call -> [tool name, key of the call, the process it was sent to]
    repeats = Repeats()
    hello = {}     # the harness's «initialize» and «notifications/initialized»: replayed to a restarted tool
    box = {"proc": None, "restarts": []}

    def refuse(msg_id, tool: str, args, text: str) -> None:
        say(_failed(msg_id, name, tool, text, repeats.failed(_call_key(tool, args))))

    def say(obj) -> None:
        with lock:
            stdout.write(json.dumps(obj).encode("ascii") + b"\n")  # ASCII only: Hermes on Windows reads it with a locale code page that has no arrows
            stdout.flush()

    def upstream(proc) -> None:
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                # a print or a traceback of the tool is not JSON-RPC: dropped, not forwarded raw — raw bytes of another
                # code page would break Hermes' reader on Windows exactly like the arrow once did
                continue
            if isinstance(msg, dict) and str(msg.get("id") or "").startswith(REINIT):
                continue  # the answer to the replayed handshake of a restarted tool: Hermes did not ask for it
            call = calls.pop(msg.get("id"), None) if isinstance(msg, dict) and msg.get("id") is not None else None
            if call is not None:
                tool, key = call[0], call[1]
                if isinstance(msg.get("error"), dict) or "result" not in msg:  # the tool raised: an answer, not a strike
                    err = msg.get("error") if isinstance(msg.get("error"), dict) else {}
                    say(_failed(msg["id"], name, tool, str(err.get("message") or "ошибка инструмента"), repeats.failed(key)))
                    continue
                result = msg.get("result")
                if isinstance(result, dict) and result.get("isError"):
                    again = repeats.failed(key)
                    blocks = [b for b in (result.get("content") or []) if not (isinstance(b, dict) and b.get("type") == "text")]
                    result["content"] = [{"type": "text", "text": _failed_text(name, _result_text(result), tool)}] + blocks
                    if not again:
                        result.pop("isError", None)
                else:
                    repeats.ok(key)
                say(msg)
                continue
            if isinstance(msg, dict) and msg.get("id") in lists and isinstance(msg.get("result"), dict):
                lists.discard(msg.get("id"))
                rules = guard.load() or {}
                tools = msg["result"].get("tools")
                if isinstance(tools, list):
                    msg["result"]["tools"] = [t for t in tools if isinstance(t, dict) and
                                              R.tool_allowed(rules, name, str(t.get("name") or ""))]
            say(msg)
        # the tool exited: the calls it was working on are answered now, not when Hermes' timeout runs out
        orphans(proc)

    def orphans(proc) -> None:
        """Answer the calls a dead process took and never answered."""
        code = proc.wait()
        if box["proc"] is None:
            return
        for msg_id, call in list(calls.items()):
            if call[2] is proc and calls.pop(msg_id, None) is not None:
                say(_failed(msg_id, name, call[0], f"инструмент {name} завершился во время вызова (код {code}); SYSAI "
                                                   "перезапустил его — повторите вызов", repeats.failed(call[1])))

    def spawn():
        # not in the folder of the tool: a program working in a folder keeps Windows from renaming it
        proc = subprocess.Popen(args, cwd=str(home), stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
                                creationflags=0x08000000 if paths.WINDOWS else 0)
        box["proc"] = proc
        box["reader"] = threading.Thread(target=upstream, args=(proc,), daemon=True)
        box["reader"].start()
        return proc

    def send(proc, out) -> None:
        proc.stdin.write(json.dumps(out, ensure_ascii=False).encode("utf-8") + b"\n")
        proc.stdin.flush()

    def restart() -> str:
        """Start the tool again and replay the handshake; "" — it runs, otherwise why not."""
        now = time.monotonic()
        box["restarts"] = [t for t in box["restarts"] if now - t < RESTART_WINDOW]
        if len(box["restarts"]) >= RESTARTS:
            return (f"инструмент {name} падает снова и снова ({RESTARTS} перезапуска за {RESTART_WINDOW} с) — "
                    "посмотрите его журнал или переустановите его в SYSAI_Hub")
        box["restarts"].append(now)
        orphans(box["proc"])
        try:
            proc = spawn()
            if hello.get("initialize"):
                send(proc, {**hello["initialize"], "id": f"{REINIT}{len(box['restarts'])}"})
            if hello.get("initialized"):
                send(proc, hello["initialized"])
        except (OSError, ValueError) as exc:
            return f"инструмент {name} не запускается: {exc}"
        return ""

    spawn()
    try:
        for line in stdin:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            forward = []
            for item in msg if isinstance(msg, list) else [msg]:
                if not isinstance(item, dict):
                    continue
                method = item.get("method")
                if method == "initialize" and "id" in item:
                    hello["initialize"] = item
                if method == "notifications/initialized":
                    hello["initialized"] = item
                if method == "tools/list" and "id" in item:
                    lists.add(item["id"])
                if method == "tools/call":
                    params = item.get("params") if isinstance(item.get("params"), dict) else {}
                    tool, targs = str(params.get("name") or ""), params.get("arguments") or {}
                    try:
                        why = guard.check_call(tool, targs)
                    except Exception as exc:  # noqa: BLE001 — a broken rule answers with an error, it must not drop the connection
                        why = f"внутренняя ошибка проверки доступов SYSAI: {exc}"
                    if why:
                        if "id" in item:
                            refuse(item["id"], tool, targs, "доступ SYSAI: " + why)
                        continue
                    if "id" in item:
                        calls[item["id"]] = [tool, _call_key(tool, targs), None]
                forward.append(item)
            if not forward:
                continue
            out = forward if isinstance(msg, list) else forward[0]
            why = ""
            for attempt in range(2):
                # the tool exited (a crash, an update of its folder): started again instead of leaving Hermes a dead
                # server for the whole session — that was «the tool is available… and then it is not»
                if box["proc"].poll() is not None:
                    why = restart()
                    if why:
                        break
                try:
                    for item in forward:
                        if item.get("id") in calls:
                            calls[item["id"]][2] = box["proc"]
                    send(box["proc"], out)
                    why = ""
                    break
                except (BrokenPipeError, OSError):
                    why = f"инструмент {name} закрыл соединение"
                    try:
                        box["proc"].wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        box["proc"].kill()
            if why:
                for item in forward:
                    if isinstance(item, dict) and "id" in item:
                        call = calls.pop(item["id"], None)
                        if call:
                            say(_failed(item["id"], name, call[0], why, repeats.failed(call[1])))
                        else:
                            say(_error(item["id"], why))
    except (BrokenPipeError, OSError):
        pass
    finally:
        proc = box["proc"]
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        box["reader"].join(timeout=5)  # what the tool still says (or the calls it dropped) is answered before we go
        box["proc"] = None
    return proc.returncode or 0
