"""Connection, one synchronization and the pulse; the loop of «sysai-agent run»."""
import datetime as dt
import hashlib
import logging
import logging.handlers
import os
import platform
import shutil
import sys
import time
from pathlib import Path

from . import __version__, desktop, fsutil, hermes, hermes_patch, hubsync, live as livechan, paths, secret, signing, update
from .client import ApiError, Client

log = logging.getLogger("sysai_agent")
EVERY = 300          # seconds between pulses
FULL_EVERY = 3600    # a full synchronization at least this often, even when nothing changed on the server


class SyncError(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def setup_logging(home: Path, console: bool = True) -> None:
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    (Path(home) / "logs").mkdir(parents=True, exist_ok=True)
    file = logging.handlers.RotatingFileHandler(Path(home) / "logs" / "sync.log", maxBytes=1_000_000, backupCount=3,
                                                encoding="utf-8")
    file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(file)
    if console and sys.stderr is not None:
        out = logging.StreamHandler()
        out.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(out)


def load_agent(home: Path) -> dict:
    cfg = fsutil.read_json(Path(home) / "agent.json", None)
    if not isinstance(cfg, dict) or not cfg.get("agent") or not cfg.get("server") or not cfg.get("public_key"):
        raise SyncError("Компьютер не подключён: получите код на странице агента в SYSAI и выполните "
                        "sysai-agent connect --server <адрес SYSAI> --code <код>")
    return cfg


_hermes_version = {"at": 0.0, "value": ""}


def versions(home: Path | None = None) -> dict:
    """Shown on the agent's page; Hermes is asked once an hour."""
    if time.time() - _hermes_version["at"] > 3600:
        _hermes_version.update(at=time.time(), value=hermes.version())
    out = {"sysai-agent": __version__, "python": platform.python_version()}
    if _hermes_version["value"]:
        out["hermes"] = _hermes_version["value"]
    window = desktop.installed(home) if home else {}
    if window.get("version"):
        out["desktop"] = window["version"]
    return out


def launcher() -> str:
    """The full path of «sysai-agent», for the MCP servers in the Hermes configuration."""
    found = shutil.which("sysai-agent")
    if found:
        return found
    here = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if here and here.stem.lower().startswith("sysai-agent") and here.exists():
        return str(here.with_name("sysai-agent" + here.suffix))
    return ""


def connect(server: str, code: str, home: Path | None = None, transport=None, profile: str = "",
            hermes_home: str = "") -> dict:
    """Trades the one-time code for the agent's token; pins the key the rules are signed with."""
    home = Path(home or paths.home())
    server = (server or "").strip().rstrip("/")
    if not server.startswith(("https://", "http://")):
        raise SyncError("Адрес SYSAI — вида https://sysai.example.ru")
    if not (code or "").strip():
        raise SyncError("Нет кода подключения: получите его на странице агента в SYSAI")
    client = Client(server, transport=transport)
    try:
        answer = client.json("POST", "/agents/api/connect", {"code": code.strip(), "host": platform.node(),
                                                             "harness": "hermes", "versions": versions()})
    except ApiError as exc:
        raise SyncError(str(exc)) from exc
    key = answer.get("public_key") or {}
    if not answer.get("agent") or not answer.get("token") or not key.get("key"):
        raise SyncError("SYSAI ответил не так, как ждали: обновите синхронизатор (запустите установщик снова)")
    home.mkdir(parents=True, exist_ok=True)
    old = fsutil.read_json(home / "agent.json", {}) or {}
    same = old.get("agent") == answer["agent"]
    cfg = {"agent": answer["agent"], "server": server, "public_key": key["key"], "key_id": key.get("key_id", ""),
           "profile": profile or (old.get("profile") if same else "") or answer["agent"],
           "hermes_home": hermes_home or (old.get("hermes_home") if same else "") or "",
           "host": platform.node(), "connected_at": now()}
    where = secret.save(home, cfg["agent"], answer["token"])
    fsutil.write_json(home / "agent.json", cfg)
    if not same:
        fsutil.write_json(home / "state.json", {})
    log.info("Подключено: агент %s, сервер %s (токен: %s)", cfg["agent"], server,
             "хранилище Windows" if where == "keyring" else "файл в папке SYSAI")
    return {**cfg, "token_store": where}


def client_for(home: Path, cfg: dict, transport=None) -> tuple[Client, str]:
    token = secret.load(home, cfg["agent"])
    if not token:
        raise SyncError("Нет токена агента: подключите компьютер заново (новый код на странице агента)")
    return Client(cfg["server"], token, transport), token


def _offline_or_refused(exc: ApiError) -> SyncError:
    if exc.status == 401:
        return SyncError("SYSAI не принял токен агента: агента отключили или подключили на другом компьютере. "
                         "Получите новый код на странице агента и запустите установщик снова")
    return SyncError(str(exc))


def _filter_unready_hub_mcp(harness: dict, manifest: dict, state: dict, home: Path) -> tuple[dict, list[str]]:
    """Do not give Hermes a local Hub MCP server until its exact manifest version is installed."""
    safe = dict(harness or {})
    servers = dict(safe.get("mcp_servers") or {})
    wanted = {str(item.get("name") or ""): item for item in (manifest.get("tools") or [])
              if isinstance(item, dict) and item.get("name")}
    installed = state.get("tools") or {}
    missing = []
    for name, config in list(servers.items()):
        if not isinstance(config, dict):
            continue
        command = str(config.get("command") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        args = config.get("args") if isinstance(config.get("args"), list) else []
        # Only gate local SYSAI wrappers. Remote URL-based MCP servers (including the built-in «sysai») do not
        # depend on the local Hub tools directory.
        if command not in ("sysai-agent", "sysai-agent.exe") or len(args) < 2 or args[0] != "mcp" or args[1] != name:
            continue
        desired = wanted.get(name) or {}
        have = installed.get(name) or {}
        ready = bool(desired.get("sha256") and have.get("sha256") == desired.get("sha256")
                     and (Path(home) / "tools" / name).is_dir())
        if not ready:
            servers.pop(name, None)
            missing.append(name)
    safe["mcp_servers"] = servers
    return safe, sorted(missing)


def sync_once(home: Path | None = None, transport=None, restart: bool = True) -> dict:
    """Everything once: signed rules → Hub install/verification → Hermes profile → proposals → pulse."""
    home = Path(home or paths.home())
    cfg = load_agent(home)
    client, token = client_for(home, cfg, transport)
    state = fsutil.read_json(home / "state.json", {}) or {}
    report = {"agent": cfg["agent"], "changed": [], "hub": {}, "proposals": [], "errors": [], "restart": "", "access": ""}
    try:
        signed = client.json("GET", "/agents/api/config")
    except ApiError as exc:
        raise _offline_or_refused(exc) from exc
    if not signing.verify(signed, cfg["public_key"], cfg.get("key_id", "")):
        raise SyncError("Подпись настроек не сходится с ключом SYSAI, полученным при подключении: ничего не применено. "
                        "Если ключ сервера сменили — подключите компьютер заново")
    doc = signed["doc"]
    if doc.get("agent") != cfg["agent"]:
        raise SyncError(f"Настройки для другого агента ({doc.get('agent')}): ничего не применено")
    fsutil.write_json(home / "access.json", signed)  # the MCP servers and the hook check the calls by it
    state["access_sha"] = hashlib.sha256((home / "access.json").read_bytes()).hexdigest()  # verified: the hook trusts it
    state["offer"] = update.offer(doc)
    state["desktop_offer"] = desktop.offer(doc)  # the window «Агент SYSAI»: installed by the loop, in the background
    state["person"] = str(doc.get("person") or "")
    try:
        desktop.refresh(home, state)
    except OSError as exc:
        report["errors"].append(f"Окно агента: {exc}")
    harness = doc.get("harness_config") or {}
    fsutil.write_json(home / "sysai.json", harness.get("sysai") or {})
    profile_dir = paths.hermes_profile_dir(cfg)
    # Compatibility patch for Hermes MCP scope resolution under ACP editor sessions (see hermes_patch). Idempotent
    # and re-applied after a Hermes update, so a fresh SYSAI install keeps the hub tools callable from the window.
    report["hermes_patch"] = hermes_patch.ensure(profile_dir)

    # Install and verify the Hub before writing any local MCP server into Hermes config. Hermes treats a server
    # that exits during its initial connection as disconnected for the rest of the session.
    manifest = {}
    hub_synced = False
    try:
        manifest = client.json("GET", "/agents/api/hub/manifest")
        report["hub"] = hubsync.sync(home, client, manifest, state, profile_dir)
        report["errors"] += report["hub"]["errors"]
        state["conflicts"] = report["hub"]["conflicts"]
        if report["hub"]["errors"]:  # not taken whole: the next pulse sees another revision and tries again
            state.pop("hub_rev", None)
        else:
            state["hub_rev"] = manifest.get("rev", "")
        hub_synced = True
    except ApiError as exc:
        report["errors"].append(f"SYSAI_Hub: {exc}")
        state.pop("hub_rev", None)

    safe_harness, unready_mcp = _filter_unready_hub_mcp(harness, manifest if hub_synced else {}, state, home)
    applied = hub_synced and not unready_mcp
    for name in unready_mcp:
        report["errors"].append(
            f"MCP-сервер {name} не добавлен в Hermes: инструмент не установлен в версии из манифеста SYSAI_Hub")

    if doc.get("harness") == "hermes" and harness:
        try:
            report["changed"] = hermes.apply(profile_dir, safe_harness, doc.get("soul") or "", home, token,
                                             cfg["server"], launcher())
        except (OSError, ValueError) as exc:
            applied = False
            report["errors"].append(f"Профиль Hermes ({profile_dir}): {exc}")
    try:
        report["proposals"] = hubsync.propose(home, client, state, doc.get("rules") or {})
    except ApiError as exc:
        report["errors"].append(f"Предложения в хаб: {exc}")
    if applied:
        if doc.get("rev", "") != state.get("access_rev", ""):
            report["access"] = doc.get("rev", "")
        state["access_rev"] = doc.get("rev", "")
        state["applied_at"] = now()
    if report["changed"] or (report["hub"] or {}).get("changed") or (report["hub"] or {}).get("removed"):
        state["restart_pending"] = True
    state["synced_at"] = now()
    state["error"] = "; ".join(report["errors"])[:2000]
    # mcpwrap reads state.json when Hermes starts a local MCP process. Persist the verified Hub tool records before
    # restarting the gateway; otherwise the wrapper can still see the previous state and exit as «not connected».
    fsutil.write_json(home / "state.json", state)
    if state.get("restart_pending") and not hermes.gateway_running(profile_dir):
        state.pop("restart_pending", None)  # nothing to restart: Hermes reads the new settings when it starts
        report["restart"] = "шлюз Hermes не запущен: новые настройки он возьмёт при запуске"
    elif restart and state.get("restart_pending"):
        done, said = hermes.restart(cfg.get("profile") or cfg["agent"], profile_dir)
        report["restart"] = said
        if done:
            state.pop("restart_pending", None)
        else:
            log.info("Hermes не перезапущен (%s): попробую при следующей синхронизации", said)
    try:
        report["pulse"] = pulse(home, client, state)
    except ApiError as exc:
        report["errors"].append(f"Пульс: {exc}")
    fsutil.write_json(home / "state.json", state)  # after the pulse: its time is kept too («sysai-agent status»)
    return report


def pulse(home: Path, client: Client, state: dict, error: str | None = None) -> dict:
    data = {"access_rev": state.get("access_rev", ""), "versions": versions(home), "host": platform.node(),
            "hub": hubsync.summary(state), "error": state.get("error", "") if error is None else error}
    answer = client.json("POST", "/agents/api/heartbeat", data)
    state["pulse_at"] = now()
    # The offers come with every pulse, so a new build is seen within one pulse instead of the hourly full
    # synchronization: the loop decides to install on every cycle (update.due), it only lacked a fresh offer.
    if isinstance(answer, dict):
        got = update.offer({"synchronizer": answer.get("synchronizer") or {}})
        if got:
            state["offer"] = got
        win = answer.get("desktop")
        if isinstance(win, dict) and win.get("sha256"):
            state["desktop_offer"] = win
    # «Обновить сейчас» из SYSAI: a new revision means update at once, not after update.RETRY
    forced = int(answer.get("update_rev") or 0) if isinstance(answer, dict) else 0
    if forced and forced != int(state.get("update_rev") or 0):
        state["update_rev"] = forced
        state["update_force"] = forced
        state.pop("update_at", None)
        state.pop("desktop_try", None)
    return answer


def _lock(home: Path):
    """One «run» per computer: a lock file with the process id; a dead owner's lock is taken over."""
    path = Path(home) / "run.lock"
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return path
        except FileExistsError:
            try:
                pid = int(fsutil.read_text(path).strip() or 0)
            except ValueError:
                pid = 0
            if pid and pid != os.getpid() and hermes._alive(pid):
                return None
            path.unlink(missing_ok=True)
    return None


def _open_live(cfg: dict, token: str):
    return livechan.Channel(cfg["server"], token).start()


def _note_live(home: Path, channel) -> None:
    """Whether the live channel is held, and why not — in state.json beside the pulse («почему не мгновенно»)."""
    up = bool(channel and channel.up)
    why = "" if up else (channel.error if channel else "живой канал не открыт") or "живой канал открывается"
    state = fsutil.read_json(Path(home) / "state.json", {}) or {}
    if state.get("live_up") != up or state.get("live_error", "") != why:
        state["live_up"], state["live_error"] = up, why
        fsutil.write_json(Path(home) / "state.json", state)


def run(home: Path | None = None, every: int = EVERY, transport=None, cycles: int = 0, sleep=time.sleep,
        live=None) -> int:
    """The loop: a full synchronization at the start, then a pulse every `every` seconds; a full one again when the
    server's revisions differ from the applied ones, after an error, or once an hour. `cycles` > 0 — for tests.

    `live(cfg, token)` opens the live channel (live.py): a push from SYSAI ends the wait at once, so the pulse — and
    the synchronization it decides on — comes now. Without one (tests with their own transport, or the channel is
    down) the loop is exactly the pulse every `every` seconds it always was."""
    if live is None and transport is None:
        live = _open_live
    home = Path(home or paths.home())
    (home / "stop").unlink(missing_ok=True)
    lock = _lock(home)
    if lock is None:
        log.info("Синхронизатор уже работает на этом компьютере")
        return 0
    channel = None
    try:
        last_full, failed, n = 0.0, True, 0
        while True:
            n += 1
            try:
                cfg = load_agent(home)
                client, token = client_for(home, cfg, transport)
                if channel is None and live is not None:
                    try:
                        channel = live(cfg, token)
                    except Exception as exc:  # noqa: BLE001 — no channel is no reason to stop the pulse
                        log.warning("Живой канал SYSAI не открыт: %s", exc)
                if live is not None:
                    _note_live(home, channel)
                state = fsutil.read_json(home / "state.json", {}) or {}
                need = failed or time.time() - last_full > FULL_EVERY or state.get("restart_pending")
                if not need:
                    before = int(state.get("update_rev") or 0)
                    answer = pulse(home, client, state)
                    fsutil.write_json(home / "state.json", state)
                    need = answer.get("access_rev") != state.get("access_rev") or \
                        answer.get("hub_rev") != state.get("hub_rev") or \
                        int(state.get("update_rev") or 0) != before  # «обновить сейчас»: a full sync too
                if need:
                    report = sync_once(home, transport)
                    last_full, failed = time.time(), False
                    if report["changed"] or (report["hub"] or {}).get("changed") or report["proposals"] or \
                            report.get("access"):
                        log.info("Синхронизировано: %s", describe(report))
                    for e in report["errors"]:
                        log.warning("%s", e)
                    state = fsutil.read_json(home / "state.json", {}) or {}
                got = update.due(state)
                if got and self_update(home, client, got, state):
                    return 0
                offered = desktop.due(home, state)  # after the synchronizer's own update: the new one installs it
                if offered:
                    state["desktop_try"] = {"sha256": offered["sha256"], "at": time.time()}  # not again before RETRY
                    fsutil.write_json(home / "state.json", state)
                    desktop.install_quietly(home, client, offered)  # minutes at most, once per build
                elif not got and state.pop("update_force", None) is not None:
                    fsutil.write_json(home / "state.json", state)  # nothing to install: the request is spent
            except (SyncError, ApiError, OSError) as exc:
                failed = True
                log.warning("%s", exc)
                _note_failure(home, exc)
            if cycles and n >= cycles:
                return 0
            signal = _wait(home, every, sleep, channel)
            if signal == "live":
                log.info("SYSAI попросил посмотреть заново: пульс сейчас, не через %s с", every)
            if signal == "stop":
                log.info("Синхронизатор остановлен (его попросили: установщик или sysai-agent stop)")
                return 0
            if signal == "wake":  # «Проверить обновление» в окне агента: пробуем сейчас, не дожидаясь RETRY
                state = fsutil.read_json(home / "state.json", {}) or {}
                state["update_force"] = time.time()
                for key in ("update_at", "update_to", "desktop_try"):
                    state.pop(key, None)
                fsutil.write_json(home / "state.json", state)
                failed = True
                log.info("Разбудили из окна агента: полная синхронизация и обновление сейчас")
    finally:
        if channel is not None:
            channel.stop()
        lock.unlink(missing_ok=True)


def self_update(home: Path, client: Client, got: dict, state: dict) -> bool:
    """The version SYSAI signed, downloaded and checked, goes to the helper; True — the loop leaves for it."""
    if not paths.WINDOWS:
        return False
    try:
        wheel = update.fetch(home, client, got)
    except (update.UpdateError, ApiError, OSError) as exc:
        state.update(update_to=update.key_of(got), update_at=time.time())  # not again before update.RETRY
        fsutil.write_json(home / "state.json", state)
        log.warning("Обновление синхронизатора: %s", exc)
        return False
    if update.start(home, wheel, got["version"], state, build=got.get("build") or ""):
        log.info("Обновляюсь до %s: синхронизатор перезапустится сам (журнал — logs\\update.log)", got["version"])
        return True
    return False


def _note_failure(home: Path, exc: Exception) -> None:
    """A failed cycle must be visible: the window and the agent's page read the reason from state.json. Before this
    only the log knew it, so a computer refused by SYSAI looked healthy on screen and silently never updated."""
    state = fsutil.read_json(Path(home) / "state.json", {}) or {}
    state["error_at"] = now()
    state["error"] = str(exc)[:2000]
    fsutil.write_json(Path(home) / "state.json", state)


def wake(home: Path | None = None) -> bool:
    """Asks the running loop to check for an update now, without waiting for RETRY — «Проверить обновление» in the
    window. True when a loop was there to see it."""
    home = Path(home or paths.home())
    if not (home / "run.lock").exists():
        return False
    (home / "wake").write_text("wake", encoding="utf-8")
    return True


def _wait(home: Path, seconds: int, sleep, channel=None) -> str:
    """Sleeps; "stop" when asked to stop (the file «stop» — the installer does so before updating), "wake" when the
    window asks to check for an update now (the file «wake»), "live" when SYSAI said «посмотри заново» over the
    live channel, "" — the time is up."""
    folder = Path(home)
    stop, wake = folder / "stop", folder / "wake"
    for _ in range(max(1, int(seconds))):
        if stop.exists():
            stop.unlink(missing_ok=True)
            return "stop"
        if wake.exists():
            wake.unlink(missing_ok=True)
            return "wake"
        if channel is not None:
            if channel.wait(1):  # the second is spent waiting on the channel instead of sleeping
                return "live"
        else:
            sleep(1)
    return ""


def stop(home: Path | None = None, wait: int = 60, sleep=time.sleep) -> bool:
    """Asks the running loop to stop; True once it has (or none ran)."""
    home = Path(home or paths.home())
    lock = home / "run.lock"
    if not lock.exists():
        return True
    (home / "stop").write_text("stop", encoding="utf-8")
    for _ in range(wait):
        if not lock.exists():
            return True
        sleep(1)
    return not lock.exists()


def describe(report: dict) -> str:
    parts = []
    if report.get("changed"):
        parts.append("Hermes: " + ", ".join(report["changed"]))
    hub = report.get("hub") or {}
    if hub.get("changed"):
        parts.append("из хаба: " + ", ".join(hub["changed"]))
    if hub.get("removed"):
        parts.append("убрано: " + ", ".join(hub["removed"]))
    if report.get("proposals"):
        parts.append("предложено в хаб: " + ", ".join(report["proposals"]))
    if report.get("access") and not report.get("changed"):
        parts.append("доступы: " + report["access"])
    return "; ".join(parts) or "без изменений"


def _tail(path: Path, lines: int = 8) -> str:
    """Последние строки файла — для отчёта: журнал обновления одним куском, без исключений на отсутствующем файле."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return ""
    return "\n".join(text[-lines:])


def update_report(home: Path | None = None, transport=None) -> dict:
    """«Почему обновление не пришло»: что стоит здесь, что отдаёт SYSAI, чего не хватает до установки.

    Ничего не меняет: спрашивает подписанный документ, сравнивает версию и сборку, показывает прошлую попытку и
    хвост журнала. По этому видно одно из трёх — ждать, переустанавливать или это SYSAI отдаёт старое.
    """
    home = Path(home or paths.home())
    cfg = fsutil.read_json(home / "agent.json", {}) or {}
    state = fsutil.read_json(home / "state.json", {}) or {}
    out = {"home": str(home), "version": __version__, "build": update.local_build(), "offer": {}, "behind": False,
           "due": None, "auto_update": None, "tried": "", "server": cfg.get("server", ""), "error": "",
           "log": _tail(home / "logs" / "update.log")}
    tried = float(state.get("update_at") or 0)
    if tried:
        out["tried"] = now_from(tried)
    if not cfg.get("agent"):
        out["error"] = "компьютер не подключён к SYSAI"
        return out
    # Запомненное в access.json — то, по чему компьютер жил до сих пор; свежий ответ важнее, но и он под проверкой.
    got = update.offer((fsutil.read_json(home / "access.json", {}) or {}).get("doc") or {})
    try:
        client, _ = client_for(home, cfg, transport)
        signed = client.json("GET", "/agents/api/config")
        if not signing.verify(signed, cfg.get("public_key", ""), cfg.get("key_id", "")):
            out["error"] = "подпись настроек не сходится: этому ответу компьютер ничего не поверит"
        else:
            got = update.offer(signed.get("doc") or {})
    except (ApiError, OSError) as exc:
        out["error"] = f"SYSAI не ответил: {exc} — показано то, что запомнено в access.json"
    out["offer"] = got
    out["auto_update"] = bool(got.get("auto_update")) if got else None
    out["behind"] = update.behind(got) if got else False
    # «пошло бы сейчас» считаем по свежему предложению, а не по тому, что запомнено в state.json: иначе отчёт
    # повторяет прошлую синхронизацию и врёт про сегодняшний ответ SYSAI
    out["due"] = bool(update.due({**state, "offer": got})) if got else False
    return out


def now_from(stamp: float) -> str:
    """Когда это было, по-человечески: «2 ч назад» — в отчётах вместо секунд с эпохи."""
    delta = max(0.0, time.time() - float(stamp))
    for size, name in ((86400, "дн"), (3600, "ч"), (60, "мин")):
        if delta >= size:
            return f"{int(delta // size)} {name} назад"
    return f"{int(delta)} с назад"


def status(home: Path | None = None) -> dict:
    home = Path(home or paths.home())
    cfg = fsutil.read_json(home / "agent.json", {}) or {}
    state = fsutil.read_json(home / "state.json", {}) or {}
    out = {"home": str(home), "connected": bool(cfg.get("agent")), "agent": cfg.get("agent", ""),
           "server": cfg.get("server", ""), "version": __version__, "access_rev": state.get("access_rev", ""),
           "hub_rev": state.get("hub_rev", ""), "synced_at": state.get("synced_at", ""), "pulse_at": state.get("pulse_at", ""),
           "error": state.get("error", ""), "skills": sorted(state.get("skills") or {}), "tools": sorted(state.get("tools") or {}),
           "conflicts": state.get("conflicts") or [], "restart_pending": bool(state.get("restart_pending")),
           "desktop": desktop.summary(home)}
    if cfg.get("agent"):
        out["hermes"] = hermes.profile_info(paths.hermes_profile_dir(cfg))
    return out
