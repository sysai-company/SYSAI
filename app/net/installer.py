"""What an employee's computer downloads from SYSAI (ОПО-6.2): the installer script and the synchronizer as a wheel,
built in memory from agents/sync — no build tools on the server, the code in the repository is the code on the PCs."""
import base64
import hashlib
import io
import re
import zipfile
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / "agents"
SYNC = AGENTS / "sync"
SCRIPT = AGENTS / "installer" / "install.ps1"
EXE = AGENTS / "installer" / "SYSAI-Setup.exe"
PACKAGE = "sysai_agent"
# the bootstrapper carries this marker and 1024 zero bytes after it (agents/installer/bootstrapper.c):
# the server writes the address and the one-time code there, so the downloaded file installs in one double click
MARKER = b"SYSAI-CFG-V1"
FIELD = 512
BLOCK = FIELD * 2
REQUIRES = ("cryptography>=41", "PyYAML>=6", 'keyring>=24; sys_platform == "win32"')
_cache: dict = {}


def version() -> str:
    text = (SYNC / PACKAGE / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else "0.0.0"


def wheel_name() -> str:
    return f"{PACKAGE}-{version()}-py3-none-any.whl"


def _sources() -> list:
    out = [(p.relative_to(SYNC).as_posix(), p.read_bytes()) for p in (SYNC / PACKAGE).rglob("*.py")
           if "__pycache__" not in p.parts]
    return sorted(out, key=lambda kv: kv[0])  # by name, as the synchronizer counts its own build (update.local_build)


def _key(sources: list) -> str:
    """The build: sha256 of the sources. Different sources — another build, even at the same version number, so a
    forgotten version bump can no longer leave every computer on an old build (TASKBAR B9)."""
    return hashlib.sha256(b"".join(n.encode() + b"\0" + d for n, d in sources)).hexdigest()


def build() -> str:
    """The build SYSAI gives out — what the synchronizer compares its own one with. It is the key the wheel is built
    from, so it always belongs to the bytes actually served."""
    wheel()
    return _cache["key"]


def _digest(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def _build(sources: list) -> tuple:
    ver = version()
    info = f"{PACKAGE}-{ver}.dist-info"
    meta = (f"Metadata-Version: 2.1\nName: sysai-agent\nVersion: {ver}\n"
            "Summary: SYSAI agent synchronizer: rules, SOUL.md and SYSAI_Hub on the employee's computer\n"
            "Requires-Python: >=3.11\n" + "".join(f"Requires-Dist: {r}\n" for r in REQUIRES))
    files = list(sources) + [
        (f"{info}/METADATA", meta.encode()),
        (f"{info}/WHEEL", b"Wheel-Version: 1.0\nGenerator: sysai\nRoot-Is-Purelib: true\nTag: py3-none-any\n"),
        (f"{info}/entry_points.txt", b"[console_scripts]\nsysai-agent = sysai_agent.cli:main\n\n"
                                     b"[gui_scripts]\nsysai-agentw = sysai_agent.cli:main_windowless\n"),
        (f"{info}/top_level.txt", b"sysai_agent\n"),
    ]
    record = "".join(f"{name},{_digest(data)},{len(data)}\n" for name, data in files) + f"{info}/RECORD,,\n"
    files.append((f"{info}/RECORD", record.encode()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o644 << 16
            archive.writestr(item, data)
    blob = out.getvalue()
    return wheel_name(), blob, hashlib.sha256(blob).hexdigest()


def wheel() -> tuple:
    """(file name, bytes, sha256), rebuilt only when the sources change."""
    sources = _sources()
    key = _key(sources)
    if _cache.get("key") != key:
        _cache.update(key=key, value=_build(sources))
    return _cache["value"]


def script(server: str) -> str:
    server = server.rstrip("/")
    name = wheel()[0]
    return (SCRIPT.read_text(encoding="utf-8").replace("__SYSAI_SERVER__", server)
            .replace("__SYSAI_WHEEL__", f"{server}/agents/api/sync/{name}").replace("__SYSAI_VERSION__", version()))


def one_liner(server: str, code: str = "") -> str:
    """The line to paste on the PC. A code is for a new computer only: a reinstall keeps the old connection
    (install.ps1 sees agent.json and skips connect), so «переустановить» never burns a one-time code."""
    url = f"irm {server.rstrip('/')}/agents/api/install.ps1 | iex"
    return f"$env:SYSAI_CODE='{code}'; {url}" if (code or "").strip() else url


def exe(server: str, code: str = "") -> bytes:
    """The one-click installer: the bootstrapper with this server and the one-time code written inside.

    The file is the same for everyone (agents/installer/SYSAI-Setup.exe, built by build.sh); only the
    configuration block changes, so the download is a byte copy with 1024 bytes replaced."""
    data = bytearray(EXE.read_bytes())
    at = data.find(MARKER)
    if at < 0 or at + len(MARKER) + BLOCK > len(data):
        raise FileNotFoundError("SYSAI-Setup.exe: нет блока настроек — пересоберите agents/installer/build.sh")
    server_b = server.rstrip("/").encode("utf-8")[:FIELD - 1]
    code_b = (code or "").strip().encode("utf-8")[:FIELD - 1]
    data[at + len(MARKER):at + len(MARKER) + BLOCK] = server_b.ljust(FIELD, b"\0") + code_b.ljust(FIELD, b"\0")
    return bytes(data)


def exe_name(agent: str = "") -> str:
    return f"SYSAI-Setup-{agent}.exe" if agent else "SYSAI-Setup.exe"
