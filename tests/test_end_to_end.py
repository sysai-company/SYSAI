"""Сквозная проверка без оборудования (T4): материалы → спецификация → программа ПЛК → проект Machine Expert →
экраны EasyBuilder → проверки. Один прогон, шаг за шагом.

Эталон REA (настоящие ТЗ и схемы) в репозитории не лежит — он у инженера. Здесь тот же путь на синтетическом
объекте (две норii и конвейер), чтобы цепочка была под тестом в CI; настоящие материалы прогоняются тем же
порядком вызовов на машине инженера (`scripts/e2e_reference.py`).

Что этот тест доказывает: спецификация проходит проверку, генератор пишет ST без ошибок, из ST собирается
`.project` Machine Expert, из основы — пустой проект панели, в него встаёт окно из донора и новый тег OPC UA,
и `cmtp_check` не находит ошибок. Чего он не доказывает: что проект открывается в Machine Expert и EasyBuilder —
это проверяется на Windows (`scripts/me_engine_wine.sh`, `scripts/ebpro_wine.sh`).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for seed in ("plc-kit", "ebpro-cmtp"):
    sys.path.insert(0, str(ROOT / "hub" / "seed" / seed))

import ebpcmtp  # noqa: E402
import ebpedit  # noqa: E402
import plcbuild  # noqa: E402
import plcgen  # noqa: E402
import plcproj  # noqa: E402
import plcspec  # noqa: E402
from test_hub_seed_ebpro import _menu_project  # noqa: E402
from test_hub_seed_plc_project import _template  # noqa: E402

SPEC = {
    "project": {"name": "Эталон", "controller": "TM241CE40R", "panel": "cMT3072X", "link": "opcua"},
    "expected": {"mechanisms": 2, "signals": 6},
    "types": {
        "noria": {"title": "Нория", "in": ["speed", "belt"], "out": ["run"], "faults": ["belt"], "pulse": ["speed"]},
        "conveyor": {"title": "Конвейер", "in": ["speed"], "out": ["run"], "faults": [], "pulse": ["speed"]},
    },
    "mechanisms": [
        {"id": "N1", "type": "noria", "title": "Нория 1", "in": {"speed": "DI.I0", "belt": "DI.I1"},
         "out": {"run": "DQ.Q0"}, "src": "Э3 лист 7"},
        {"id": "C1", "type": "conveyor", "title": "Конвейер 1", "in": {"speed": "DI.I2"}, "out": {"run": "DQ.Q1"},
         "src": "Э3 лист 8"},
    ],
    "signals": [{"id": "EStop", "title": "Аварийный стоп", "dir": "in", "channel": "!DI.I5", "role": "estop",
                 "src": "Э3 лист 2"}],
    "routes": [],
}


def test_the_whole_chain_from_specification_to_screens(tmp_path):
    steps = []

    # 1. Спецификация: то, что модель прочитала в ТЗ и схемах, — один файл, и он проверяется до кода.
    spec_file = tmp_path / "_work" / "spec" / "project.spec.json"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text(json.dumps(SPEC, ensure_ascii=False), encoding="utf-8")
    rep = plcspec.check(plcspec.load(str(spec_file)))
    assert not [i for i in rep["issues"] if i["level"] == "error"], rep["issues"]
    steps.append("спецификация: без ошибок")

    # 2. Программа: генератор пишет ST, каждая программа проверяется разбором.
    st = tmp_path / "_work" / "st"
    gen = plcgen.generate(str(spec_file), str(st))
    assert gen["written"], gen
    program = plcbuild.load_dir(str(st))          # разбирает и проверяет каждую программу, на ошибке бросает
    assert program.pous
    steps.append(f"программа: {len(gen['written'])} файлов, проверка без ошибок")

    # 3. Проект Machine Expert: из папки ST и шаблона контроллера.
    template = _template(tmp_path)
    out = tmp_path / "plc" / "Эталон.project"
    out.parent.mkdir()
    plcproj.create(program, str(template), str(out))
    assert out.exists() and out.stat().st_size > 0
    steps.append("проект Machine Expert: собран из шаблона")

    # 4. Экраны: пустой проект панели по основе, окно из донора, новый тег OPC UA.
    base = _menu_project()
    base_file = tmp_path / "base.cmtp"
    base.save(str(base_file))
    p = ebpcmtp.Project.load(str(base_file))
    r = ebpedit.new_project(p, start=0)
    assert not r["start"]["left"], r["start"]["left"]
    donor = _menu_project()
    donor_file = tmp_path / "donor.cmtp"
    donor.save(str(donor_file))
    got = ebpedit.import_window(p, str(donor_file), "Нория 1", name="Нория 1")
    assert got["number"] and p.window("Нория 1")
    assert ebpedit.add_tags(p, [{"name": "GVL.Start_1", "type": "BOOL"}]) == ["GVL.Start_1"]
    hmi = tmp_path / "hmi" / "Эталон.cmtp"
    hmi.parent.mkdir()
    p.save(str(hmi))
    steps.append("экраны: пустой проект, окно из донора, тег OPC UA")

    # 5. Проверки: проект панели читается обратно и не имеет ошибок.
    q = ebpcmtp.Project.load(str(hmi))
    assert q.window("Нория 1")["objects"]
    assert "GVL.Start_1" in [t["name"] for t in q.opcua_tags()]
    found = ebpedit.check(q)
    assert not [c for c in found if c["level"] == "error"], [c for c in found if c["level"] == "error"]
    steps.append(f"проверка экранов: ошибок нет, замечаний {len(found)}")

    assert len(steps) == 5
