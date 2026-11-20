"""Проект Haiwell Happy: `.gpc` — закрытый контейнер, но программа для Haiwell делается и без него.

Что проверено на настоящем проекте (`600_S1_Благовещенск_01A1_071223.gpc`, 51 942 байта) и на двух его версиях:
тело — не zlib, не lzma, не bz2, не zstd (проверено распаковщиками и zstd-ом), не XOR с ключом постоянной длины
(доля нулей после XOR со сдвигом не отличается от исходной), энтропия 7,06 бит/байт, общих ненулевых блоков у двух
версий одного проекта нет. То есть это закрытое сжатие или потоковый шифр вендора: писать `.gpc` мы не будем и
делать вид, что можем, тоже.

Но Haiwell Happy — среда с **документированным языком инструкций**: в руководстве (оно лежит внутри их же
установщика, `Instruction_set_stl_bit_t_c.htm`) у каждой инструкции в графе «Support language» стоят LD, FBD и IL,
а в самой программе LD переключается в STL по F7. Значит программу для контроллера Haiwell можно отдать списком
инструкций — это штатный язык этой среды, а не обходной путь. Поэтому инструмент делает то, что действительно
работает до конца:

    спецификация проекта (plc_spec) →  haw_export
        hawell/program.il    — программа списком инструкций (LD/AND/ANI/OR/OUT/TON/SET/RST …), с комментариями
        hawell/program.ld.txt— та же программа лестницей, чтобы рисовать в LD и сверять глазами
        hawell/io.csv        — таблица «сигнал → адрес X/Y/M/T/D», её заводят в таблице символов
        hawell/README.txt    — что сделать в Haiwell Happy, по шагам

Адресация — Haiwell: X (входы), Y (выходы), M (внутренние реле), T (таймеры), C (счётчики), D (регистры), номера
десятичные. Адреса выдаются детерминированно (по порядку механизмов и сигналов в спецификации), поэтому повторный
экспорт того же проекта даёт тот же файл — его видно в диффе.
"""
import csv
import io
import json
import math
import os
import pathlib
import re
import zlib

MAGIC = b"\xb0\xb0HaiWell"
LANGUAGE = "LD"
FOLDER = "hawell"
IL_MAX_BYTES = 1_000_000

# Инструкции, которые этот инструмент пишет (все — из руководства Haiwell Happy, «Instruction set»).
INSTRUCTIONS = ("LD", "LDI", "AND", "ANI", "OR", "ORI", "OUT", "SET", "RST", "TON", "TOF", "END")


class HawellError(ValueError):
    pass


def _path(path) -> pathlib.Path:
    p = pathlib.Path(str(path))
    if not p.is_file():
        raise HawellError(f"нет файла: {p}")
    return p


