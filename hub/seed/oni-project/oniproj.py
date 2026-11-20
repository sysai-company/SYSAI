"""The HMI project of ONI Visual Studio (Flexem Studio): windows, objects, addresses.

ONI Visual Studio is the Russian build of Flexem Studio, and its project is a folder, not one file:

* `<имя>.fsprj` — the project itself: language, version, whether the HMI is enabled (XML, a few hundred bytes);
* `HMI/Frame/**/*.wcfg` — the windows. One file per window, `<HMIWindowInfo>`, plain XML: every object is a
  `<GraphicsBase i:type="…">` whose type is in the `xsi:type` attribute, geometry in `NormalInfo/Position`,
  the PLC binding in `DynamicGraphInfo/ControlAddress` (a switch keeps four: before/after × bit/word), the
  text in `NormalInfo/StaticTextContentInfos`, and a picture as base64 PNG in `NormalInfo/ImageData`;
* `HMI/System/*.cfg` — the devices and the protocol (`ConnectInfo.cfg`), alarms, users, global settings;
* `HMI/Frame/Startup/Startup.sscfg` — the splash screen; `GlobalConfigInfo.cfg` names the start window.

The windows have no names of their own (`GraphicsName` is empty): the program refers to them by GUID, and
`GlobalConfigInfo.cfg` says which one is the start window. So a window is named here by its first text, and
the GUID stays the identity.

What this module does not do: it does not write `.wcfg` back. Reading is exact; writing a window that ONI
Visual Studio opens without complaint is a separate job (the object model has ~16 types with their own
defaults), and it is not pretended here.
"""
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://schemas.flexem.com/fs/model/1}"
XSITYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# What each object type is, in words an engineer reads.
KINDS = {
    "SwitchInfo": "клавиша / индикатор",
    "StaticTextInfo": "текст",
    "NumericCharInfo": "число",
    "StaticPictureInfo": "картинка",
    "LineInfo": "линия",
    "RectangleInfo": "прямоугольник",
    "GroupGraphicsInfo": "группа",
    "AlertAndEventInfo": "тревоги и события",
    "TouchSourceInfo": "источник касания",
    "ArcInfo": "дуга",
    "PopupWindowInfo": "всплывающее окно",
    "UserRightsBrowserInfo": "права пользователя",
    "QRCodeInfo": "QR-код",
    "SingleSelectorInfo": "переключатель",
    "CalendarAndTimeInfo": "календарь и время",
    "FileBrowserInfoDto": "файлы",
}

# The register a `RegisterId` means. The address itself is `MainAddress`; the readable name is
# `Abbreviation` when the engineer typed one, and is built from this table when he did not.
REGISTERS = {
    "257": "SRB",        # системный бит
    "65791": "LW",       # локальное слово
    "65792": "SRW",      # системное слово
    "65788": "SRWR",     # системный регистр слова
    "6": "4X_bit",       # бит Modbus
    "65540": "4X",       # регистр хранения Modbus (слово)
}


# Разрешения панелей, под которые рисуют экраны. Панели разные, и экран, нарисованный под 1024×768, на 800×480
# не влезает: поэтому разрешение — это выбор инженера при создании проекта, а не константа в коде.
RESOLUTIONS = [
    {"id": "800x480", "w": 800, "h": 480, "title": "800×480 — 7\" панель", "note": "самое частое у небольших панелей"},
    {"id": "1024x600", "w": 1024, "h": 600, "title": "1024×600 — 7\" широкая", "note": ""},
    {"id": "1024x768", "w": 1024, "h": 768, "title": "1024×768 — 10,4\"/12,1\"", "note": "классика: так нарисовано Достоево"},
    {"id": "1280x800", "w": 1280, "h": 800, "title": "1280×800 — 10,1\"", "note": ""},
    {"id": "1366x768", "w": 1366, "h": 768, "title": "1366×768 — 15\"", "note": ""},
    {"id": "1920x1080", "w": 1920, "h": 1080, "title": "1920×1080 — 15\"/21,5\"", "note": ""},
    {"id": "640x480", "w": 640, "h": 480, "title": "640×480 — 5,7\"", "note": "старые панели"},
    {"id": "480x272", "w": 480, "h": 272, "title": "480×272 — 4,3\"", "note": ""},
]


