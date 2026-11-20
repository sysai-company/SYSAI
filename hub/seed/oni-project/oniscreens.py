"""Экраны проекта ONI, собранные из спецификации объекта.

Спецификация (`plcspec`) говорит, какие у объекта механизмы и сигналы; этот модуль превращает её в окна,
которые инженер открывает на панели: мнемосхема со всеми механизмами и экран на каждый механизм.

Адреса. Панель читает контроллер по Modbus, поэтому каждый сигнал получает здесь регистр, и карта адресов
возвращается вместе с проектом — ту же карту надо задать в контроллере (Modbus mapping). Бит идёт в `4X_bit`
(регистр 6: `MainAddress` — регистр, `SubAddress` — бит), число — в `4X` (регистр 65540). Так это устроено в
настоящем проекте Достоево, оттуда же взяты и сами объекты окна (`onitpl`).

Чего это не гарантирует: что ONI Visual Studio откроет проект без замечаний — программы здесь нет, проверить
нечем. Поэтому проверяется разбором: проект читается обратно тем же `oniproj`, и сверяются окна, объекты и адреса.
"""
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import oniproj
import onitpl

NS = oniproj.NS
XSI = oniproj.XSI_URI

BIT_REGISTER = "6"        # 4X_bit
WORD_REGISTER = "65540"   # 4X
ZERO_GUID = "00000000-0000-0000-0000-000000000000"

# Что означает роль сигнала в спецификации — подпись на экране.
ROLE_RU = {
    "run": "работа", "speed": "датчик скорости", "belt": "сход ленты", "local_stop": "местный стоп",
    "plug": "завал", "vfd_ready": "готовность ПЧ", "level": "уровень", "temp": "температура",
    "pressure": "давление", "flow": "расход", "open": "открыто", "close": "закрыто",
    "fault": "авария", "estop": "аварийный стоп", "mode": "режим", "setpoint": "задание",
    "start_delay_s": "задержка пуска", "stop_delay_s": "задержка останова", "cmd_start": "команда «пуск»",
    "cmd_stop": "команда «стоп»", "ready": "готовность", "alarm": "авария", "sensor": "датчик",
    "gate_open": "затвор открыт", "gate_close": "затвор закрыт", "limit": "концевой",
}


class ScreenError(ValueError):
    pass


def _raw(device: str, register: str, main: int, sub=None, width: str = "Bit") -> str:
    """Блок адреса так, как его пишет ONI: регистр, номер, бит."""
    tail = f"<SubAddress>{sub}</SubAddress>" if sub is not None else ""
    return ("<Raw><AddressWidth>%s</AddressWidth><DeviceId>%s</DeviceId><FomulaId>%s</FomulaId>"
            "<FormulaRegisterType>Word</FormulaRegisterType><MainAddress>%d</MainAddress>%s"
            "<RegisterId>%s</RegisterId><TagName/><NewSubAddressIndexType>Constant</NewSubAddressIndexType>"
            "<Version>4</Version><Length>1</Length></Raw>"
            % (width, device, ZERO_GUID, main, tail, register))


def _bit_action(device: str, register: int, bit: int) -> str:
    return ('<SwitchActionBase i:type="BitSwitchAction"><Address>'
            '<AddressLabelId>%s</AddressLabelId><DataType>UInt16</DataType>%s'
            '<Speed>Normal</Speed><AddressLength>1</AddressLength><Version>5</Version>'
            '<OccupiedWord>1</OccupiedWord></Address><PulseWidth>2</PulseWidth></SwitchActionBase>'
            % (ZERO_GUID, _raw(device, BIT_REGISTER, register, bit)))


def _window_action(window_id: str) -> str:
    return ('<SwitchActionBase i:type="WindowOperSwitchAction"><Function>Window</Function>'
            '<IsAutoPopupPasswordWindow>true</IsAutoPopupPasswordWindow><Window>%s</Window>'
            '</SwitchActionBase>' % window_id)


def _text(x, y, w, h, text, z=1, fs=16, fc="#FF1F2933") -> str:
    return onitpl.TEXT.format(uid=str(uuid.uuid4()), z=z, x=x, y=y, w=w, h=h,
                              text=_esc(text), fs=fs, fc=fc)


def _rect(x, y, w, h, z=0, fill="#FFFFFFFF", line="#FFD0D7DE") -> str:
    return onitpl.RECT.format(uid=str(uuid.uuid4()), z=z, x=x, y=y, w=w, h=h, fill=fill, line=line)