# ---------------------------------------------------------------------------------------------------- .gpc: что видно
def info(path) -> dict:
    """Что можно сказать о файле, не выдумывая: формат, размер, заголовок, энтропия тела."""
    p = _path(path)
    data = p.read_bytes()
    head = data[:16]
    magic = data[:len(MAGIC)] == MAGIC
    body = data[len(MAGIC):]
    counts = {}
    for b in body[:65536]:
        counts[b] = counts.get(b, 0) + 1
    total = sum(counts.values()) or 1
    entropy = -sum((n / total) * math.log2(n / total) for n in counts.values())
    streams = 0
    for i in range(max(0, len(body) - 2)):
        if body[i] == 0x78 and body[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                if len(zlib.decompressobj().decompress(body[i:i + 200000], 1 << 20)) > 200:
                    streams += 1
            except zlib.error:
                pass
    return {"path": str(p), "size": len(data), "magic": magic, "head": head.hex(),
            "environment": "Haiwell Happy", "language": LANGUAGE, "decoded": False,
            "entropy": round(entropy, 2), "zlib_streams": streams,
            "note": ("заголовок Haiwell прочитан; тело проекта не разобрано — закрытое сжатие вендора, не zlib. "
                     "Схему LD из .gpc прочитать нельзя и записать тоже. Программа для Haiwell делается из "
                     "спецификации списком инструкций: hawell_export"
                     if magic else "это не файл Haiwell Happy: нет заголовка b0 b0 HaiWell")}


def check(path) -> dict:
    """Что не так с файлом — по строке на находку, без догадок о содержимом."""
    one = info(path)
    issues = []
    if not one["magic"]:
        issues.append({"level": "error", "text": "нет заголовка «b0 b0 HaiWell» — это не проект Haiwell Happy"})
    if one["magic"] and one["size"] < 1024:
        issues.append({"level": "error", "text": f"файл слишком мал для проекта ({one['size']} байт)"})
    if one["magic"]:
        issues.append({"level": "info",
                       "text": "тело .gpc закрытое: схему LD из файла не прочитать, и записать .gpc тоже нельзя — "
                               "программа отдаётся списком инструкций (haw_export)"})
    return {"path": one["path"], "summary": {"error": sum(1 for i in issues if i["level"] == "error"),
                                             "warning": 0,
                                             "info": sum(1 for i in issues if i["level"] == "info")},
            "issues": issues, "info": one}


# ------------------------------------------------------------------------------------------ спецификация → программа
def _spec_name(spec: dict) -> str:
    return str((spec.get("project") or {}).get("name") or "проект")


def _mechanisms(spec: dict) -> list:
    mechs = spec.get("mechanisms") or []
    if not isinstance(mechs, list):
        raise HawellError("в спецификации mechanisms — не список")
    return [m for m in mechs if isinstance(m, dict) and m.get("id")]


def _kinds(spec: dict) -> dict:
    return spec.get("types") or {}


def _faults(spec: dict, mech: dict) -> list:
    kind = _kinds(spec).get(str(mech.get("type") or "")) or {}
    return [str(x) for x in (kind.get("faults") or [])]


def _title(spec: dict, mech: dict) -> str:
    return str(mech.get("title") or mech.get("id"))


class _Addresses:
    """Адреса Haiwell: X входы, Y выходы, M внутренние, T таймеры, C счётчики, D регистры. Номера десятичные,
    выдаются по порядку — повторный экспорт даёт тот же файл."""

    def __init__(self):
        self.used = {"X": 0, "Y": 0, "M": 0, "T": 0, "C": 0, "D": 0}
        self.by_signal = {}

    def take(self, area: str, key: str) -> str:
        if area not in self.used:
            raise HawellError(f"нет области адресов {area}")
        if key in self.by_signal:
            return self.by_signal[key]
        self.by_signal[key] = f"{area}{self.used[area]}"
        self.used[area] += 1
        return self.by_signal[key]


def _norm(name: str) -> str:
    return str(name or "").strip()


def _comment(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def build(spec: dict) -> dict:
    """Программа из спецификации: {rungs, io, addresses, notes}. Ничего не пишет."""
    mechs = _mechanisms(spec)
    if not mechs:
        raise HawellError("в спецификации нет механизмов (mechanisms) — программа пустая")
    addr = _Addresses()
    io_rows, rungs, notes = [], [], []

    # Входы: сначала каналы механизмов, потом отдельные сигналы спецификации — чтобы адреса не зависели от порядка
    # разделов в файле.
    for m in mechs:
        for name, ch in (m.get("in") or {}).items():
            addr.take("X", f"in:{m['id']}:{_norm(name)}")
    for sig in spec.get("signals") or []:
        if isinstance(sig, dict) and str(sig.get("dir") or "") == "in" and sig.get("id"):
            addr.take("X", f"signal:{_norm(sig['id'])}")
    for m in mechs:
        for name, ch in (m.get("out") or {}).items():
            addr.take("Y", f"out:{m['id']}:{_norm(name)}")

    for m in mechs:
        mid, title = str(m["id"]), _title(spec, m)
        ins = m.get("in") or {}
        outs = m.get("out") or {}
        faults = _faults(spec, m)
        for name in ins:
            key = f"in:{mid}:{_norm(name)}"
            role = "авария" if _norm(name) in faults else "вход"
            io_rows.append({"id": f"{mid}.{_norm(name)}", "address": addr.by_signal[key],
                            "area": addr.by_signal[key][:1], "role": role, "dir": "вход",
                            "comment": _comment(_signal_title(spec, m, name))})
        for name in outs:
            key = f"out:{mid}:{_norm(name)}"
            io_rows.append({"id": f"{mid}.{_norm(name)}", "address": addr.by_signal[key],
                            "area": addr.by_signal[key][:1], "role": "выход", "dir": "выход",
                            "comment": _comment(_signal_title(spec, m, name))})
        run = addr.by_signal.get(f"out:{mid}:run") or next(
            (addr.by_signal[k] for k in addr.by_signal if k.startswith(f"out:{mid}:")), None)
        if not run:
            notes.append(f"{mid}: у механизма нет выходов (out) — нечего включать, схема не собрана")
            continue
        mem_run = addr.take("M", f"state:{mid}:run")          # «механизм включён»
        run_lines, ladder = [], []
        start_keys = [k for k in ins if k in ("start", "local_start")]
        stop_keys = [k for k in ins if k in ("stop", "local_stop")]
        fault_keys = [k for k in ins if _norm(k) in faults]
        if not start_keys:
            notes.append(f"{mid}: нет входа пуска (start/local_start) — включение только из маршрута, "
                         "схема собрана по общему пуску маршрута")
        first = True
        for k in start_keys:
            a = addr.by_signal[f"in:{mid}:{_norm(k)}"]
            run_lines.append(_line("LD" if first else "OR", a, _signal_title(spec, m, k)))
            ladder.append(("LD" if first else "OR", a, _signal_title(spec, m, k)))
            first = False
        if not first:  # самоблокировка: выход держит себя сам
            run_lines.append(_line("OR", run, f"{title}: самоблокировка"))
            ladder.append(("OR", run, f"{title}: самоблокировка"))
        for k in fault_keys + [k for k in stop_keys if k not in fault_keys]:
            a = addr.by_signal[f"in:{mid}:{_norm(k)}"]
            if _norm(k) in faults:
                run_lines.append(_line("ANI", a, _signal_title(spec, m, k, fault=True)))
                ladder.append(("ANI", a, _signal_title(spec, m, k, fault=True)))
            else:
                run_lines.append(_line("ANI", a, _signal_title(spec, m, k)))
                ladder.append(("ANI", a, _signal_title(spec, m, k)))
        if first:  # ни одного пуска: включаем по внутреннему реле, которое ставит маршрут
            run_lines.append(_line("LD", mem_run, f"{title}: включение из маршрута"))
            ladder.append(("LD", mem_run, f"{title}: включение из маршрута"))
        run_lines.append(_line("OUT", run, f"{title}: работа"))
        ladder.append(("OUT", run, f"{title}: работа"))
        rungs.append({"n": len(rungs) + 1, "title": f"{title} — пуск/стоп", "il": run_lines, "ladder": ladder,
                      "comment": _where(m)})

        delay = _delay_s(m)
        if delay:
            t = addr.take("T", f"timer:{mid}:start")
            d = addr.take("D", f"data:{mid}:start")
            rungs.append({"n": len(rungs) + 1, "title": f"{title} — задержка пуска {delay:g} с",
                          "il": [_line("LD", run, f"{title}: пошёл"),
                                 _line("TON", f"{t}, {d}", f"задержка {delay:g} с: {d} — 0,1 с на единицу"),
                                 _line("LD", t, f"{title}: время вышло"),
                                 _line("OUT", mem_run, f"{title}: работает после задержки")],
                          "ladder": [("LD", run, f"{title}: пошёл"), ("TON", f"{t}, {d}", f"задержка {delay:g} с"),
                                     ("LD", t, "время вышло"), ("OUT", mem_run, f"{title}: работает")],
                          "comment": f"{d} = {int(round(delay * 10))} (0,1 с на единицу)"})
        pulses = [k for k in ins if _norm(k) == "speed"]
        if pulses:
            notes.append(f"{mid}: датчик скорости ({addr.by_signal['in:' + mid + ':speed']}) в этой схеме не "
                         "участвует — контроль вращения и завал делаются защитой по месту или в маршруте")
        if fault_keys:
            latch = addr.take("M", f"fault:{mid}")
            reset = addr.by_signal.get(f"in:{mid}:reset")
            latch_il = [_line("LD", addr.by_signal["in:" + mid + ":" + _norm(fault_keys[0])],
                              _signal_title(spec, m, fault_keys[0], fault=True)),
                        _line("OR", latch, "самоблокировка аварии")]
            latch_ld = [("LD", addr.by_signal["in:" + mid + ":" + _norm(fault_keys[0])],
                         _signal_title(spec, m, fault_keys[0], fault=True)),
                        ("OR", latch, "самоблокировка аварии")]
            if reset:
                latch_il.append(_line("ANI", reset, "сброс аварии оператором"))
                latch_ld.append(("ANI", reset, "сброс аварии оператором"))
            else:
                notes.append(f"{mid}: входа сброса аварии (reset) нет — авария держится до перезапуска программы, "
                             "кнопку сброса стоит завести в спецификации")
            latch_il.append(_line("OUT", latch, f"{title}: авария"))
            latch_ld.append(("OUT", latch, f"{title}: авария"))
            rungs.append({"n": len(rungs) + 1, "title": f"{title} — авария (защёлка)", "il": latch_il,
                          "ladder": latch_ld,
                          "comment": "снять аварию — кнопкой сброса" if reset else "сброс не заведён"})

    for sig in spec.get("signals") or []:
        if not isinstance(sig, dict) or not sig.get("id"):
            continue
        key = f"signal:{_norm(sig['id'])}"
        if key in addr.by_signal:
            io_rows.append({"id": _norm(sig["id"]), "address": addr.by_signal[key],
                            "area": addr.by_signal[key][:1],
                            "role": str(sig.get("role") or "сигнал"),
                            "dir": "вход" if str(sig.get("dir")) == "in" else str(sig.get("dir") or ""),
                            "comment": _comment(sig.get("title"))})
    if not any(r["il"][-1].startswith("OUT") for r in rungs):
        notes.append("нет ни одного выхода: программа ничего не включает")
    return {"project": _spec_name(spec), "rungs": rungs, "io": io_rows, "notes": notes,
            "addresses": {k: v for k, v in addr.by_signal.items()}}


def _where(mech: dict) -> str:
    return _comment(mech.get("src") or "")


def _delay_s(mech: dict) -> float:
    for name, value in (mech.get("params") or {}).items():
        if str(name).endswith("_delay_s"):
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _signal_title(spec: dict, mech: dict, name: str, fault: bool = False) -> str:
    """Подпись сигнала: «Нория 1: лента — авария» — по имени поля, словами инженера."""
    russian = {"start": "пуск", "stop": "стоп", "local_stop": "местный стоп", "local_start": "местный пуск",
               "speed": "датчик скорости", "belt": "лента", "plug": "завал", "vfd_ready": "готовность ПЧ",
               "run": "работа", "reset": "сброс аварии", "hmi_start": "пуск с панели"}
    key = _norm(name)
    said = f"{_title(spec, mech)}: {russian.get(key, key)}"
    return f"{said} — авария" if fault else said


def _why(text: str) -> str:
    said = _comment(text)
    return f"   // {said}" if said else ""


def _line(ins: str, arg: str, why: str) -> str:
    """Одна инструкция: мнемоника, операнд, комментарий — колонками, чтобы файл читался глазами."""
    said = _comment(why)
    return f"{ins:<4}{arg:<9}" + (f"// {said}" if said else "")


# ---------------------------------------------------------------------------------------------------- запись файлов
def il_text(prog: dict) -> str:
    out = [f"// {prog['project']} — программа для Haiwell Happy (язык инструкций, STL).",
           "// Адреса: X — входы, Y — выходы, M — внутренние реле, T — таймеры, D — регистры (числа десятичные).",
           "// Переключение LD/STL в Haiwell Happy: F7. Петля: схему собрать по program.ld.txt,",
           "// список инструкций вставить в окно STL, затем «Проверка» (F9) и компиляция.",
           ""]
    for r in prog["rungs"]:
        out.append(f"// ---- Схема {r['n']}. {r['title']}" + (f"  ({r['comment']})" if r["comment"] else ""))
        out.extend(r["il"])
        out.append("")
        if r["n"] == 1:
            pass
    out.append("END")
    text = "\n".join(out) + "\n"
    if len(text.encode("utf-8")) > IL_MAX_BYTES:
        raise HawellError(f"программа больше {IL_MAX_BYTES} байт — разделите проект на части")
    return text


def ladder_text(prog: dict) -> str:
    """Лестница текстом: по ней собирают LD, если STL не подходит. Контакты `] [` — замыкающий, `] / [` — размыкающий."""
    out = [f"{prog['project']} — схема."]
    for r in prog["rungs"]:
        out.append("")
        out.append(f"Схема {r['n']}. {r['title']}")
        for kind, arg, why in r["ladder"]:
            if kind == "OUT":
                out.append(f"  |----------------------------------------------( ) {arg:<6} {why}")
            elif kind == "TON":
                out.append(f"  |-----------------------------------------[TON {arg}] {why}")
            elif kind == "ANI":
                out.append(f"  |---]/[--- {arg:<6} {why}")
            elif kind == "OR":
                out.append(f"  +---] [--- {arg:<6} {why}")
            else:
                out.append(f"  |---] [--- {arg:<6} {why}")
        out.append("  |")
    return "\n".join(out) + "\n"


def io_csv(prog: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["адрес", "область", "сигнал", "направление", "роль", "комментарий"])
    for row in prog["io"]:
        w.writerow([row["address"], row["area"], row["id"], row["dir"], row["role"], row["comment"]])
    return buf.getvalue()


def readme_text(prog: dict) -> str:
    areas = {}
    for row in prog["io"]:
        areas[row["area"]] = areas.get(row["area"], 0) + 1
    said = ", ".join(f"{k} — {n}" for k, n in sorted(areas.items()))
    return f"""{prog['project']} — программа для Haiwell Happy

Что в папке:
  program.il    программа списком инструкций (STL) — основной файл
  program.ld.txt та же программа лестницей: по ней собирают LD, ею же сверяют
  io.csv        таблица сигналов и адресов ({said or 'пусто'})
  README.txt    этот файл

Что сделать в Haiwell Happy (5 шагов):
  1. Новый проект: File → New, выбрать контроллер и панель, которые стоят на объекте.
  2. Таблица символов: открыть таблицу символов и завести имена из io.csv с теми же адресами
     (X — входы, Y — выходы, M — внутренние реле, T — таймеры, D — регистры; числа десятичные).
  3. Программа: открыть программу и переключить LD ↔ STL клавишей F7, вставить текст program.il
     (или собрать схему по program.ld.txt, если нужен рисунок для проверки глазами).
  4. Проверка: F9 (компиляция). Ошибок быть не должно; замечания — по строкам, которые Haiwell покажет.
  5. Записать в контроллер (On-line control PLC) и сохранить проект: File → Save, файл .gpc.

Важно, честно:
  · .gpc пишется только самим Haiwell Happy: формат закрытый (сжатие вендора), и этот инструмент его не пишет.
    Поэтому последний шаг — сохранение в программе, а не файл с нашей стороны.
  · Задержка пуска задаётся в D-регистрах (0,1 с на единицу) — значения указаны в комментариях к схемам.
  · Схемы собраны по спецификации проекта: адреса входов и выходов выданы по порядку, их надо свести с
    монтажом (какой провод куда) — это делает инженер на объекте.

Замечания по спецификации:
{chr(10).join('  · ' + n for n in prog['notes']) if prog['notes'] else '  · нет'}
"""


def export(spec_file, out_dir) -> dict:
    """Пишет папку hawell/ из спецификации проекта. Возвращает, что записано и с какими замечаниями."""
    spec_path = pathlib.Path(str(spec_file))
    if not spec_path.is_file():
        raise HawellError(f"нет файла спецификации: {spec_path} (его делает plc_spec)")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise HawellError(f"спецификация не читается как JSON: {exc}") from exc
    prog = build(spec)
    folder = pathlib.Path(str(out_dir)) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    files = {"program.il": il_text(prog), "program.ld.txt": ladder_text(prog), "io.csv": io_csv(prog),
             "README.txt": readme_text(prog)}
    written = []
    for name, text in files.items():
        with open(folder / name, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(str(folder / name))
    return {"ok": True, "folder": str(folder), "files": written, "rungs": len(prog["rungs"]),
            "io": len(prog["io"]), "addresses": prog["addresses"], "notes": prog["notes"],
            "format": (".gpc — закрытый формат Haiwell: он не пишется и не читается (только заголовок). "
                       "Программа отдана списком инструкций — это штатный язык Haiwell Happy (LD ↔ STL, F7)")}


def read_export(out_dir) -> dict:
    """Обратное чтение того, что записали: адреса и сигналы из io.csv — чтобы проверить, что файл читается."""
    folder = pathlib.Path(str(out_dir)) / FOLDER
    csv_file = folder / "io.csv"
    if not csv_file.is_file():
        raise HawellError(f"нет {csv_file}: сначала haw_export")
    rows = []
    with open(csv_file, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            rows.append(row)
    seen = {}
    for row in rows:
        address = row.get("адрес") or ""
        if not re.fullmatch(r"[XYMTCD]\d{1,5}", address):
            raise HawellError(f"адрес не по правилам Haiwell: {address!r} у сигнала {row.get('сигнал')}")
        if address in seen:
            raise HawellError(f"адрес {address} у двух сигналов: {seen[address]} и {row.get('сигнал')}")
        seen[address] = row.get("сигнал")
    il = (folder / "program.il").read_text(encoding="utf-8") if (folder / "program.il").is_file() else ""
    unknown = [line for line in il.splitlines()
               if line and not line.startswith("//") and line.split()[0] not in INSTRUCTIONS]
    return {"folder": str(folder), "signals": len(rows), "addresses": seen, "il_lines": len(il.splitlines()),
            "unknown_instructions": unknown[:10]}
