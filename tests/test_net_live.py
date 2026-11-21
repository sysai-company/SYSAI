"""The live channel of the agents (app/net/live.py, agents/sync/sysai_agent/live.py): a saved swarm, «Обновить сейчас»
and a switched-off agent reach the computer at once over one WebSocket; without it — the pulse, as before."""
import io
import sys
import threading
import zipfile
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "sync"))

from sysai_agent import live as client_live  # noqa: E402

from app.net import access, agents, live  # noqa: E402


@pytest.fixture(autouse=True)
def _no_leftover_sockets():
    yield
    live._sockets.clear()


def _open(client, net_agent):
    return client.websocket_connect("/agents/api/live", headers=dict(net_agent["headers"]))  # it adds its own keys


def test_a_saved_swarm_reaches_a_connected_agent_at_once(client, net_agent):
    """«Рой агентов»: сохранили — компьютер на связи получает «посмотри заново» сразу, и сообщение так и говорит."""
    with _open(client, net_agent) as ws:
        assert live.connected(net_agent["id"]) and live.count() == 1
        page = client.get("/agents/swarm").text
        assert "на связи 1" in page and 'data-live="1"' in page, "сота показывает, что компьютер на связи"
        r = client.post(f"/agents/swarm/{net_agent['id']}", data={"on": "1", "cells": "12", "at": "6"})
        assert ws.receive_json() == {"type": "poke", "why": "swarm"}
        assert "Компьютер на связи — получил сразу" in r.text
        assert access.document(net_agent["id"])["rules"]["swarm"] == {"on": True, "cells": 12, "at": 6}
    # the socket is gone: the next save says honestly that the pulse will bring it
    r = client.post(f"/agents/swarm/{net_agent['id']}", data={"cells": "12", "at": "6"})
    assert "не на связи — применит при следующем пульсе" in r.text and not live.connected(net_agent["id"])


def test_update_now_wakes_connected_agents_and_says_how_many(client, net_agent):
    with _open(client, net_agent) as ws:
        r = client.post("/agents/update", data={"scope": "all"})
        assert ws.receive_json() == {"type": "poke", "why": "update"}
        assert "Все на связи — ставят сейчас" in r.text
        r = client.post(f"/agents/{net_agent['id']}/update")
        assert ws.receive_json()["why"] == "update" and "на связи и ставит последнюю версию сейчас" in r.text
    r = client.post("/agents/update", data={"scope": "all"})
    assert "никто не на связи — получат при следующем пульсе" in r.text


def test_a_hub_publish_and_a_profile_save_wake_everyone_connected(client, net_agent):
    with _open(client, net_agent) as ws:
        pid = next(p["id"] for p in access.profiles() if p["code"] == "opo-engineer")
        base = next(p for p in access.profiles() if p["id"] == pid)
        client.post(f"/agents/access/{pid}", data={"name": base["name"], "description": base["description"]})
        assert ws.receive_json() == {"type": "poke", "why": "access"}
        access.save_profile(pid, base["name"], base["description"], base["rules"], by="test")
        # публикация в хабе: загрузили версию и опубликовали — тоже «посмотри заново», а не «с пульсом»
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as z:
            z.writestr("opo-live/SKILL.md", "---\nname: opo-live\ndescription: Проверка живого канала\nversion: 1.0.0\n---\n# Живой\n")
        r = client.post("/hub/upload", files={"file": ("opo-live.zip", blob.getvalue(), "application/zip")},
                        follow_redirects=False)
        assert r.status_code == 303 and "opo-live" in r.headers["location"]
        client.post("/hub/opo-live/1.0.0/publish", data={"note": ""})
        assert ws.receive_json() == {"type": "poke", "why": "hub"}


def test_no_token_no_channel_and_a_switched_off_agent_is_cut_off(client, net_agent):
    with pytest.raises(WebSocketDisconnect) as no:
        with client.websocket_connect("/agents/api/live") as ws:
            ws.receive_json()
    assert no.value.code == live.UNAUTHORIZED
    with pytest.raises(WebSocketDisconnect) as bad:
        with client.websocket_connect("/agents/api/live", headers={"Authorization": "Bearer sysai_nope"}) as ws:
            ws.receive_json()
    assert bad.value.code == live.UNAUTHORIZED
    with _open(client, net_agent) as ws:
        agents.revoke(net_agent["id"], by="test")
        with pytest.raises(WebSocketDisconnect) as cut:
            ws.receive_json()
        assert cut.value.code == live.UNAUTHORIZED
    assert not live.connected(net_agent["id"])
    with pytest.raises(WebSocketDisconnect):  # the revoked token does not open it again
        with _open(client, net_agent) as ws:
            ws.receive_json()


def test_health_counts_the_agents_on_the_line(client, net_agent):
    assert client.get("/health").json()["live"] == 0
    with _open(client, net_agent):
        assert client.get("/health").json()["live"] == 1


# ------------------------------------------------------------------------------------- the computer's side
class _Conn:
    """A fake connection of `websockets.sync`: hands out the given texts, then times out until closed."""

    def __init__(self, texts):
        self.texts, self.sent = list(texts), []
        self.closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed.set()

    def recv(self, timeout=None):
        if self.texts:
            return self.texts.pop(0)
        if self.closed.wait(0.01):
            raise OSError("closed")
        raise TimeoutError

    def send(self, text):
        self.sent.append(text)


def test_the_channel_turns_a_push_into_a_wake_and_pings_by_its_own_clock():
    conn = _Conn(['{"type":"ping"}', '{"type":"poke","why":"swarm"}'])
    seen = {}
    clock = iter(range(0, 10000, client_live.PING_EVERY))  # each look at the clock is one ping period later

    def connect(url, additional_headers=None, **_):
        seen.update(url=url, headers=additional_headers)
        return conn
    ch = client_live.Channel("https://sysai.example/apps/sysai", "sysai_tok", connect=connect,
                             clock=lambda: next(clock)).start()
    try:
        assert ch.wait(5), "push → the loop is woken"
        assert seen["url"] == "wss://sysai.example/apps/sysai/agents/api/live"
        assert seen["headers"] == {"Authorization": "Bearer sysai_tok"}
        assert ch.up and ch.error == ""
        for _ in range(200):
            if conn.sent:
                break
            threading.Event().wait(0.01)
        assert "ping" in conn.sent, "the computer pings by its clock, so a dead connection is found from its side"
    finally:
        ch.stop()
        conn.closed.set()


def test_without_websockets_the_channel_says_why_and_the_pulse_stays(monkeypatch):
    def no_package():
        raise ImportError("No module named 'websockets'")
    monkeypatch.setattr(client_live, "_connect", no_package)
    ch = client_live.Channel("https://sysai.example", "sysai_tok").start()
    ch._thread.join(5)
    assert not ch.up and "нет пакета websockets" in ch.error and "по пульсу" in ch.error
    assert ch.wait(0) is False, "no push — the loop waits its pulse"
    assert client_live.url_of("ftp://x") == "" and client_live.Channel("ftp://x", "t").start().error
