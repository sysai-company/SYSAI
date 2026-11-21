"""The live channel to SYSAI: one WebSocket that says «посмотри заново» the moment something changes there — a saved
swarm, a new access profile, «Обновить сейчас», a published hub version — instead of at the next pulse (5 minutes).

It only wakes the loop: the loop then pulses and, if the revisions moved, synchronizes from the signed document as
before. When the channel cannot be held (no `websockets` on this computer, a proxy without the upgrade, SYSAI is
older, the token refused), the loop simply waits its pulse, and the reason is written to state.json (`live_error`)
and the log, so «почему не мгновенно» has an answer.

The connection lives in its own thread; the loop asks `wait(seconds)` instead of sleeping."""
import logging
import threading
import time

log = logging.getLogger("sysai_agent")

PATH = "/agents/api/live"
PING_EVERY = 25    # seconds: the server pings too; this one finds a dead connection from our side
RETRY = (2, 5, 15, 30, 60)  # seconds between attempts; the pulse covers the gap meanwhile


def url_of(server: str) -> str:
    server = str(server or "").rstrip("/")
    if server.startswith("https://"):
        return "wss://" + server[len("https://"):] + PATH
    if server.startswith("http://"):
        return "ws://" + server[len("http://"):] + PATH
    return ""


def _connect():
    """The client of `websockets`, imported late: a computer whose update could not bring the package keeps working on
    the pulse — the import error becomes the reason, not a crash of the loop."""
    from websockets.sync.client import connect
    return connect


class Channel:
    """connect(url, headers) -> a connection with recv(timeout) / send(text) / close(); swappable for the tests."""

    def __init__(self, server: str, token: str, connect=None, clock=time.monotonic):
        self.url, self.token = url_of(server), token
        self._connect, self._clock = connect, clock
        self._woken = threading.Event()
        self._stop = threading.Event()
        self.error = ""  # why the channel is not held now ("" — it is)
        self.up = False
        self._thread = None

    # ------------------------------------------------------------------ for the loop
    def start(self) -> "Channel":
        if not self.url:
            self.error = "адрес SYSAI не http(s): живой канал не открыть"
            return self
        self._thread = threading.Thread(target=self._run, name="sysai-live", daemon=True)
        self._thread.start()
        return self

    def wait(self, seconds: float) -> bool:
        """Waits up to `seconds`; True — SYSAI said «посмотри заново» meanwhile (or before)."""
        got = self._woken.wait(max(0.0, seconds))
        self._woken.clear()
        return got

    def stop(self) -> None:
        self._stop.set()
        self._woken.set()

    # ------------------------------------------------------------------ the thread
    def _run(self) -> None:
        tries = 0
        while not self._stop.is_set():
            try:
                connect = self._connect or _connect()
            except ImportError as exc:
                self._fail(f"нет пакета websockets ({exc}): живой канал выключен, работаем по пульсу")
                return  # nothing to retry: the next update of the synchronizer brings the package
            try:
                with connect(self.url, additional_headers={"Authorization": f"Bearer {self.token}"},
                             open_timeout=15, close_timeout=5) as conn:
                    self.up, self.error, tries = True, "", 0
                    log.info("Живой канал SYSAI открыт: изменения приходят сразу")
                    self._woken.set()  # whatever changed while we were away: look once now
                    self._hold(conn)
            except Exception as exc:  # noqa: BLE001 — any failure of the channel only means «по пульсу»
                if self._stop.is_set():
                    break
                self._fail(_reason(exc))
            self.up = False
            if self._stop.wait(RETRY[min(tries, len(RETRY) - 1)]):
                break
            tries += 1

    def _hold(self, conn) -> None:
        last = self._clock()
        while not self._stop.is_set():
            try:
                text = conn.recv(timeout=PING_EVERY)
            except TimeoutError:
                text = None
            if text is None:
                if self._clock() - last >= PING_EVERY:
                    conn.send("ping")
                    last = self._clock()
                continue
            last = self._clock()
            if '"poke"' in str(text):
                log.info("SYSAI: посмотри заново — синхронизируюсь сейчас")
                self._woken.set()

    def _fail(self, why: str) -> None:
        if why != self.error:
            log.warning("Живой канал SYSAI: %s", why)
        self.error, self.up = why, False


def _reason(exc: Exception) -> str:
    code = getattr(getattr(exc, "rcvd", None), "code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if code in (4401, 401, 403):
        return "SYSAI не принял токен агента для живого канала — работаем по пульсу"
    if code == 404:
        return "SYSAI ещё не знает живого канала (старая версия службы) — работаем по пульсу"
    return f"нет живого канала ({type(exc).__name__}: {exc}) — работаем по пульсу"
