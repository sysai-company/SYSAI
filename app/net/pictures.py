"""Пак картинок оборудования в хранилище: индекс строится при первом подключении и живёт рядом с паком.

Пак — папка хранилища (по умолчанию «Общее/Картинки»). Индекс — файл `_index.json` в той же папке: что где лежит,
что это за механизм (нория, муз, шнек, триер…), какие у него состояния и сколько их (3, 4, 5 — сколько есть на
самом деле), чем состояния отличаются. Агент сначала ищет картинку здесь и только потом рисует свою.

Правила разбора имён — те же, что у `pic-index` на ПК инженера (`hub/seed/pic-index/picindex.py`): один пак
понимается одинаково и в хранилище, и в локальной папке.
"""
import json
import os
import sys

from .. import config
from . import files

PACK = "Общее/Картинки"
INDEX_NAME = "_index.json"
MAX_PICTURES = 20000


class PicturesError(Exception):
    pass


def _picindex():
    """The picture index of the hub seed, imported once: the same rules as on the engineer's PC."""
    if "picindex" not in sys.modules:
        seed = os.path.join(str(config.BASE_DIR.parent), "hub", "seed", "pic-index")
        if seed not in sys.path:
            sys.path.insert(0, seed)
    import picindex
    return picindex


def _walk(rights, folder: str, depth: int = 0) -> list:
    """Every file of the pack, folders first: [{path, name, size}] — pictures only, the index itself skipped."""
    if depth > 12:
        return []
    out = []
    try:
        got = files.listing(rights, folder, limit=MAX_PICTURES)
    except files.FilesError:
        return out
    for item in got.get("items") or []:
        if item.get("is_folder"):
            out.extend(_walk(rights, item["path"], depth + 1))
        elif item.get("name") != INDEX_NAME:
            out.append({"path": item["path"], "name": item["name"], "size": item.get("size") or 0})
    return out


def build(rights, folder: str = PACK) -> dict:
    """Read the pack and write its index next to it. -> {index, stats}"""
    pic = _picindex()
    rows, skipped = [], []
    for one in _walk(rights, folder):
        if os.path.splitext(one["name"])[1].lower() not in pic.EXTENSIONS:
            continue
        try:
            found = files.blob(rights, one["path"])
            data = files.read_bytes(found["stored"], limit=pic.MAX_FILE_BYTES + 1)
        except (files.FilesError, OSError):
            skipped.append(one["path"])
            continue
        if len(data) > pic.MAX_FILE_BYTES:
            skipped.append(one["path"])
            continue
        rel = one["path"][len(folder):].lstrip("/") if one["path"].startswith(folder) else one["path"]
        rows.append(pic.record_of(rel, data))
    index = pic.index_of(rows)
    sets = pic.sets_of(index["pictures"])
    stats = {"folder": folder, "pictures": len(index["pictures"]), "sets": len(sets),
             "equipment": len({s["equipment"] for s in sets if s["equipment"]}),
             "unrecognized": sum(1 for r in index["pictures"] if not r["equipment"]),
             "skipped": skipped[:50], "updated": index["updated"]}
    try:
        files.put_inline(rights, f"{folder}/{INDEX_NAME}", text=json.dumps(index, ensure_ascii=False),
                         note=f"индекс пака картинок: {stats['pictures']} картинок, {stats['sets']} наборов")
    except files.FilesError as exc:
        stats["saved"] = False
        stats["error"] = str(exc)
        return {"index": index, "stats": stats}
    stats["saved"] = True
    return {"index": index, "stats": stats}


def load(rights, folder: str = PACK, rebuild: bool = False) -> dict:
    """The index of the pack; built on the first call (that is the «first connection»), then read as is."""
    if not rebuild:
        try:
            got = files.read_text(rights, f"{folder}/{INDEX_NAME}")
            doc = json.loads(got.get("text") or "")
            if isinstance(doc, dict) and isinstance(doc.get("pictures"), list):
                return doc
        except (files.FilesError, ValueError):
            pass
    return build(rights, folder)["index"]


def find(rights, query: str, state: str = "", limit: int = 10, folder: str = PACK) -> dict:
    """Sets by meaning, best first — over the pack in the storage."""
    pic = _picindex()
    index = load(rights, folder)
    try:
        return pic.find_in(index, query, state, limit, where=folder)
    except pic.PicError as exc:
        raise PicturesError(str(exc)) from None


def overview(rights, equipment: str = "", folder: str = PACK) -> dict:
    """What the pack holds: kinds of equipment, how many sets and pictures, and the states each set has."""
    pic = _picindex()
    index = load(rights, folder)
    sets = pic.sets_of(index["pictures"])
    kinds = {}
    for one in sets:
        row = kinds.setdefault(one["equipment"], {"equipment": one["equipment"], "sets": 0, "pictures": 0,
                                                  "states": set()})
        row["sets"] += 1
        row["pictures"] += len(one["files"])
        row["states"] |= set(one["states"])
    rows = []
    for name, row in sorted(kinds.items(), key=lambda kv: (-kv[1]["pictures"], kv[0])):
        if equipment and name != equipment:
            continue
        rows.append({"equipment": name, "sets": row["sets"], "pictures": row["pictures"],
                     "states": sorted(row["states"])})
    return {"folder": folder, "pictures": len(index["pictures"]), "sets": len(sets), "kinds": rows,
            "updated": index.get("updated") or ""}