def resolutions() -> list:
    """Из чего инженер выбирает разрешение экрана. Список один на все программы панелей."""
    return [dict(r) for r in RESOLUTIONS]


def resolution_of(width: int, height: int) -> dict:
    """Какое из известных разрешений это. Не совпало — честно говорим, что такого в списке нет."""
    for r in RESOLUTIONS:
        if (r["w"], r["h"]) == (width, height):
            return dict(r)
    return {"id": f"{width}x{height}", "w": width, "h": height,
            "title": f"{width}×{height} — не из списка", "note": "панель с таким разрешением в реестре не описана"}


class OniError(ValueError):
    pass


def find_root(path) -> Path:
    """The project folder, from whatever the engineer pointed at: the folder, the `.fsprj`, or `HMI`."""
    p = Path(str(path))
    if p.is_file():
        if p.suffix.lower() == ".fsprj":
            return p.parent
        if p.suffix.lower() == ".wcfg":
            return p.parent
        raise OniError(f"это не проект ONI: {p.name}. Нужна папка проекта (в ней <имя>.fsprj) или сам .fsprj")
    if not p.is_dir():
        raise OniError(f"нет такой папки: {p}")
    if list(p.glob("*.fsprj")):
        return p
    if (p / "HMI" / "Frame").is_dir() and list((p / "HMI" / "Frame").rglob("*.wcfg")):
        return p
    if (p / "Frame").is_dir() and list((p / "Frame").rglob("*.wcfg")):
        return p.parent          # дали саму папку HMI, а не проект
    for sub in sorted(p.iterdir()):
        if sub.is_dir() and list(sub.glob("*.fsprj")):
            return sub
    raise OniError(f"в папке нет проекта ONI (ни <имя>.fsprj, ни HMI/Frame/*.wcfg): {p}")


def _text(e, tag, default=""):
    if e is None:
        return default
    x = e.find(NS + tag)
    return (x.text or default) if x is not None else default


def _int(e, tag, default=0):
    try:
        return int(float(_text(e, tag, "") or default))
    except (TypeError, ValueError):
        return default


def _position(obj) -> dict:
    """X, Y, Width, Height — the first `Position` that has them (a group keeps its own under NormalInfo)."""
    for pos in obj.iter(NS + "Position"):
        if pos.find(NS + "X") is not None and pos.find(NS + "Width") is not None:
            return {"x": _int(pos, "X"), "y": _int(pos, "Y"),
                    "w": _int(pos, "Width"), "h": _int(pos, "Height")}
    return {"x": 0, "y": 0, "w": 0, "h": 0}


def _addresses(obj) -> list:
    """Every PLC binding of the object: (what, address, device). No address — the object is not wired.

    The address element is not one tag: a switch keeps `BitAddressInfo` / `WordAddressInfo`, a number keeps
    `ReadAddress`, a clock keeps `ClockAddress`. Two shapes hide inside them:

    * the Modbus one — `Abbreviation` is the address itself (`4X_bit3.13`, `0X3079`);
    * the register one — `Raw/MainAddress` is the number and `Raw/RegisterId` says which register it is
      (`257` → `SRB13`, `65791` → `LW799999`), with `Abbreviation` often empty.

    So the address is `Abbreviation` when it is there, and is built from the register table when it is not.
    """
    parent = {}
    for par in obj.iter():
        for c in par:
            parent[c] = par
    out = []
    for a in obj.iter():
        if a.tag == NS + "Raw" or parent.get(a) is not None and parent[a].tag == NS + "Raw":
            continue
        raw = a.find(NS + "Raw")
        main = _text(raw, "MainAddress").strip() if raw is not None else _text(a, "MainAddress").strip()
        rid = _text(raw, "RegisterId").strip() if raw is not None else _text(a, "RegisterId").strip()
        sub = _text(raw, "SubAddress").strip() if raw is not None else _text(a, "SubAddress").strip()
        abbr = a.find(NS + "Abbreviation")
        name = (abbr.text or "").strip() if abbr is not None else ""
        if not name and main:
            prefix = REGISTERS.get(rid)
            if prefix is None:
                name = f"reg{rid}:{main}" if rid else main
            elif prefix == "4X_bit" and sub:
                name = f"{prefix}{main}.{sub}"
            else:
                name = f"{prefix}{main}"
        if not name:
            continue
        out.append({"what": a.tag.split("}")[-1], "address": name,
                    "device": _text(a, "DeviceAndAbbreviation").strip(),
                    "type": _text(a, "AddressType").strip() or _text(a, "AddressWidth").strip()})
    return out


