#!/usr/bin/env python3
"""Сквозная проверка проекта без оборудования (T4): материалы → спецификация → программа ПЛК → проект Machine
Expert → экраны EasyBuilder → проверки. Один прогон, шаг за шагом, отчёт в `_work/reports/e2e.md`.

    python scripts/e2e_reference.py <папка проекта> [--template <шаблон .project>] [--base <основа .cmtp>]

Папка проекта — та, что открыта агенту: `materials/`, `_work/spec/project.spec.json`, `plc/`, `hmi/`.
`--template` — проект Machine Expert с контроллером и модулями (по умолчанию `_work/templates/*.project`).
`--base` — проект EasyBuilder в стиле компании (по умолчанию `_work/templates/*.cmtp`).

Что проверяется: спецификация без ошибок, генератор пишет ST, из ST собирается `.project`, из основы — пустой
проект панели, `cmtp_check` не находит ошибок. Чего скрипт не проверяет: что файлы открываются в Machine Expert
и EasyBuilder — это на Windows (`scripts/me_engine_wine.sh`, `scripts/ebpro_wine.sh`).
"""
import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for seed in ("plc-kit", "ebpro-cmtp"):
    sys.path.insert(0, str(ROOT / "hub" / "seed" / seed))

import ebpcmtp  # noqa: E402
import ebpedit  # noqa: E402
import plcbuild  # noqa: E402
import plcgen  # noqa: E402
import plcproj  # noqa: E402
import plcspec  # noqa: E402


def _first(pattern: str) -> str:
    found = sorted(glob.glob(pattern))
    return found[0] if found else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Сквозная проверка проекта без оборудования")
    ap.add_argument("project", help="папка проекта (materials/, _work/spec/project.spec.json)")
    ap.add_argument("--template", default="", help="проект Machine Expert с контроллером (шаблон)")
    ap.add_argument("--base", default="", help="проект EasyBuilder в стиле компании (основа)")
    ap.add_argument("--keep", action="append", default=[], help="окна основы, которые оставить (имя или номер)")
    args = ap.parse_args()

    root = Path(args.project).resolve()
    if not root.is_dir():
        print(f"нет папки {root}", file=sys.stderr)
        return 2
    spec_file = root / "_work" / "spec" / "project.spec.json"
    template = args.template or _first(str(root / "_work" / "templates" / "*.project"))
    base = args.base or _first(str(root / "_work" / "templates" / "*.cmtp")) or _first(str(root / "_work" / "templates" / "*.emtp"))
    steps, failed = [], 0

    def step(name: str, ok: bool, note: str = "") -> None:
        nonlocal failed
        steps.append({"step": name, "ok": ok, "note": note})
        print(f"{'✓' if ok else '✗'} {name}" + (f" — {note}" if note else ""))
        if not ok:
            failed += 1

    # 1. Спецификация
    if not spec_file.is_file():
        step("спецификация", False, f"нет {spec_file} — сначала plc_spec_new и разбор материалов")
    else:
        rep = plcspec.check(plcspec.load(str(spec_file)))
        errors = [i for i in rep["issues"] if i["level"] == "error"]
        step("спецификация", not errors, f"ошибок {len(errors)}, замечаний {len(rep['issues']) - len(errors)}")
        for e in errors[:5]:
            print(f"    {e['where']}: {e['text']}")

    # 2. Программа
    st = root / "_work" / "st"
    program = None
    if spec_file.is_file():
        try:
            gen = plcgen.generate(str(spec_file), str(st))
            program = plcbuild.load_dir(str(st))
            step("программа", True, f"{len(gen['written'])} файлов, разбор без ошибок")
        except Exception as exc:  # noqa: BLE001 — отчёт важнее типа
            step("программа", False, str(exc))

    # 3. Проект Machine Expert
    if program is not None and template:
        out = root / "plc" / f"{program.name}.project"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            rep = plcproj.create(program, template, str(out), overwrite=True)
            step("проект Machine Expert", True, f"{out.name}, {rep.get('bytes', 0)} байт")
        except Exception as exc:  # noqa: BLE001
            step("проект Machine Expert", False, str(exc))
    elif program is not None:
        step("проект Machine Expert", False, "нет шаблона .project (--template или _work/templates/*.project)")

    # 4. Экраны
    if base:
        try:
            p = ebpcmtp.Project.load(base)
            numbers = [w["number"] for w in p.windows()]
            start = ebpedit.SYSTEM_WINDOWS if ebpedit.SYSTEM_WINDOWS in numbers else numbers[0]
            r = ebpedit.new_project(p, keep=args.keep, start=start)
            hmi = root / "hmi" / f"{root.name}.cmtp"
            hmi.parent.mkdir(parents=True, exist_ok=True)
            p.save(str(hmi))
            step("экраны", True, f"{hmi.name}: окон {len(p.windows())}, удалено {len(r['deleted'])}, "
                                 f"уведено за окно {len(r['start']['hidden'])}")
        except Exception as exc:  # noqa: BLE001
            step("экраны", False, str(exc))
    else:
        step("экраны", False, "нет основы .cmtp (--base или _work/templates/*.cmtp)")

    # 5. Проверка экранов
    hmi = root / "hmi" / f"{root.name}.cmtp"
    if hmi.is_file():
        q = ebpcmtp.Project.load(str(hmi))
        found = ebpedit.check(q)
        errors = [c for c in found if c["level"] == "error"]
        step("проверка экранов", not errors, f"ошибок {len(errors)}, замечаний {len(found) - len(errors)}")
        for c in errors[:5]:
            print(f"    окно {c['window']} #{c['object']}: {c['text']}")

    report = root / "_work" / "reports" / "e2e.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Сквозная проверка — {root.name}", "", f"Когда: {time.strftime('%Y-%m-%d %H:%M')}", "",
             "| шаг | итог | что вышло |", "|---|---|---|"]
    lines += [f"| {s['step']} | {'✓' if s['ok'] else '✗'} | {s['note']} |" for s in steps]
    lines += ["", "Открытие в Machine Expert и EasyBuilder проверяется на Windows: "
                  "`scripts/me_engine_wine.sh`, `scripts/ebpro_wine.sh`.", ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nотчёт: {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
