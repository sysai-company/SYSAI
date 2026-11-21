"""The live channel of the agents: one WebSocket per computer, so a change in SYSAI reaches it at once.

The pulse every 5 minutes stays as it was — the channel only says «посмотри заново» (the agent then pulses and, if the
revisions moved, synchronizes from the signed document as always). Nothing but that word goes down the socket: the
rules still come only signed, so a socket that lies can make a computer ask more often, never trust something else.

One process (the Dockerfile starts one uvicorn): the registry is this module's dictionary. `poke` and `drop` are called
from the handlers' threads, so they hand the message to the event loop with `call_soon_threadsafe`."""
import asyncio
import logging

from starlette.websockets import WebSocket, WebSocketDisconnect

log = logging.getLogger("sysai.net.live")

PING_EVERY = 25  # seconds: a proxy closes a silent connection after a minute or so (Caddy keeps it, others do not)
UNAUTHORIZED = 4401  # the close code for «no token / revoked token», as HTTP 401

_sockets: dict = {}  # agent_id -> {id(queue): (loop, queue)}; one computer may open a second while the first dies


def _put(entry, message) -> None:
    loop, queue = entry
    try:
        loop.call_soon_threadsafe(queue.put_nowait, message)
    except RuntimeError:  # the loop has closed (shutdown): the agent will pulse anyway
        pass


def poke(agent_ids=None, why: str = "") -> int:
    """«Посмотри заново» to these agents (None — every connected one). Returns how many computers got it now; the rest
    learn at their next pulse."""
    wanted = None if agent_ids is None else {int(i) for i in agent_ids}
    told = 0
    for agent_id, entries in list(_sockets.items()):
        if wanted is not None and agent_id not in wanted:
            continue
        for entry in list(entries.values()):
            _put(entry, {"type": "poke", "why": why})
        told += bool(entries)
    return told


def drop(agent_id: int) -> None:
    """The agent was switched off: its open socket is closed now, not when the computer next talks to it."""
    for entry in list((_sockets.get(int(agent_id)) or {}).values()):
        _put(entry, None)


def connected(agent_id: int) -> bool:
    return bool(_sockets.get(int(agent_id)))


def count() -> int:
    """How many agents are on the line now — /health shows it, so a dead channel is seen at the usual address."""
    return sum(1 for entries in _sockets.values() if entries)


async def serve(ws: WebSocket, authenticate) -> None:
    """`authenticate(headers, ip)` -> agent id or None, called in a thread (it asks the base)."""
    from anyio import to_thread
    agent_id = await to_thread.run_sync(authenticate, ws.headers, ws.client.host if ws.client else "")
    if agent_id is None:
        await ws.close(code=UNAUTHORIZED)
        return
    await ws.accept()
    loop, queue = asyncio.get_running_loop(), asyncio.Queue()
    entries = _sockets.setdefault(agent_id, {})
    entries[id(queue)] = (loop, queue)

    async def send():  # its own task: a receive-only loop would never hand a poke over
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), PING_EVERY)
            except asyncio.TimeoutError:
                message = {"type": "ping"}
            if message is None:
                await ws.close(code=UNAUTHORIZED)
                return
            await ws.send_json(message)

    sender = asyncio.create_task(send())
    try:
        while True:
            receiving = asyncio.ensure_future(ws.receive_text())
            done, _ = await asyncio.wait({receiving, sender}, return_when=asyncio.FIRST_COMPLETED)
            if sender in done:  # closed by drop() or the send failed: the connection is over
                receiving.cancel()
                break
            if receiving.result() == "ping":
                await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sender.cancel()
        entries.pop(id(queue), None)
        if not entries:
            _sockets.pop(agent_id, None)
