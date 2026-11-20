import struct

from app.net import installer


def test_agent_installer_has_official_hermes_github_fallback():
    script = installer.script("https://sysai.example")

    primary = "https://hermes-agent.nousresearch.com/install.ps1"
    fallback = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1"

    assert primary in script
    assert fallback in script
    assert script.index(primary) < script.index(fallback)
    assert "Invoke-WebRequest -Uri $source.Url -UseBasicParsing -ErrorAction Stop" in script
    assert "Hermes Agent bootstrap:" in script
    assert "не удалось загрузить официальный установщик Hermes" in script


def test_the_one_click_installer_opens_a_window_not_a_console():
    """`SYSAI-Setup.exe` — окно, а не чёрная консоль: инженер запускает файл двойным щелчком.

    В PE-заголовке это подсистема: 2 = Windows GUI, 3 = консоль. Проверяем двоичный файл, который лежит в
    репозитории и отдаётся сервером, — иначе «переделали в окно» останется обещанием.
    """
    data = installer.exe("https://sysai.example", "ABCD-1234")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    subsystem = struct.unpack_from("<H", data, pe + 24 + 68)[0]
    assert subsystem == 2, "установщик — графическое приложение, консольного окна быть не должно"
    assert data[:2] == b"MZ"


def test_the_installer_carries_the_server_and_the_code_once():
    data = installer.exe("https://sysai.example", "WXYZ-9876")
    assert data.count(b"SYSAI-CFG-V1") == 1, "блок конфигурации должен находиться однозначно"
    at = data.index(b"SYSAI-CFG-V1") + 12
    assert data[at:at + 64].split(b"\x00")[0] == b"https://sysai.example"
    assert data[at + 512:at + 512 + 64].split(b"\x00")[0] == b"WXYZ-9876"
