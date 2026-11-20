"""Haiwell Happy: свой инструмент, свой закрытый формат `.gpc`, язык только LD.

Формат тела не разобран, и это состояние закреплено тестом: инструмент обязан сказать «заголовок прочитан, тело
нет» и отказаться писать файл, а не выдать похожий. Когда разбор появится, эти тесты изменятся вместе с ним.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "hub" / "seed" / "haiwell-happy"


def _load(name, path):
    """Загрузить модуль по пути, не трогая sys.path: в соседних seed-папках тоже есть `server.py`."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hawell = _load("hawell", KIT / "hawell.py")
sys.modules.setdefault("hawell", hawell)


def _gpc(path: Path, body: bytes | None = None) -> Path:
    """Файл с настоящим заголовком Haiwell и случайным телом — тело всё равно не разбирается."""
    path.write_bytes(hawell.MAGIC + (body if body is not None else os.urandom(8192)))
    return path


def _server(calls):
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})]
    for i, (name, args) in enumerate(calls, start=2):
        lines.append(json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                 "params": {"name": name, "arguments": args}}))
    out = subprocess.run([sys.executable, str(KIT / "server.py")], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    return [json.loads(line) for line in out.stdout.splitlines() if line.strip()][1:]


def test_the_header_is_read_and_the_body_is_admitted_unread(tmp_path):
    p = _gpc(tmp_path / "Line.gpc")
    one = hawell.info(p)
    assert one["magic"] is True and one["environment"] == "Haiwell Happy" and one["language"] == "LD"
    assert one["decoded"] is False, "тело .gpc не разобрано — инструмент не должен делать вид, что прочитал"
    assert "не разобрано" in one["note"]


def test_a_file_of_another_program_is_named_as_such(tmp_path):
    p = tmp_path / "x.gpc"
    p.write_bytes(b"PK\x03\x04 not a haiwell file at all" + b"0" * 2048)
    one = hawell.info(p)
    assert one["magic"] is False
    assert "не файл Haiwell" in one["note"]
    res = hawell.check(p)
    assert res["summary"]["error"] == 1 and any("нет заголовка" in i["text"] for i in res["issues"])


def test_a_real_file_is_never_written_because_the_body_is_not_decoded(tmp_path):
    out = tmp_path / "Line.gpc"
    with pytest.raises(hawell.HawellError, match="не разобран"):
        hawell.export(out, tmp_path)
    assert not out.exists(), "похожий файл вместо проекта — потеря работы инженера"


def test_the_server_says_which_environment_it_is():
    out = subprocess.run([sys.executable, str(KIT / "server.py")],
                         input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n",
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    got = json.loads(out.stdout.strip().splitlines()[0])["result"]
    assert got["serverInfo"] == {"name": "haiwell-happy", "title": "Haiwell Happy (.gpc, LD)", "version": "1.0.0"}
    assert "только LD" in got["instructions"]


def test_the_tools_are_info_check_and_an_honest_refusal(tmp_path):
    p = _gpc(tmp_path / "Line.gpc")
    info, check, export = _server([("hawell_info", {"path": str(p)}), ("hawell_check", {"path": str(p)}),
                                   ("hawell_export", {"path": str(tmp_path / "out.gpc"),
                                                      "src_dir": str(tmp_path)})])
    assert info["result"]["structuredContent"]["decoded"] is False
    assert check["result"]["structuredContent"]["summary"]["error"] == 0
    assert export["result"].get("isError") is True and "не разобран" in export["result"]["content"][0]["text"]
    assert not (tmp_path / "out.gpc").exists()
