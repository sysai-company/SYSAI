"""ONI Visual Studio (Flexem Studio) — the screens of the panel, not the PLC.

The fixture is a small project written by hand in the same XML the real one uses, so the test does not need
the 1479-file Dostoevo project on disk. The real project is checked separately by `scripts/oni_report.py`.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "hub" / "seed" / "plc-kit"


def _load(name, path):
    """Load a module by path without touching sys.path: several seed folders have a `server.py`, and a path
    left in sys.path makes another test file import the wrong one."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


oniproj = _load("oniproj", KIT / "oniproj.py")

NS = "http://schemas.flexem.com/fs/model/1"
XSI = "http://www.w3.org/2001/XMLSchema-instance"


def _window(uid, name, width, height, objects):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<HMIWindowInfo xmlns="{NS}" xmlns:xsi="{XSI}">
  <UniqueId>{uid}</UniqueId>
  <Name>{name}</Name>
  <Width>{width}</Width>
  <Height>{height}</Height>
  <GraphicsName />
{objects}
</HMIWindowInfo>'''


def _text(uid, label, x, y, w, h):
    return f'''  <GraphicsBase xsi:type="StaticTextInfo">
    <GraphicsName>Static Text</GraphicsName><UniqueId>{uid}</UniqueId><ZIndex>1</ZIndex>
    <NormalInfo><Position><X>{x}</X><Y>{y}</Y><Width>{w}</Width><Height>{h}</Height></Position>
      <StaticTextContentInfos><StaticTextContentInfo><LabelContent>{label}</LabelContent></StaticTextContentInfo></StaticTextContentInfos>
    </NormalInfo>
  </GraphicsBase>'''


def _switch(uid, x, y, w, h, abbreviation="", main="", register="", sub=""):
    raw = ""
    if main:
        raw = (f'<Raw><AddressWidth>Word</AddressWidth><DeviceId>dev-1</DeviceId>'
               f'<MainAddress>{main}</MainAddress><RegisterId>{register}</RegisterId>'
               f'<SubAddress>{sub}</SubAddress><Length>1</Length></Raw>')
    return f'''  <GraphicsBase xsi:type="SwitchInfo">
    <GraphicsName>Switch/Indicator Light</GraphicsName><UniqueId>{uid}</UniqueId><ZIndex>2</ZIndex>
    <NormalInfo><Position><X>{x}</X><Y>{y}</Y><Width>{w}</Width><Height>{h}</Height></Position></NormalInfo>
    <DynamicGraphInfo><BitAddressInfo><Abbreviation>{abbreviation}</Abbreviation>
      <DeviceAndAbbreviation>Device1:[Ethernet ПЛК:Modbus_TCP]:{abbreviation}</DeviceAndAbbreviation>
      <AddressType>Bit</AddressType>{raw}</BitAddressInfo></DynamicGraphInfo>
  </GraphicsBase>'''


def _number(uid, x, y, w, h, main, register, abbreviation=""):
    return f'''  <GraphicsBase xsi:type="NumericCharInfo">
    <GraphicsName>Numerical Value/Characters</GraphicsName><UniqueId>{uid}</UniqueId><ZIndex>3</ZIndex>
    <DisplaySettings><Position><X>{x}</X><Y>{y}</Y><Width>{w}</Width><Height>{h}</Height></Position></DisplaySettings>
    <CommunicationSettingNew><ReadAddress><AddressType>Word</AddressType>
      <Raw><AddressWidth>Word</AddressWidth><DeviceId>dev-1</DeviceId><MainAddress>{main}</MainAddress>
        <RegisterId>{register}</RegisterId><Length>1</Length></Raw>
      <Abbreviation>{abbreviation}</Abbreviation></ReadAddress></CommunicationSettingNew>
  </GraphicsBase>'''


def _picture(uid, x, y, w, h):
    return f'''  <GraphicsBase xsi:type="StaticPictureInfo">
    <GraphicsName>Static Picture</GraphicsName><UniqueId>{uid}</UniqueId><ZIndex>0</ZIndex>
    <NormalInfo><Position><X>{x}</X><Y>{y}</Y><Width>{w}</Width><Height>{h}</Height></Position>
      <ImageData>iVBORw0KGgo=</ImageData></NormalInfo>
  </GraphicsBase>'''


@pytest.fixture
def oni(tmp_path):
    """A project with two windows: the main one 1024×768 and a popup 800×480."""
    root = tmp_path / "Line"
    (root / "HMI" / "Frame" / "Basic").mkdir(parents=True)
    (root / "HMI" / "System").mkdir(parents=True)
    (root / "Line.fsprj").write_text(
        f'<?xml version="1.0"?><Project xmlns="{NS}"><Version>1.7</Version>'
        f'<SoftwareVersion>2.8.11916.0</SoftwareVersion></Project>', encoding="utf-8")
    main = _window("win-main", "Basic Window", 1024, 768, "\n".join([
        _text("t1", "Нория 1", 20, 20, 200, 30),
        _switch("s1", 20, 60, 80, 40, abbreviation="4X_bit3.13"),
        _switch("s2", 20, 120, 80, 40, main="13", register="257"),          # SRB13
        _number("n1", 20, 180, 120, 30, main="799999", register="65791"),   # LW799999
        _number("n2", 20, 220, 120, 30, main="70", register="65792"),       # SRW70
        _picture("p1", 300, 60, 64, 64),
        _switch("s3", 20, 300, 80, 40),                                     # ни к чему не привязан
        _text("t2", "За окном", 1100, 800, 200, 40),                        # целиком за окном
    ]))
    (root / "HMI" / "Frame" / "Basic" / "win-main.wcfg").write_text(main, encoding="utf-8")
    popup = _window("win-popup", "Popup", 800, 480, _text("t3", "Ручной режим", 10, 10, 200, 30))
    (root / "HMI" / "Frame" / "Basic" / "win-popup.wcfg").write_text(popup, encoding="utf-8")
    (root / "HMI" / "System" / "ConnectInfo.cfg").write_text(
        f'<?xml version="1.0"?><ConnectInfo xmlns="{NS}"><InternetPLCInfo>'
        f'<DeviceAlias>Device1</DeviceAlias><PLCName>Modbus_TCP</PLCName><PLCID>400</PLCID>'
        f'<DefaultStation>1</DefaultStation></InternetPLCInfo></ConnectInfo>', encoding="utf-8")
    (root / "HMI" / "System" / "GlobalConfigInfo.cfg").write_text(
        f'<?xml version="1.0"?><GlobalConfigInfo xmlns="{NS}">'
        f'<InitWindow>win-main</InitWindow></GlobalConfigInfo>', encoding="utf-8")
    return root


def test_the_project_is_read_from_the_folder_the_fsprj_or_the_hmi_dir(oni):
    """Инженер показывает папку проекта, сам .fsprj или HMI — разбор находит проект в любом случае."""
    for given in (oni, oni / "Line.fsprj", oni / "HMI"):
        p = oniproj.load(given)
        assert p.root == oni and len(p.windows) == 2


def test_windows_carry_their_size_and_a_name_from_the_first_text(oni):
    """У окон нет своих имён: имя — первый текст на окне, личность — GUID."""
    got = oniproj.windows(oni)
    assert got["version"] == "1.7" and got["software"] == "2.8.11916.0"
    assert got["init_window"] == "win-main"
    assert got["devices"] == [{"name": "Device1", "plc": "Modbus_TCP", "id": "400", "station": "1"}]
    main = next(w for w in got["windows"] if w["id"] == "win-main")
    assert (main["width"], main["height"]) == (1024, 768)
    assert main["name"] == "Нория 1" and main["objects"] == 8


def test_an_address_is_the_abbreviation_or_is_built_from_the_register(oni):
    """Адрес — Abbreviation, а если её нет, то RegisterId + MainAddress: 257 → SRB13, 65791 → LW799999."""
    got = oniproj.addresses(oni)
    by = {a["address"]: a for a in got["addresses"]}
    assert "4X_bit3.13" in by and by["4X_bit3.13"]["type"] == "Bit"
    assert "SRB13" in by and by["SRB13"]["count"] == 1
    assert "LW799999" in by and "SRW70" in by
    assert by["SRB13"]["windows"] == ["win-main"]


def test_objects_show_what_they_are_and_what_they_read(oni):
    """Объект: тип словами, подпись, координаты, привязка и есть ли картинка."""
    got = oniproj.objects(oni, "Нория 1")
    items = {o["id"]: o for o in got["window"]["items"]}
    assert items["s1"]["kind"] == "клавиша / индикатор"
    assert items["s1"]["addresses"][0]["address"] == "4X_bit3.13"
    assert items["n1"]["addresses"][0]["address"] == "LW799999"
    assert items["p1"]["picture"] is True and items["t1"]["picture"] is False
    assert (items["t1"]["x"], items["t1"]["y"], items["t1"]["w"]) == (20, 20, 200)
    assert items["s3"]["addresses"] == []


def test_the_panel_resolution_is_the_biggest_window(oni):
    """Разрешение панели — самое большое окно: всплывающие меньше и экран не задают."""
    got = oniproj.panel(oni)
    assert got["panel"]["id"] == "1024x768" and got["panel"]["window"] == "win-main"
    assert "800×480" in got["panel"]["sizes"]
    assert [r["id"] for r in got["resolutions"]][:3] == ["800x480", "1024x600", "1024x768"]
    assert oniproj.resolution_of(800, 480)["id"] == "800x480"
    assert oniproj.resolution_of(1234, 567)["id"] == "1234x567"      # не из списка — честно говорим


def test_check_names_the_window_and_counts_the_objects(oni):
    """Проверка — по строке на окно: за окном, за краем больше 20 точек, ни к чему не привязан."""
    got = oniproj.check(oni)
    assert got["summary"]["error"] == 1
    assert got["windows"] == 2 and got["objects"] == 9 and got["addresses"] == 4
    errors = [i for i in got["issues"] if i["level"] == "error"]
    assert len(errors) == 1 and "целиком за окном" in errors[0]["text"]
    assert "Нория 1" in errors[0]["text"]
    warnings = " ".join(i["text"] for i in got["issues"] if i["level"] == "warning")
    assert "ни к чему не привязаны" in warnings


def test_a_new_project_is_created_at_the_chosen_resolution(tmp_path):
    """Разрешение — выбор инженера: проект под 800×480 получает окно 800×480, а не 1024×768 из константы."""
    got = oniproj.new_project(tmp_path / "Line", "Line", "800x480", title="Линия приёмки")
    assert got["panel"]["id"] == "800x480" and got["panel"]["w"] == 800
    assert got["devices"] == [{"name": "Device1", "plc": "Modbus_TCP", "id": "400", "station": "1"}]
    assert (tmp_path / "Line" / "Line.fsprj").is_file()
    back = oniproj.load(tmp_path / "Line")
    assert len(back.windows) == 1 and (back.windows[0].width, back.windows[0].height) == (800, 480)
    assert back.windows[0].name == "Линия приёмки"
    assert back.init_window == "win-main"
    with pytest.raises(oniproj.OniError, match="уже есть"):
        oniproj.new_project(tmp_path / "Line", "Line", "800x480")
    with pytest.raises(oniproj.OniError, match="не понято"):
        oniproj.new_project(tmp_path / "X", "X", "большой")


def test_a_window_is_written_back_without_losing_anything(oni):
    """Перезапись окна: разобранное окно до и после совпадает — объекты, типы, координаты, адреса."""
    p = oniproj.load(oni)
    w = p.window("Нория 1")
    before = [o.as_dict() for o in w.objects]
    got = oniproj.write_window(w)
    assert got["same"] is True and got["objects"] == len(before)
    assert (got["width"], got["height"]) == (1024, 768)
    back = oniproj.load(oni).window("Нория 1")
    assert [o.as_dict() for o in back.objects] == before


def test_a_carriage_return_survives_a_rewrite(tmp_path):
    """`\r\n` в подписи не превращается в `\n`: XML-парсер нормализует сырой CR, поэтому он экранируется."""
    root = tmp_path / "P"
    (root / "HMI" / "Frame" / "Basic").mkdir(parents=True)
    (root / "P.fsprj").write_text(f'<Project xmlns="{NS}"><Version>1</Version></Project>', encoding="utf-8")
    win = _window("w1", "Basic Window", 800, 480, _text("t1", "Перевести в &#13;&#10;ручной режим", 10, 10, 200, 30))
    (root / "HMI" / "Frame" / "Basic" / "w1.wcfg").write_text(win, encoding="utf-8")
    p = oniproj.load(root)
    assert p.windows[0].objects[0].label == "Перевести в \r\nручной режим"
    assert oniproj.write_window(p.windows[0])["same"] is True
    assert oniproj.load(root).windows[0].objects[0].label == "Перевести в \r\nручной режим"


def test_a_folder_that_is_not_an_oni_project_says_so(tmp_path):
    """Не проект ONI — понятная ошибка, а не пустой список окон."""
    with pytest.raises(oniproj.OniError, match="нет проекта ONI"):
        oniproj.load(tmp_path)
    (tmp_path / "x.txt").write_text("не проект", encoding="utf-8")
    with pytest.raises(oniproj.OniError, match="не проект ONI"):
        oniproj.load(tmp_path / "x.txt")


def test_the_mcp_server_serves_the_screens(oni):
    """Инструменты MCP: окна, объекты, адреса, проверка, разрешение — и ошибка на чужой папке."""
    code = f'''