def _line(x, y, w, z=1, color="#FFD0D7DE") -> str:
    return onitpl.LINE.format(uid=str(uuid.uuid4()), z=z, x=x, y=y, w=w, h=2, line=color)


def _lamp(x, y, size, device, register, bit, z=3) -> str:
    """Лампа: тот же объект, что клавиша, но без подписи и без действия — только показывает бит."""
    return onitpl.LAMP.format(uid=str(uuid.uuid4()), z=z, x=x, y=y, w=size, h=size,
                              raw=_raw(device, BIT_REGISTER, register, bit), actions="")


def _button(x, y, w, h, text, device, register, bit, z=4) -> str:
    return onitpl.BUTTON.format(uid=str(uuid.uuid4()), z=z, x=x, y=y, w=w, h=h,
                                text=_esc(text), raw=_raw(device, BIT_REGISTER, register, bit),
                                actions=_bit_action(device, register, bit))


def _nav(x, y, w, h, text, window_id, z=4) -> str:
    """Клавиша перехода на другое окно: адреса не читает, только открывает окно."""
    return onitpl.NAV.format(uid=str(uuid.uuid4()), z=z, x=x, y=y, w=w, h=h,
                             text=_esc(text), window=window_id, actions=_window_action(window_id))


def _number(x, y, w, h, device, register, z=3) -> str:
    return onitpl.NUMBER.format(uid=str(uuid.uuid4()), z=z, x=x, y=y, w=w, h=h,
                                raw=_raw(device, WORD_REGISTER, register, width="Word"))


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _window_xml(window_id: str, name: str, width: int, height: int, objects: list) -> bytes:
    head = ('<HMIWindowInfo xmlns="%s" xmlns:i="%s"><UniqueId>%s</UniqueId><Name>%s</Name>'
            '<Width>%d</Width><Height>%d</Height><GraphicsName/>'
            % (NS.strip("{}"), XSI, window_id, _esc(name), width, height))
    return (head + "".join(objects) + "</HMIWindowInfo>").encode("utf-8")


def _role_ru(role: str) -> str:
    return ROLE_RU.get(str(role or "").strip().lower(), str(role or "").replace("_", " "))


def _mechanisms(spec: dict) -> list:
    out = []
    for m in spec.get("mechanisms") or []:
        if isinstance(m, dict) and str(m.get("id") or "").strip():
            out.append(m)
    return out


def _signals_of(m: dict) -> list:
    """Сигналы механизма по порядку: сначала входы, потом выходы. Роль, направление, канал.

    «!» перед каналом — нормально замкнутый контакт: на экране он всё равно читается этим же битом, но
    инженеру важно знать, что лампа «1» означает «контакт разомкнут».
    """
    rows = []
    for side in ("in", "out"):
        part = m.get(side)
        for role, channel in (part.items() if isinstance(part, dict) else ()):
            rows.append({"role": str(role), "dir": side, "channel": str(channel or "")})
    return rows


def _channel(text: str) -> tuple:
    """Канал и признак нормально замкнутого контакта: «!DI.I5» -> («DI.I5», True)."""
    raw = str(text or "").strip()
    return (raw[1:].strip(), True) if raw.startswith("!") else (raw, False)


def _global_signals(spec: dict) -> list:
    """Сигналы объекта, а не механизма: аварийный стоп, режим, общая готовность.

    Они не принадлежат ни одному механизму, поэтому на экране стоят отдельной строкой сверху — иначе
    аварийный стоп искали бы внутри чьей-то плитки.
    """
    rows = []
    for s in spec.get("signals") or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("mechanism") or "").strip():
            continue
        role = str(s.get("role") or s.get("id") or "").strip()
        if not role:
            continue
        rows.append({"role": role, "title": str(s.get("title") or _role_ru(role)),
                     "channel": str(s.get("channel") or "")})
    return rows


def _params_of(m: dict) -> list:
    part = m.get("params")
    return [{"role": str(k), "value": v} for k, v in (part.items() if isinstance(part, dict) else ())]


