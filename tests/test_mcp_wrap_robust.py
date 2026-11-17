"""The MCP wrapper (sysai-agent mcp) must keep the connection alive whatever a tool or a rule does. Hermes marks a
server that exits as «not connected» for the whole session, so the wrapper answers with an error instead of crashing,
drops non-JSON noise of the tool (raw bytes of another code page broke Hermes on Windows once), and answers clearly
when the tool itself exits. These are unit tests of the wrapper: no server, no database, only the standard library."""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "sync"))

from sysai_agent import mcpwrap  # noqa: E402

mcpwrap.WAIT_STEP = 0  # the tests do not wait for a synchronizer in mid-work


def _rpc(id_, method, params=None):
    return json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})


@pytest.fixture
def home(tmp_path):
    (tmp_path / "agent.json").write_text(json.dumps({"agent": "opo-pc", "public_key": ""}), encoding="utf-8")
    return tmp_path


def _startable(home, monkeypatch, name, argv):
    """«name» is a startable tool: the guard allows it, its folder and the state record are there, the run line is argv."""
    monkeypatch.setattr(mcpwrap.Guard, "server_allowed", lambda self: True)
    monkeypatch.setattr(mcpwrap, "command", lambda spec, folder, python="": list(argv))
    state = mcpwrap.fsutil.read_json(home / "state.json", {}) or {}
    state.setdefault("tools", {})[name] = {"version": "1.0.0", "sha256": "x", "spec": {"run": "python server.py"}}
    mcpwrap.fsutil.write_json(home / "state.json", state)
    (home / "tools" / name).mkdir(parents=True, exist_ok=True)


def _answers(out):
    return {m["id"]: m for m in (json.loads(line) for line in out.getvalue().decode("utf-8").splitlines() if line.strip())}


# a tiny MCP server: tools/list with one tool, tools/call echoes the arguments
ECHO = (
    "import json, sys\n"
    "for line in sys.stdin:\n"
    "    msg = json.loads(line)\n"
    "    if msg.get('method') == 'tools/list':\n"
    "        out = {'tools': [{'name': 'read_doc'}]}\n"
    "    else:\n"
    "        out = {'content': [{'type': 'text', 'text': 'ok'}]}\n"
    "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg.get('id'), 'result': out}) + '\\n')\n"
    "    sys.stdout.flush()\n"
)


def test_a_broken_rule_answers_with_an_error_and_keeps_the_connection(home, monkeypatch):
    folder = home / "tools" / "report-kit"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "server.py").write_text(ECHO, encoding="utf-8")
    _startable(home, monkeypatch, "report-kit", [sys.executable, str(folder / "server.py")])

    def boom(self, tool, args):
        raise RuntimeError("правило повреждено")
    monkeypatch.setattr(mcpwrap.Guard, "check_call", boom)
    calls = [_rpc(1, "tools/list"), _rpc(2, "tools/call", {"name": "read_doc", "arguments": {}}), _rpc(3, "tools/list")]
    out = io.BytesIO()
    code = mcpwrap.serve("report-kit", home, stdin=io.BytesIO(("\n".join(calls) + "\n").encode("utf-8")), stdout=out)
    assert code == 0
    answers = _answers(out)
    assert "result" in answers[1] and "result" in answers[3]          # the connection survived the broken rule
    assert "внутренняя ошибка" in answers[2]["error"]["message"]


def test_non_json_noise_of_the_tool_is_dropped_and_the_wire_stays_ascii(home, monkeypatch):
    noise = (
        "import json, sys\n"
        "sys.stdout.buffer.write('\\u2192 \\u043f\\u0440\\u0438\\u0432\\u0435\\u0442\\n'.encode('utf-8'))\n"
        "sys.stdout.flush()\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg.get('id'), 'result': {'tools': [{'name': 'read_doc'}]}}) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    _startable(home, monkeypatch, "noise-kit", [sys.executable, "-c", noise])
    out = io.BytesIO()
    code = mcpwrap.serve("noise-kit", home, stdin=io.BytesIO((_rpc(1, "tools/list") + "\n").encode("utf-8")), stdout=out)
    assert code == 0
    lines = [x for x in out.getvalue().split(b"\n") if x.strip()]
    assert len(lines) == 1                                            # the noise line is gone, only the JSON answer stays
    for line in lines:
        line.decode("ascii")                                          # the wire is ASCII only
        assert json.loads(line)["id"] == 1


def test_a_tool_that_exits_gets_a_clear_answer_not_silence(home, monkeypatch):
    import time
    die = "import sys\nsys.stdin.readline()\n"                        # consumes one request, then exits without answering
    _startable(home, monkeypatch, "die-kit", [sys.executable, "-c", die])
    monkeypatch.setattr(mcpwrap.Guard, "check_call", lambda self, tool, args: "")  # allow: the call must reach the tool

    class SlowStdin:                                                  # the second request arrives after the tool has died
        def __iter__(self):
            yield (_rpc(5, "tools/call", {"name": "read_doc", "arguments": {}}) + "\n").encode("utf-8")
            time.sleep(0.5)
            yield (_rpc(6, "tools/call", {"name": "read_doc", "arguments": {}}) + "\n").encode("utf-8")
    out = io.BytesIO()
    mcpwrap.serve("die-kit", home, stdin=SlowStdin(), stdout=out)
    answers = _answers(out)
    assert 6 in answers and "error" in answers[6]
    assert "перезапустите окно" in answers[6]["error"]["message"]


def test_a_signed_doc_without_rules_is_not_trusted_and_does_not_crash(home, monkeypatch):
    """Guard.load reads signed['doc']['rules']; a doc without «rules» must yield None, not a KeyError that kills the wrapper."""
    access = home / "access.json"
    mcpwrap.fsutil.write_json(access, {"alg": "Ed25519", "doc": {}, "sig": "x"})
    guard = mcpwrap.Guard(home, "report-kit", access)
    monkeypatch.setattr(mcpwrap.signing, "verify", lambda signed, key, key_id="": True)
    guard.agent = {"public_key": "k"}
    assert guard.load() is None                                       # no «rules» key: not trusted, no exception