def _label(obj) -> str:
    """The text the object shows: the first non-empty LabelContent (a text may have one per language)."""
    for c in obj.iter(NS + "LabelContent"):
        if c.text and c.text.strip():
            return c.text.strip()
    # У клавиши подпись лежит не в LabelContent, а в Text её состояния — иначе «Пуск» на экране есть,
    # а в отчёте клавиша безымянная.
    for c in obj.iter(NS + "Text"):
        text = (c.text or "").strip()
        if text and text != "Quit":
            return text
    return ""


def _picture(obj) -> bool:
    return any((x.text or "").strip() for x in obj.iter(NS + "ImageData"))


class Obj:
    __slots__ = ("type", "kind", "name", "z", "x", "y", "w", "h", "addresses", "label", "picture", "id",
                 "navigates")

    def __init__(self, e):
        self.type = e.get(XSITYPE) or ""
        self.kind = KINDS.get(self.type, self.type or "объект")
        self.name = _text(e, "GraphicsName")
        self.id = _text(e, "UniqueId")
        self.z = _int(e, "ZIndex")
        pos = _position(e)
        self.x, self.y, self.w, self.h = pos["x"], pos["y"], pos["w"], pos["h"]
        self.addresses = _addresses(e)
        self.label = _label(e)
        self.picture = _picture(e)
        # Клавиша перехода на другое окно адреса не читает — и «мёртвой» от этого не становится. Действие
        # в ONI записано типом элемента (`i:type`), а не именем тега, поэтому смотрим на атрибут.
        self.navigates = any((x.get(XSITYPE) or "").endswith("WindowOperSwitchAction")
                             or x.tag == NS + "WindowOperSwitchAction" for x in e.iter())

    def as_dict(self) -> dict:
        return {"type": self.type, "kind": self.kind, "name": self.name, "id": self.id, "z": self.z,
                "x": self.x, "y": self.y, "w": self.w, "h": self.h,
                "addresses": self.addresses, "label": self.label, "picture": self.picture,
                "navigates": self.navigates}


