"""«Обновить сейчас» и установщик в один клик (TASKBAR T7–T8): the .exe SYSAI gives out with the server and the
one-time code inside, the button «Обновить всех / выбранных», the revision in the pulse and the synchronizer
updating at once instead of waiting for its retry."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "sync"))

from sysai_agent import core, desktop as D, hermes, update  # noqa: E402

from app.net import installer  # noqa: E402


# --------------------------------------------------------------------------------------------- the one-click .exe
def test_the_installer_exe_carries_the_server_and_the_code():
    blob = installer.exe("https://sysai.example", "7K2M-9QXA")
    assert blob[:2] == b"MZ", "это настоящий исполняемый файл Windows"
    at = blob.find(installer.MARKER)
    assert at > 0
    block = blob[at + len(installer.MARKER):at + len(installer.MARKER) + installer.BLOCK]
    assert block[:installer.FIELD].rstrip(b"\0") == b"https://sysai.example"
    assert block[installer.FIELD:].rstrip(b"\0") == b"7K2M-9QXA"
    # всё остальное — байт в байт тот же файл: подменяется только блок настроек
    original = installer.EXE.read_bytes()
    assert len(blob) == len(original)
    assert blob[:at] == original[:at]
    tail = at + len(installer.MARKER) + installer.BLOCK
    assert blob[tail:] == original[tail:]


def test_the_exe_without_a_code_asks_for_it_on_the_pc():
    blob = installer.exe("https://sysai.example")
    at = blob.find(installer.MARKER)
    block = blob[at + len(installer.MARKER):at + len(installer.MARKER) + installer.BLOCK]
    assert block[:installer.FIELD].rstrip(b"\0") == b"https://sysai.example"
    assert block[installer.FIELD:].strip(b"\0") == b""


def test_the_exe_downloads_from_the_agents_page(client, net_agent):
    r = client.get("/agents/download/SYSAI-Setup.exe")
    assert r.status_code == 200 and r.content[:2] == b"MZ"
    assert "SYSAI-Setup.exe" in r.headers["content-disposition"]
    r = client.get(f"/agents/{net_agent['id']}/setup.exe?code=7K2M-9QXA")
    assert r.status_code == 200 and r.content[:2] == b"MZ"
    assert net_agent["name"] in r.headers["content-disposition"]
    at = r.content.find(installer.MARKER)
    code = r.content[at + len(installer.MARKER) + installer.FIELD:at + len(installer.MARKER) + installer.BLOCK]
    assert code.rstrip(b"\0") == b"7K2M-9QXA"


# --------------------------------------------------------------------------------------------- «обновить сейчас»
def test_update_all_bumps_the_revision_and_the_pulse_carries_it(client, net_agent):
    assert client.post("/agents/api/heartbeat", headers=net_agent["headers"], json={}).json()["update_rev"] == 0
    r = client.post("/agents/update", data={"scope": "all"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.post("/agents/api/heartbeat", headers=net_agent["headers"], json={}).json()["update_rev"] == 1
    # второе нажатие — новая ревизия: компьютер обновится ещё раз
    client.post("/agents/update", data={"scope": "all"}, follow_redirects=False)
    assert client.post("/agents/api/heartbeat", headers=net_agent["headers"], json={}).json()["update_rev"] == 2


def test_update_picked_agents_only(client, net_agent):
    from app.db import SessionLocal, User
    from app.net import agents
    with SessionLocal() as s:
        admin = s.query(User).filter(User.role == "superuser").first()
        admin_id = admin.id
    other = agents.create(admin_id, "opo-second", None, None, "hermes", "", by="test")
    client.post("/agents/update", data={"scope": "picked", "ids": [str(net_agent["id"])]}, follow_redirects=False)
    assert client.post("/agents/api/heartbeat", headers=net_agent["headers"], json={}).json()["update_rev"] == 1
    with SessionLocal() as s:
        from app.net.models import NetAgent
        assert int(s.get(NetAgent, other.id).update_rev or 0) == 0, "невыбранный агент не тронут"


def test_update_without_a_choice_asks_to_choose(client, net_agent):
    r = client.post("/agents/update", data={"scope": "picked"}, follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]


# --------------------------------------------------------------------------------------------- the synchronizer
class _FakeClient:
    def __init__(self, answer):
        self.answer = answer

    def json(self, method, path, data=None):
        return self.answer


def test_the_pulse_turns_a_new_revision_into_an_immediate_update(tmp_path, monkeypatch):
    monkeypatch.setattr(hermes, "version", lambda: "")
    state = {"offer": {"version": "9.9.9", "sha256": "a" * 64, "auto_update": False},
             "update_to": "9.9.9", "update_at": 1000.0}
    assert update.due(state, now=1001.0) == {}, "автообновление выключено и попытка уже была"
    core.pulse(tmp_path, _FakeClient({"update_rev": 3}), state)
    assert state["update_force"] == 3 and "update_at" not in state
    assert update.due(state, now=1001.0)["version"] == "9.9.9", "«обновить сейчас» сильнее выключенного автообновления"


def test_the_window_is_installed_at_once_when_sysai_asks(tmp_path, monkeypatch):
    got = D.offer({"desktop": {"version": "0.7.0", "file": "sysai-desktop-0.7.0.zip", "sha256": "a" * 64,
                               "auto_update": False,
                               "electron": {"version": "44.10.2", "file": "electron-v44.10.2-win32-x64.zip",
                                            "sha256": "b" * 64, "urls": ["https://github.com/e.zip"]}}})
    monkeypatch.setattr(D.paths, "WINDOWS", True)
    state = {"desktop_offer": got}
    assert D.due(tmp_path, state) == {}
    state["update_force"] = 1
    assert D.due(tmp_path, state) == got


def test_a_new_build_is_announced_in_the_running_window(tmp_path, monkeypatch):
    heard = []
    monkeypatch.setattr(D, "notify", lambda home, text, kind="info", timeout=5: heard.append((text, kind)) or True)
    monkeypatch.setattr(D, "installed", lambda home: {"exe": "e", "app": "a", "sha256": "old"})
    monkeypatch.setattr(D, "_electron", lambda *a, **k: tmp_path / "electron")
    monkeypatch.setattr(D, "_app", lambda *a, **k: tmp_path / "app")
    monkeypatch.setattr(D, "_shortcuts", lambda *a, **k: {"done": []})
    monkeypatch.setattr(D, "_cleanup", lambda *a, **k: None)
    monkeypatch.setattr(D, "_lock", lambda home: tmp_path / "lock")
    monkeypatch.setattr(D.paths, "WINDOWS", True)
    (tmp_path / "app").mkdir()
    (tmp_path / "electron").mkdir()
    got = {"version": "0.7.0", "file": "sysai-desktop-0.7.0.zip", "sha256": "new",
           "electron": {"version": "44.10.2", "sha256": "b" * 64}}
    D.install(tmp_path, None, got, say=lambda *a: None)
    assert heard and heard[0][1] == "update" and "0.7.0" in heard[0][0]
