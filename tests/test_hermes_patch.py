"""The Hermes MCP scope compatibility patch (agents/sync/sysai_agent/hermes_patch.py): an ACP editor session must
resolve the owning profile's MCP connection, else every hub tool call from the SYSAI window answers «not connected».
Unit tests on a representative original source — no Hermes installation needed."""
import py_compile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "sync"))

from sysai_agent import hermes_patch as hp  # noqa: E402

ORIGINAL = '''"""Connection-ledger keys."""
from typing import Optional
from tools.mcp_tool_common import _core

ServerKey = str | tuple[str, str]


def _server_key(name, scope=None, *, current=True):
    return name if scope is None else (scope, name)


def _key_name(key):
    return key[1] if isinstance(key, tuple) else key


def _resolve_server_key(name: str, scope: Optional[str] = None, *, current: bool = True) -> ServerKey:
    """The connection key a call to *name* from *scope* must use."""
    if scope is None and current:
        scope = _core._mcp_registry_scope()
    own = _server_key(name, scope, current=False)
    if scope is None or own in _core._servers or own in _core._lazy_server_configs:
        return own
    for key, scopes in _core._server_tool_scopes.items():
        if scope in scopes and _key_name(key) == name and key in _core._servers:
            return key
    return own


# Ledgers keyed by connection key.
_KEYED_LEDGERS = ("_servers",)
'''


def test_patch_injects_the_profile_fallback_and_stays_valid_python(tmp_path):
    patched = hp.patch_text(ORIGINAL)
    assert patched is not None
    assert hp.MARKER in patched
    assert "registry.current_scope_key()" in patched
    assert patched.count("def _resolve_server_key(") == 1
    assert "_KEYED_LEDGERS" in patched                       # the rest of the file is untouched
    f = tmp_path / "mcp_tool_scope.py"
    f.write_text(patched, encoding="utf-8")
    py_compile.compile(str(f), doraise=True)


def test_patch_is_idempotent():
    patched = hp.patch_text(ORIGINAL)
    assert hp.patch_text(patched) is None


def test_ensure_patches_then_reports_already_and_backs_up(tmp_path):
    prof = tmp_path / "hermes" / "profiles" / "opo-test"
    prof.mkdir(parents=True)
    tools = tmp_path / "hermes" / "hermes-agent" / "tools"
    tools.mkdir(parents=True)
    target = tools / "mcp_tool_scope.py"
    target.write_text(ORIGINAL, encoding="utf-8")
    assert hp.ensure(prof) == "patched"
    assert hp.ensure(prof) == "already"
    assert (tools / "mcp_tool_scope.py.sysai-scope-backup").read_text(encoding="utf-8") == ORIGINAL
    assert hp.MARKER in target.read_text(encoding="utf-8")


def test_ensure_skips_unrecognised_or_absent(tmp_path):
    prof = tmp_path / "hermes" / "profiles" / "opo-test"
    prof.mkdir(parents=True)
    assert hp.ensure(prof) == "absent"
    tools = tmp_path / "hermes" / "hermes-agent" / "tools"
    tools.mkdir(parents=True)
    (tools / "mcp_tool_scope.py").write_text("def other():\n    pass\n", encoding="utf-8")
    assert hp.ensure(prof) == "unrecognised"
