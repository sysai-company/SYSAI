"""Проект Haiwell Happy (`.gpc`) — что о нём известно на самом деле.

Haiwell Happy — среда программирования контроллеров Haiwell, язык только LD (релейные схемы). Проект лежит в
одном файле `.gpc`, и файл закрытый: заголовок читается, тело — нет.

Что проверено на настоящем проекте (`600_S1_Благовещенск_01A1_071223.gpc`, 51 942 байта):

* первые байты — `b0 b0` и строка `HaiWell`, дальше двоичный заголовок;
* zlib-потоков в файле нет, а энтропия тела 7,06 бит/байт — то есть это не «сжатый zip», а свой формат;
* в теле повторяются короткие последовательности байт с общим хвостом — похоже на шифр или на своё сжатие со
  словарём; побайтовым XOR не снимается (проверено: ни один ключ не даёт текста).

Поэтому инструмент честно говорит «заголовок прочитан, тело не разобрано» и файлов не пишет. Когда разбор
появится, он появится здесь, а не в `plc-kit`: Haiwell — отдельная среда, и путать её с Machine Expert нельзя.
"""
import math
import pathlib
import zlib

MAGIC = b"\xb0\xb0HaiWell"
LANGUAGE = "LD"


class HawellError(ValueError):
    pass


def _path(path) -> pathlib.Path:
    p = pathlib.Path(str(path))
    if not p.is_file():
        raise HawellError(f"нет файла: {p}")
    return p


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
            "note": ("заголовок Haiwell прочитан; тело проекта не разобрано — своего формата, не zlib. "
                     "Прочитать схему LD из него пока нельзя: нужен разбор тела (см. TOOL.md, «Ошибки»)"
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
                       "text": "тело проекта не разобрано: схему LD из него прочитать нельзя, и записать тоже"})
    return {"path": one["path"], "summary": {"error": sum(1 for i in issues if i["level"] == "error"),
                                             "warning": 0,
                                             "info": sum(1 for i in issues if i["level"] == "info")},
            "issues": issues, "info": one}


def export(*_args, **_kwargs):
    """Запись проекта Haiwell пока невозможна — честный отказ вместо похожего файла."""
    raise HawellError("формат .gpc не разобран: записать проект Haiwell Happy нельзя. Читается только заголовок "
                      "(hawell_info) — тело файла своего формата, не zlib; нужен разбор тела")
