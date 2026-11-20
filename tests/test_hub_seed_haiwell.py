"""Haiwell Happy: `.gpc` — закрытый контейнер, программа — списком инструкций.

Тело `.gpc` не разбирается (сжатие вендора), и это закреплено тестами: инструмент говорит «заголовок прочитан,
тело нет» и файл `.gpc` не пишет. Но программа для Haiwell делается и без этого: у среды есть язык инструкций
(STL), LD ↔ STL переключается по F7, и в руководстве Haiwell у каждой инструкции стоит поддержка IL. Поэтому
экспорт — `program.il` + лестница + таблица адресов + шаги для инженера, и он проверяется здесь по существу:
какой адрес куда, какие инструкции, читается ли записанное обратно и повторяется ли файл байт в байт.
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

SPEC = {
    "project": {"name": "Эталон", "controller": "Haiwell", "panel": "cMT3072X", "link": "modbus_tcp"},
    "types": {"noria": {"title": "Нория", "in": ["speed", "belt"], "out": ["run"], "faults": ["belt"]}},
    "mechanisms": [
        {"id": "N1", "type": "noria", "title": "Нория 1",
         "in": {"start": "DI.I0", "stop": "DI.I1", "speed": "DI.I2", "belt": "DI.I3", "reset": "DI.I4"},
         "out": {"run": "DQ.Q0"}, "params": {"start_delay_s": 5}, "src": "Э3 лист 7"},
        {"id": "C1", "type": "noria", "title": "Конвейер 1", "in": {"start": "DI.I5", "stop": "DI.I6"},
         "out": {"run": "DQ.Q1"}, "src": "Э3 лист 8"},
    ],
    "signals": [{"id": "EStop", "title": "Аварийный стоп", "dir": "in", "channel": "!DI.I9", "role": "estop"}],
    "routes": [{"id": "R1", "title": "Приём", "mechanisms": ["N1", "C1"]}],
}


def _spec(tmp_path, spec=None) -> Path:
    path = tmp_path / "_work" / "spec" / "project.spec.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec if spec is not None else SPEC, ensure_ascii=False), encoding="utf-8")
    return path


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


# ------------------------------------------------------------------------------------------- .gpc: что известно
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


def test_no_gpc_file_is_ever_written(tmp_path):
    """Даже когда экспорт идёт в ту же папку, файла .gpc не появляется: его пишет только Haiwell Happy."""
    _spec(tmp_path)
    got = hawell.export(_spec(tmp_path), tmp_path)
    assert got["ok"] is True
    assert not list(tmp_path.rglob("*.gpc")), "поддельный .gpc — потеря работы инженера"
    assert "закрытый формат" in got["format"]


# ----------------------------------------------------------------------------------- программа: инструкции и адреса
def test_the_program_is_exported_as_instructions_a_ladder_and_an_io_table(tmp_path):
    got = hawell.export(_spec(tmp_path), tmp_path)
    folder = tmp_path / "hawell"
    assert sorted(p.name for p in folder.iterdir()) == ["README.txt", "io.csv", "program.il", "program.ld.txt"]
    il = (folder / "program.il").read_text(encoding="utf-8")
    assert "OUT Y0" in il and "END" in il
    assert "Схема 1." in il and "Нория 1: пуск" in il
    assert got["rungs"] >= 4 and got["io"] >= 8


def test_only_instructions_haiwell_documents_are_written(tmp_path):
    """Мнемоники — из руководства Haiwell (Instruction set): выдуманная инструкция не соберётся в их среде."""
    hawell.export(_spec(tmp_path), tmp_path)
    il = (tmp_path / "hawell" / "program.il").read_text(encoding="utf-8")
    for line in il.splitlines():
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        ins = line.split()[0]
        assert ins in hawell.INSTRUCTIONS, f"инструкция {ins!r} не из набора Haiwell: {line!r}"


def test_a_mechanism_gets_start_stop_seal_in_and_its_own_output(tmp_path):
    """Пуск X0, самоблокировка выходом, стоп и авария — размыкающими, выход Y0. Это и есть схема пускателя."""
    hawell.export(_spec(tmp_path), tmp_path)
    il = (tmp_path / "hawell" / "program.il").read_text(encoding="utf-8")
    rung = il.split("Схема 1.", 1)[1].split("Схема 2.", 1)[0]
    lines = [line.split("//")[0].strip() for line in rung.splitlines()
             if line.strip() and line.split()[0] in hawell.INSTRUCTIONS]
    assert lines[0] == "LD  X0" and lines[1] == "OR  Y0"
    assert "ANI X1" in lines and "ANI X3" in lines
    assert lines[-1] == "OUT Y0"


def test_the_start_delay_goes_to_a_timer_and_a_data_register(tmp_path):
    hawell.export(_spec(tmp_path), tmp_path)
    il = (tmp_path / "hawell" / "program.il").read_text(encoding="utf-8")
    assert "TON T0, D0" in il
    assert "D0 = 50" in il, "5 с в Haiwell — 50 единиц по 0,1 с"


def test_every_signal_has_its_own_address_and_a_readable_table(tmp_path):
    got = hawell.export(_spec(tmp_path), tmp_path)
    rows = (tmp_path / "hawell" / "io.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0].split(";")[:4] == ["адрес", "область", "сигнал", "направление"]
    addresses = [row.split(";")[0] for row in rows[1:]]
    assert len(addresses) == len(set(addresses)), "один адрес на два сигнала — монтаж спалит выход"
    assert all(a[0] in "XYMTD" for a in addresses)
    assert got["addresses"]["in:N1:start"] == "X0" and got["addresses"]["out:N1:run"] == "Y0"


def test_what_was_written_reads_back(tmp_path):
    """Обратное чтение: адреса из таблицы, только известные инструкции. Это проверка, что файл живой, а не отчёт."""
    hawell.export(_spec(tmp_path), tmp_path)
    back = hawell.read_export(tmp_path)
    assert back["signals"] >= 8 and back["unknown_instructions"] == []
    assert back["addresses"]["X0"] == "N1.start"


def test_the_same_specification_gives_the_same_files(tmp_path):
    """Детерминированный экспорт: повтор — тот же файл, его видно в диффе и он не «шумит» в git."""
    first = tmp_path / "one"
    second = tmp_path / "two"
    for folder in (first, second):
        folder.mkdir()
        hawell.export(_spec(folder), folder)
    for name in ("program.il", "program.ld.txt", "io.csv", "README.txt"):
        assert (first / "hawell" / name).read_bytes() == (second / "hawell" / name).read_bytes(), name


def test_a_specification_without_mechanisms_is_an_honest_error(tmp_path):
    empty = {"project": {"name": "Пусто"}, "mechanisms": [], "signals": [], "routes": []}
    with pytest.raises(hawell.HawellError, match="нет механизмов"):
        hawell.export(_spec(tmp_path, empty), tmp_path)
    assert not (tmp_path / "hawell").exists()


def test_a_missing_specification_is_named(tmp_path):
    with pytest.raises(hawell.HawellError, match="нет файла спецификации"):
        hawell.export(tmp_path / "нет.json", tmp_path)


def test_the_notes_say_what_is_not_done_yet(tmp_path):
    """Датчик скорости и сброс аварии — то, что нельзя додумать за инженера: о них сказано в замечаниях."""
    spec = json.loads(json.dumps(SPEC))
    del spec["mechanisms"][0]["in"]["reset"]
    got = hawell.export(_spec(tmp_path, spec), tmp_path)
    said = " ".join(got["notes"])
    assert "датчик скорости" in said and "сброса аварии" in said


# ------------------------------------------------------------------------------------------------------- сервер
def test_the_server_says_which_environment_it_is():
    out = subprocess.run([sys.executable, str(KIT / "server.py")],
                         input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n",
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    got = json.loads(out.stdout.strip().splitlines()[0])["result"]
    assert got["serverInfo"] == {"name": "haiwell-happy", "title": "Haiwell Happy (.gpc, LD)", "version": "1.1.0"}
    assert "STL" in got["instructions"] and "закрытое сжатие" in got["instructions"]


def test_the_tools_read_a_gpc_and_export_a_program(tmp_path):
    p = _gpc(tmp_path / "Line.gpc")
    spec_file = _spec(tmp_path)
    info, check, prog, export, read = _server([
        ("hawell_info", {"path": str(p)}), ("hawell_check", {"path": str(p)}),
        ("hawell_program", {"spec_file": str(spec_file)}),
        ("hawell_export", {"spec_file": str(spec_file), "out_dir": str(tmp_path)}),
        ("hawell_read", {"out_dir": str(tmp_path)})])
    assert info["result"]["structuredContent"]["decoded"] is False
    assert check["result"]["structuredContent"]["summary"]["error"] == 0
    assert prog["result"]["structuredContent"]["il"].startswith("// Эталон")
    assert export["result"]["structuredContent"]["ok"] is True
    assert read["result"]["structuredContent"]["unknown_instructions"] == []
    assert (tmp_path / "hawell" / "program.il").is_file()