class Window:
    __slots__ = ("id", "file", "folder", "objects", "width", "height", "name", "own_name", "root")

    def __init__(self, path: Path, root):
        self.file = str(path)
        self.folder = path.parent.name
        self.root = root
        self.id = _text(root, "UniqueId") or path.stem
        self.own_name = _text(root, "Name")
        self.objects = [Obj(e) for e in root.iter(NS + "GraphicsBase")]
        self.width = _int(root, "Width")
        self.height = _int(root, "Height")
        self.name = self._name()

    def _name(self) -> str:
        """A window has no name of its own: the first text on it is the best handle, the GUID is the identity."""
        for o in sorted(self.objects, key=lambda o: (o.z, o.y, o.x)):
            if o.label and len(o.label) <= 60 and "\n" not in o.label:
                return o.label
        return self.own_name or self.folder

    def as_dict(self, with_objects: bool = False) -> dict:
        d = {"id": self.id, "name": self.name, "folder": self.folder, "file": self.file,
             "objects": len(self.objects), "width": self.width, "height": self.height}
        if with_objects:
            d["items"] = [o.as_dict() for o in sorted(self.objects, key=lambda o: (o.z, o.y, o.x))]
        return d


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.name = root.name
        self.fsprj = next(iter(sorted(root.glob("*.fsprj"))), None)
        self.windows = []
        self.devices = []
        self.init_window = ""
        self.version = ""
        self.software = ""
        self._read()

    def _read(self):
        if self.fsprj is not None:
            try:
                r = ET.parse(self.fsprj).getroot()
                self.version = _text(r, "Version")
                self.software = _text(r, "SoftwareVersion")
            except ET.ParseError as exc:
                raise OniError(f"{self.fsprj.name} не читается: {exc}") from None
        files = sorted((self.root / "HMI" / "Frame").rglob("*.wcfg"))
        if not files:
            raise OniError(f"в проекте нет окон (HMI/Frame/**/*.wcfg): {self.root}")
        for f in files:
            try:
                self.windows.append(Window(f, ET.parse(f).getroot()))
            except ET.ParseError as exc:
                raise OniError(f"окно {f.name} не читается: {exc}") from None
        self._read_system()

    def _read_system(self):
        cfg = self.root / "HMI" / "System" / "GlobalConfigInfo.cfg"
        if cfg.is_file():
            try:
                r = ET.parse(cfg).getroot()
                self.init_window = _text(r, "InitWindow") or _text(r, "HomeWindowId")
            except ET.ParseError:
                pass
        conn = self.root / "HMI" / "System" / "ConnectInfo.cfg"
        if conn.is_file():
            try:
                r = ET.parse(conn).getroot()
            except ET.ParseError:
                return
            seen = set()
            for e in r.iter():
                tag = e.tag.split("}")[-1]
                if tag not in ("InternetPLCInfo", "EthernetPLCInfo", "COMPLCInfo"):
                    continue
                alias = _text(e, "DeviceAlias") or _text(e, "PLCName")
                if not alias or alias in seen:
                    continue
                seen.add(alias)
                self.devices.append({"name": alias, "plc": _text(e, "PLCName"),
                                     "id": _text(e, "PLCID"), "station": _text(e, "DefaultStation")})

    def window(self, key: str):
        """A window by GUID, by file name, or by the name this module gave it."""
        k = str(key or "").strip().lower()
        for w in self.windows:
            if k in (w.id.lower(), os.path.basename(w.file).lower(), w.name.lower()):
                return w
        return None

    def panel(self) -> dict:
        """Разрешение панели: самое большое окно проекта. Всплывающие окна меньше — они не задают экран."""
        if not self.windows:
            return resolution_of(0, 0)
        big = max(self.windows, key=lambda w: (w.width * w.height, w.width))
        one = resolution_of(big.width, big.height)
        one["window"] = big.id
        one["window_name"] = big.name
        one["sizes"] = sorted({f"{w.width}×{w.height}" for w in self.windows})
        return one

    def addresses(self) -> dict:
        """Every PLC address the screens use, with how many objects read it and on which windows."""
        out = {}
        for w in self.windows:
            for o in w.objects:
                for a in o.addresses:
                    one = out.setdefault(a["address"], {"address": a["address"], "device": a["device"],
                                                        "type": a["type"], "count": 0, "windows": set()})
                    one["count"] += 1
                    one["windows"].add(w.id)
        for one in out.values():
            one["windows"] = sorted(one["windows"])
        return dict(sorted(out.items()))

    def check(self) -> dict:
        """What is wrong with the screens, one line per window rather than one per object.

        A screen is a drawing: an object that hangs a few points over the edge is normal and is not reported.
        What is reported: an object entirely outside the window, an object more than 20 points over the edge,
        and a switch or a number that reads nothing — those are the ones that show a dead screen.
        """
        issues = []
        for w in self.windows:
            outside, over, dead = [], [], []
            for o in w.objects:
                if not (o.w and o.h):
                    continue
                if o.x >= w.width or o.y >= w.height:
                    outside.append(o)
                elif o.x + o.w > w.width + 20 or o.y + o.h > w.height + 20:
                    over.append(o)
                if o.type in ("SwitchInfo", "NumericCharInfo") and not o.addresses and not o.navigates:
                    dead.append(o)
            where = f"окно «{w.name or w.id}» ({w.id[:8]})"
            if outside:
                issues.append({"level": "error", "window": w.id, "object": "",
                               "text": f"{where}: {len(outside)} объект(ов) целиком за окном — "
                                       + ", ".join(f"{o.kind} «{o.label or o.name}»" for o in outside[:3])})
            if over:
                issues.append({"level": "warning", "window": w.id, "object": "",
                               "text": f"{where}: {len(over)} объект(ов) выходит за окно больше чем на 20 точек — "
                                       + ", ".join(f"{o.kind} «{o.label or o.name}»" for o in over[:3])})
            if dead:
                issues.append({"level": "warning", "window": w.id, "object": "",
                               "text": f"{where}: {len(dead)} клавиш(и)/числа(ел) ни к чему не привязаны — "
                                       + ", ".join(f"{o.kind} «{o.label or o.name}»" for o in dead[:3])})
        if not self.devices:
            issues.append({"level": "warning", "window": "", "object": "",
                           "text": "в проекте не описан ни один ПЛК (ConnectInfo.cfg): экраны некуда читать"})
        order = {"error": 0, "warning": 1, "info": 2}
        issues.sort(key=lambda i: order[i["level"]])
        return {"project": str(self.root), "windows": len(self.windows),
                "objects": sum(len(w.objects) for w in self.windows),
                "addresses": len(self.addresses()), "devices": self.devices,
                "summary": {k: sum(1 for i in issues if i["level"] == k) for k in order},
                "issues": issues[:2000]}