def build(spec: dict, out, resolution: str = "1024x768", device: str = "Modbus_TCP",
          title: str = "", start_bit: int = 0, start_word: int = 1001) -> dict:
    """Собрать проект экранов из спецификации.

    -> {'project', 'panel', 'windows': [...], 'map': [...], 'unwired': [...]}. `map` — карта адресов: что за
    сигнал, бит это или слово, какой регистр. `unwired` — сигналы без канала в спецификации: на экране они
    есть, но читать им нечего, и это сказано, а не спрятано.
    """
    if not isinstance(spec, dict):
        raise ScreenError("спецификация не прочитана: нужен разобранный project.spec.json")
    mechs = _mechanisms(spec)
    if not mechs:
        raise ScreenError("в спецификации нет ни одного механизма — экраны строить не из чего")
    key = str(resolution or "").strip().lower().replace("х", "x").replace("×", "x")
    if "x" not in key:
        raise ScreenError(f"разрешение «{resolution}» не понято: нужно вида 1024x768")
    try:
        one = oniproj.resolution_of(*[int(x) for x in key.split("x", 1)])
    except ValueError:
        raise ScreenError(f"разрешение «{resolution}» не понято: нужно вида 1024x768") from None

    root = Path(str(out))
    if (root / "HMI" / "Frame").exists() and list((root / "HMI" / "Frame").rglob("*.wcfg")):
        raise ScreenError(f"в папке уже есть проект экранов: {root}")
    (root / "HMI" / "Frame" / "Basic").mkdir(parents=True, exist_ok=True)
    (root / "HMI" / "System").mkdir(parents=True, exist_ok=True)

    device_id = str(uuid.uuid4())
    width, height = one["w"], one["h"]
    head = str(title or (spec.get("project") or {}).get("name") or "Мнемосхема")

    bit, word = int(start_bit), int(start_word)
    addr_map, unwired = [], []

    def take_bit(tag: str, role: str, channel: str, own: bool = False) -> dict:
        nonlocal bit
        reg, sub = bit // 16 + 1, bit % 16
        bit += 1
        row = {"tag": tag, "role": role, "kind": "bit", "register": reg, "bit": sub,
               "address": f"4X_bit{reg}.{sub}", "channel": channel}
        addr_map.append(row)
        if not channel and not own:
            unwired.append(tag)
        return row

    def take_word(tag: str, role: str) -> dict:
        nonlocal word
        reg = word
        word += 1
        row = {"tag": tag, "role": role, "kind": "word", "register": reg, "bit": None,
               "address": f"4X{reg}", "channel": ""}
        addr_map.append(row)
        return row

    # Сначала раздаём адреса: экраны рисуются уже по готовой карте.
    plan = []
    for m in mechs:
        mid = str(m["id"]).strip()
        sigs = []
        for s in _signals_of(m):
            sigs.append(dict(s, addr=take_bit(f"{mid}.{s['role']}", s["role"], s["channel"])))
        params = [dict(p, addr=take_word(f"{mid}.{p['role']}", p["role"])) for p in _params_of(m)]
        plan.append({"id": mid, "title": str(m.get("title") or mid), "signals": sigs, "params": params,
                     "start": take_bit(f"{mid}.cmd_start", "cmd_start", "", own=True),
                     "stop": take_bit(f"{mid}.cmd_stop", "cmd_stop", "", own=True)})

    obj_signals = [dict(s, addr=take_bit(f"obj.{s['role']}", s["role"], s["channel"]))
                   for s in _global_signals(spec)]

    windows = []

    # --- главный экран: все механизмы плитками
    objs = [_text(24, 16, width - 48, 40, head, z=1, fs=26),
            _line(24, 62, width - 48, z=1)]
    top = 84
    if obj_signals:
        x = 24
        for s in obj_signals[:5]:
            objs.append(_lamp(x, 72, 22, device_id, s["addr"]["register"], s["addr"]["bit"]))
            objs.append(_text(x + 28, 72, 150, 22, s["title"], z=2, fs=13))
            x += 190
        top = 84 + 34
    cols = 3 if width >= 1000 else 2
    gap, tile_h = 16, 104
    tile_w = (width - 48 - gap * (cols - 1)) // cols
    for i, p in enumerate(plan):
        col, row = i % cols, i // cols
        x = 24 + col * (tile_w + gap)
        y = top + row * (tile_h + gap)
        if y + tile_h > height - 16:
            break
        objs.append(_rect(x, y, tile_w, tile_h, z=0))
        objs.append(_text(x + 12, y + 10, tile_w - 24, 26, p["title"], z=2, fs=17))
        run = next((s for s in p["signals"] if s["role"] == "run"), None)
        alarm = next((s for s in p["signals"] if s["role"] in ("fault", "belt", "plug", "local_stop")), None)
        if run:
            objs.append(_lamp(x + 12, y + 48, 22, device_id, run["addr"]["register"], run["addr"]["bit"]))
            objs.append(_text(x + 40, y + 48, 90, 22, "работа", z=2, fs=13))
        if alarm:
            objs.append(_lamp(x + 140, y + 48, 22, device_id, alarm["addr"]["register"], alarm["addr"]["bit"]))
            objs.append(_text(x + 168, y + 48, 110, 22, _role_ru(alarm["role"]), z=2, fs=13))
        objs.append(_nav(x + tile_w - 100, y + 44, 88, 32, "Открыть", f"win-{p['id']}"))
    windows.append(("win-main", head, objs))

    # --- экран на каждый механизм: сигналы лампами, задание числом, пуск и стоп
    for p in plan:
        objs = [_text(24, 16, width - 200, 40, p["title"], z=1, fs=24),
                _line(24, 62, width - 48, z=1),
                _nav(width - 140, 16, 116, 34, "Назад", "win-main")]
        y = 84
        for s in p["signals"]:
            if y + 30 > height - 90:
                break
            objs.append(_lamp(24, y, 22, device_id, s["addr"]["register"], s["addr"]["bit"]))
            objs.append(_text(56, y, 300, 24, _role_ru(s["role"]), z=2, fs=15))
            shown, nc = _channel(s["channel"])
            if nc:
                shown += "  (норм. замкнут)"
            objs.append(_text(370, y, 320, 24, shown or "не подключён", z=2, fs=13, fc="#FF7B8794"))
            y += 34
        for prm in p["params"]:
            if y + 30 > height - 90:
                break
            objs.append(_text(24, y, 300, 24, _role_ru(prm["role"]), z=2, fs=15))
            objs.append(_number(340, y, 120, 24, device_id, prm["addr"]["register"]))
            y += 34
        objs.append(_button(24, height - 68, 140, 40, "Пуск", device_id, p["start"]["register"], p["start"]["bit"]))
        objs.append(_button(180, height - 68, 140, 40, "Стоп", device_id, p["stop"]["register"], p["stop"]["bit"]))
        windows.append((f"win-{p['id']}", p["title"], objs))

    for window_id, name, objs in windows:
        (root / "HMI" / "Frame" / "Basic" / f"{window_id}.wcfg").write_bytes(
            _window_xml(window_id, name, width, height, objs))

    fsprj = ('<Project xmlns="%s" xmlns:i="%s"><Version>1.0</Version>'
             '<SoftwareVersion>2.8.11916.0</SoftwareVersion></Project>' % (NS.strip("{}"), XSI))
    (root / f"{root.name}.fsprj").write_bytes(fsprj.encode("utf-8"))

    conn = ('<HMIProjectInfo xmlns="%s" xmlns:i="%s"><DeviceId>%s</DeviceId>'
            '<EthernetConnectionInfo><EthernetHMIInfos/><EthernetPLCInfos/><InternetPLCInfos>'
            '<InternetPLCInfo><DeviceAlias>Device1</DeviceAlias><PLCName>%s</PLCName><PLCID>400</PLCID>'
            '<DefaultStation>1</DefaultStation></InternetPLCInfo></InternetPLCInfos></EthernetConnectionInfo>'
            '</HMIProjectInfo>' % (NS.strip("{}"), XSI, device_id, _esc(device)))
    (root / "HMI" / "System" / "ConnectInfo.cfg").write_bytes(conn.encode("utf-8"))

    glob = ('<GlobalConfigInfo xmlns="%s" xmlns:i="%s"><InitWindow>win-main</InitWindow></GlobalConfigInfo>'
            % (NS.strip("{}"), XSI))
    (root / "HMI" / "System" / "GlobalConfigInfo.cfg").write_bytes(glob.encode("utf-8"))

    made = oniproj.Project(root)
    return {"project": str(root), "panel": made.panel(), "title": head,
            "windows": [w.as_dict() for w in made.windows],
            "objects": sum(len(w.objects) for w in made.windows),
            "addresses": len(made.addresses()), "map": addr_map, "unwired": unwired,
            "devices": made.devices}


def screens(spec_file, out, resolution: str = "1024x768", device: str = "Modbus_TCP",
            title: str = "") -> dict:
    """То же, но спецификация читается из файла — так это зовёт инженер."""
    import json
    p = Path(str(spec_file))
    if not p.is_file():
        raise ScreenError(f"нет файла спецификации: {p}")
    try:
        spec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScreenError(f"спецификация не читается: {exc}") from None
    return build(spec, out, resolution=resolution, device=device, title=title)