import json, sys
sys.path.insert(0, {str(KIT)!r})
import server
out = []
for name, args in [("oni_windows", {{"path": {str(oni)!r}}}),
                   ("oni_objects", {{"path": {str(oni)!r}, "window": "Нория 1"}}),
                   ("oni_addresses", {{"path": {str(oni)!r}}}),
                   ("oni_check", {{"path": {str(oni)!r}}}),
                   ("oni_panel", {{"path": {str(oni)!r}}}),
                   ("oni_write_window", {{"path": {str(oni)!r}, "window": "Нория 1"}}),
                   ("oni_new_project", {{"path": {str(oni / "new")!r}, "name": "New", "resolution": "1280x800"}}),
                   ("oni_windows", {{"path": {str(oni / "nope")!r}}})]:
    r = server._call(name, args)
    out.append({{"name": name, "text": r["content"][0]["text"], "error": bool(r.get("isError"))}})
print(json.dumps(out, ensure_ascii=False))
'''
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert [o["error"] for o in out] == [False] * 7 + [True]
    assert json.loads(out[0]["text"])["windows"][0]["id"] == "win-main"
    assert json.loads(out[1]["text"])["window"]["name"] == "Нория 1"
    assert len(json.loads(out[2]["text"])["addresses"]) == 4
    assert json.loads(out[3]["text"])["summary"]["error"] == 1
    assert json.loads(out[4]["text"])["panel"]["id"] == "1024x768"
    assert json.loads(out[5]["text"])["same"] is True
    assert json.loads(out[6]["text"])["panel"]["id"] == "1280x800"
    assert "нет такой папки" in out[7]["text"]