NS_URI = "http://schemas.flexem.com/fs/model/1"
XSI_URI = "http://www.w3.org/2001/XMLSchema-instance"


def _serialize(root) -> bytes:
    """Окно в XML так, как его пишет ONI: без объявления, с префиксом `i` у xsi:type.

    `\r` экранируется в `&#13;` руками: ElementTree его не трогает, а XML-парсер по спецификации превращает
    сырой `\r\n` в `\n` — и перевод строки в подписи терялся бы при каждой перезаписи.
    """
    ET.register_namespace("", NS_URI)
    ET.register_namespace("i", XSI_URI)
    return ET.tostring(root, encoding="utf-8", xml_declaration=False).replace(b"\r", b"&#13;")


def write_window(window, path=None) -> dict:
    """Записать окно обратно и прочитать его снова — что получилось, а не что задумано.

    Байт-в-байт не совпадёт: ElementTree поднимает объявления неймспейсов к корню и пишет `<X />` вместо `<X/>`.
    Для ONI это одно и то же (это XmlSerializer .NET), поэтому сверяется не текст, а разобранное окно: объекты,
    их типы, координаты и адреса.
    """
    target = Path(str(path or window.file))
    data = _serialize(window.root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    back = Window(target, ET.parse(target).getroot())
    before = [o.as_dict() for o in window.objects]
    after = [o.as_dict() for o in back.objects]
    return {"file": str(target), "bytes": len(data), "objects": len(back.objects),
            "same": before == after, "width": back.width, "height": back.height}


def _el(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, NS + tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def new_project(path, name: str, resolution: str = "1024x768", device: str = "Modbus_TCP",
                title: str = "") -> dict:
    """Новый проект экранов под выбранное разрешение.

    Панели разные, и экран под 1024×768 на 800×480 не влезает — поэтому разрешение приходит сюда, а не берётся
    из константы. Создаётся папка проекта: `<имя>.fsprj`, одно окно нужного размера, описание ПЛК и стартовое
    окно. Структура снята с настоящего проекта Достоево.

    Чего это не гарантирует: что ONI Visual Studio откроет файл без замечаний — программы здесь нет, проверить
    нечем. Поэтому `plc_formats` честно говорит `write: false` для ONI, пока это не проверено на панели.
    """
    key = str(resolution or "").strip().lower().replace("х", "x").replace("×", "x")
    if "x" not in key:
        raise OniError(f"разрешение «{resolution}» не понято: нужно вида 1024x768")
    try:
        one = resolution_of(*[int(x) for x in key.split("x", 1)])
    except ValueError:
        raise OniError(f"разрешение «{resolution}» не понято: нужно вида 1024x768") from None
    root = Path(str(path))
    if (root / f"{name}.fsprj").exists():
        raise OniError(f"проект уже есть: {root / (name + '.fsprj')}")
    (root / "HMI" / "Frame" / "Basic").mkdir(parents=True, exist_ok=True)
    (root / "HMI" / "System").mkdir(parents=True, exist_ok=True)

    fsprj = ET.Element(NS + "Project")
    _el(fsprj, "Version", "1.0")
    _el(fsprj, "SoftwareVersion", "2.8.11916.0")
    (root / f"{name}.fsprj").write_bytes(_serialize(fsprj))

    win = ET.Element(NS + "HMIWindowInfo")
    _el(win, "UniqueId", "win-main")
    _el(win, "Name", "Basic Window")
    _el(win, "Width", one["w"])
    _el(win, "Height", one["h"])
    _el(win, "GraphicsName")
    if title:
        obj = ET.SubElement(win, NS + "GraphicsBase", {"{%s}type" % XSI_URI: "StaticTextInfo"})
        _el(obj, "GraphicsName", "Static Text")
        _el(obj, "UniqueId", "t-title")
        _el(obj, "ZIndex", 0)
        info = _el(obj, "NormalInfo")
        pos = _el(info, "Position")
        for k, v in (("X", 20), ("Y", 16), ("Width", min(600, one["w"] - 40)), ("Height", 32)):
            _el(pos, k, v)
        texts = _el(info, "StaticTextContentInfos")
        content = _el(texts, "StaticTextContentInfo")
        _el(content, "LabelContent", title)
    (root / "HMI" / "Frame" / "Basic" / "win-main.wcfg").write_bytes(_serialize(win))

    conn = ET.Element(NS + "ConnectInfo")
    plc = _el(conn, "InternetPLCInfo")
    _el(plc, "DeviceAlias", "Device1")
    _el(plc, "PLCName", device)
    _el(plc, "PLCID", "400")
    _el(plc, "DefaultStation", "1")
    (root / "HMI" / "System" / "ConnectInfo.cfg").write_bytes(_serialize(conn))

    glob = ET.Element(NS + "GlobalConfigInfo")
    _el(glob, "InitWindow", "win-main")
    (root / "HMI" / "System" / "GlobalConfigInfo.cfg").write_bytes(_serialize(glob))

    made = Project(root)
    return {"project": str(root), "name": name, "panel": made.panel(),
            "windows": [w.as_dict() for w in made.windows], "devices": made.devices}


def load(path) -> Project:
    return Project(find_root(path))


def windows(path) -> dict:
    p = load(path)
    return {"project": str(p.root), "name": p.name, "version": p.version, "software": p.software,
            "init_window": p.init_window, "devices": p.devices,
            "windows": [w.as_dict() for w in p.windows]}


def objects(path, window: str) -> dict:
    p = load(path)
    w = p.window(window)
    if w is None:
        raise OniError(f"нет окна «{window}». Есть: " + ", ".join(x.id for x in p.windows[:10]))
    return {"project": str(p.root), "window": w.as_dict(with_objects=True)}


def addresses(path) -> dict:
    p = load(path)
    return {"project": str(p.root), "devices": p.devices, "addresses": list(p.addresses().values())}


def check(path) -> dict:
    return load(path).check()


def panel(path) -> dict:
    p = load(path)
    return {"project": str(p.root), "panel": p.panel(), "resolutions": resolutions()}
