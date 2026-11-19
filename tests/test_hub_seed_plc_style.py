"""hub/seed/plc-kit/plcstyle.py — стиль проекта как именованный профиль, и генерация в этом стиле.

Стиль — это манера, а не смысл: регистр имён, суффикс классов, группы глобального списка, плотность и язык
комментариев. Тесты доказывают, что

* профиль готового проекта сохраняется под именем, читается обратно и виден в списке;
* спецификация переписывается в манере стиля целиком — механизмы, их блокировки, маршруты и глобальные сигналы
  переименовываются вместе, поэтому ссылки не разъезжаются;
* расхождение проекта со стилем видно (compare), а не тонет;
* сервер отдаёт это инструментами plc_style_save / plc_style_list / plc_style_show и принимает style у plc_generate.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parent.parent / "hub" / "seed" / "plc-kit"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "me_engine_samples.project"
sys.path.append(str(SEED))
import plcstyle  # noqa: E402

PROFILE = {
    "project": "Vendor", "controller": "TM241CE40R",
    "programs": [{"name": "Main", "language": "ST", "lines": 40, "in_task": True, "calls_instances": 3, "role": "main"}],
    "classes": [{"name": "Noria_class", "language": "ST", "inputs": ["run"], "outputs": ["on"], "instances": ["Noria_1"]}],
    "groups": [{"name": "Нории", "variables": 12, "addressed": 0}, {"name": "Общее", "variables": 4, "addressed": 4}],
    "naming": {"case": "snake_case", "class_suffix": "_class",
               "comments": {"share": 0.8, "russian": True}},
}

SPEC = {
    "project": {"name": "Line", "controller": "TM241CE40R", "panel": "cMT3072X", "link": "opcua", "template": ""},
    "expected": {"mechanisms": 2, "signals": 5},
    "types": {"noria": {"title": "Нория", "in": ["speed"], "out": ["run"], "fb": "FB_Noria"}},
    "mechanisms": [
        {"id": "Noria1", "type": "noria", "title": "Нория 1", "src": "Э3",
         "in": {"speed": "DI.I0"}, "out": {"run": "DQ.Q0"}, "interlocks": {"after": "Conveyor1"}},
        {"id": "Conveyor1", "type": "noria", "title": "Конвейер 1", "src": "Э3",
         "in": {"speed": "DI.I1"}, "out": {"run": "DQ.Q1"}},
    ],
    "signals": [{"id": "StartAll", "dir": "in", "channel": "DI.I2", "title": "Пуск всех"}],
    "routes": [{"id": "Line1", "title": "Линия", "mechanisms": ["Noria1", "Conveyor1"]}],
}


def test_a_profile_is_saved_under_a_name_and_read_back(tmp_path):
    got = plcstyle.save(PROFILE, "Vendor", "пример вендора", str(tmp_path))
    assert got["name"] == "Vendor" and Path(got["file"]).is_file()
    assert plcstyle.load("Vendor", str(tmp_path))["project"] == "Vendor"
    rows = plcstyle.listing(str(tmp_path))
    assert [r["name"] for r in rows] == ["Vendor"]
    assert rows[0]["case"] == "snake_case" and rows[0]["class_suffix"] == "_class"
    assert rows[0]["note"] == "пример вендора"


def test_a_missing_style_says_so_instead_of_returning_an_empty_profile(tmp_path):
    with pytest.raises(plcstyle.StyleError, match="нет"):
        plcstyle.load("Нет такого", str(tmp_path))


def test_a_file_that_is_not_a_style_is_refused(tmp_path):
    (tmp_path / "чужой.json").write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(plcstyle.StyleError, match="не файл стиля"):
        plcstyle.load("чужой", str(tmp_path))
    assert plcstyle.listing(str(tmp_path)) == []


def test_the_spec_is_rewritten_in_the_style_and_every_reference_follows():
    spec, changes = plcstyle.apply_to_spec(SPEC, PROFILE)
    ids = [m["id"] for m in spec["mechanisms"]]
    assert ids == ["noria1", "conveyor1"]                       # snake_case, как в стиле
    assert spec["mechanisms"][0]["interlocks"]["after"] == "conveyor1"   # блокировка едет вместе
    assert spec["routes"][0]["mechanisms"] == ["noria1", "conveyor1"]      # маршрут тоже
    assert spec["signals"][0]["id"] == "startall"
    assert spec["types"]["noria"]["fb"] == "FB_Noria_class"              # суффикс классов стиля
    assert len(changes) == 4
    assert SPEC["mechanisms"][0]["id"] == "Noria1"              # исходная спецификация не тронута


def test_a_style_without_naming_rules_changes_nothing():
    spec, changes = plcstyle.apply_to_spec(SPEC, {"project": "Пустой", "naming": {}})
    assert changes == [] and spec == SPEC


def test_a_project_that_departs_from_the_style_is_reported():
    other = {"project": "Свой", "naming": {"case": "CamelCase", "class_suffix": "",
                                           "comments": {"share": 0.1, "russian": False}},
             "groups": [{"name": "Другое", "variables": 1, "addressed": 0}]}
    issues = plcstyle.compare(other, PROFILE)
    texts = " ".join(i["text"] for i in issues)
    assert "snake_case" in texts and "CamelCase" in texts
    assert any(i["where"] == "комментарии" for i in issues)
    assert any(i["where"] == "группы" for i in issues)
    assert plcstyle.compare(PROFILE, PROFILE) == []


def _server(calls) -> list:
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})]
    lines += [json.dumps({"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call",
                          "params": {"name": n, "arguments": a}}) for i, (n, a) in enumerate(calls)]
    out = subprocess.run([sys.executable, str(SEED / "server.py")], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, timeout=180, encoding="utf-8").stdout.splitlines()
    return [json.loads(x)["result"] for x in out][1:]


def test_the_server_saves_lists_and_shows_a_style(tmp_path):
    saved, listed, shown = _server([
        ("plc_style_save", {"path": str(FIXTURE), "name": "Движок", "note": "фикстура", "folder": str(tmp_path)}),
        ("plc_style_list", {"folder": str(tmp_path)}),
        ("plc_style_show", {"name": "Движок", "folder": str(tmp_path)}),
    ])
    assert "сохранён" in saved["content"][0]["text"]
    assert saved["structuredContent"]["name"] == "Движок"
    assert [s["name"] for s in listed["structuredContent"]["styles"]] == ["Движок"]
    assert "Движок" in shown["content"][0]["text"] or "me_engine_samples" in shown["content"][0]["text"]


def test_the_server_generates_in_the_saved_style(tmp_path):
    spec = tmp_path / "project.spec.json"
    spec.write_text(json.dumps(SPEC, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "st"
    out.mkdir(parents=True, exist_ok=True)
    (out / "FB_Noria_class.st").write_text(          # класс в манере стиля: суффикс _class
        "FUNCTION_BLOCK FB_Noria_class\nVAR_INPUT\n\tspeed: BOOL;\nEND_VAR\nVAR_OUTPUT\n\trun: BOOL;\nEND_VAR\n\nrun := speed;\n",
        encoding="utf-8")
    plcstyle.save(PROFILE, "Vendor", "", str(tmp_path / "styles"))
    got = _server([("plc_generate", {"spec_file": str(spec), "out_dir": str(out),
                                     "style": "Vendor", "style_folder": str(tmp_path / "styles")})])[0]
    assert "ошибок 0" in got["content"][0]["text"]
    assert got["structuredContent"]["style"]["name"] == "Vendor"
    mechs = (out / "Mechs.st").read_text(encoding="utf-8")
    assert "noria1" in mechs and "Noria1" not in mechs      # имена в манере стиля


def test_the_formats_separate_the_plc_from_the_panel():
    """ПЛК и панель — разные вещи: Machine Expert и Haiwell это программа, ONI и EasyBuilder это экраны."""
    got = _server([("plc_formats", {})])[0]
    fmts = {f["id"]: f for f in got["structuredContent"]["formats"]}
    assert {k for k, f in fmts.items() if f["kind"] == "plc"} == {"me", "hawell"}
    assert {k for k, f in fmts.items() if f["kind"] == "hmi"} == {"oni", "easybuilder"}
    assert fmts["me"]["read"] and fmts["me"]["write"] and fmts["me"]["icon"].endswith("format-me.svg")
    assert fmts["oni"]["read"] is True and fmts["oni"]["write"] is False   # экраны читаем, писать ещё нет
    assert fmts["hawell"]["read"] is False and fmts["hawell"]["write"] is False
    assert "LD и ST" in fmts["me"]["note"] and "только LD" in fmts["hawell"]["note"]


def test_a_panel_format_offers_the_screen_resolutions():
    """Панели разные: разрешение — выбор инженера, а не константа в коде."""
    got = _server([("plc_formats", {"kind": "hmi"})])[0]
    fmts = got["structuredContent"]["formats"]
    assert [f["id"] for f in fmts] == ["oni", "easybuilder"]
    ids = [r["id"] for r in fmts[0]["resolutions"]]
    assert ids[:3] == ["800x480", "1024x600", "1024x768"] and "1920x1080" in ids
    assert all({"id", "w", "h", "title"} <= set(r) for r in fmts[0]["resolutions"])
    assert "resolutions" not in _server([("plc_formats", {"kind": "plc"})])[0]["structuredContent"]["formats"][0]


def test_a_format_we_cannot_write_writes_nothing_and_says_why(tmp_path):
    out = tmp_path / "x.oni"
    got = _server([("plc_export", {"format": "oni", "src_dir": str(tmp_path), "out_file": str(out)})])[0]
    assert got.get("isError") is True
    assert "ещё не разобран" in got["content"][0]["text"] or "не разобран" in got["content"][0]["text"]
    assert not out.exists()
