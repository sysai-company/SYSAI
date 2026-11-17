"""Compatibility patch for Hermes MCP scope resolution (profile multiplexer + ACP editor sessions).

Upstream bug: an ACP editor session runs under a private registry scope (``editor-session:…``), while the profile's
MCP connections are keyed ``(profile_scope, name)``. ``_resolve_server_key`` looks only under the session's own scope
and the adopted shares, never the owning profile — so every hub tool call from the SYSAI window answers
«MCP server '…' is not connected» even though the server is registered and healthy. This injects a fallback to the
owning profile's connection (``registry.current_scope_key()``), then the bare name for single-profile processes.

Idempotent (a marker guards re-application), re-applied after a Hermes update, backs the original up once. Remove
this module once upstream Hermes ships the fix. The SYSAI synchronizer calls ``ensure`` on every full sync."""
import re
import shutil
from pathlib import Path

MARKER = "# SYSAI-SCOPE-FIX"
# The adoption loop ends with this line; everything between it and the function's final ``return own`` is replaced.
_LOOP_END = "            return key\n"
_FINAL_RETURN = "    return own"
_FALLBACK = (
    "    " + MARKER + ": an ACP editor session resolves the owning profile's connection.\n"
    "    from tools.registry import current_session_tool_scope, registry\n"
    "    if current_session_tool_scope() == scope:\n"
    "        profile_key = _server_key(name, registry.current_scope_key(), current=False)\n"
    "        if profile_key in _core._servers or profile_key in _core._lazy_server_configs:\n"
    "            return profile_key\n"
    "        process_key = _server_key(name, None, current=False)\n"
    "        if process_key in _core._servers or process_key in _core._lazy_server_configs:\n"
    "            return process_key\n"
    "    return own"
)


def scope_file(profile_dir: Path) -> Path:
    """<hermes root>/hermes-agent/tools/mcp_tool_scope.py from a profile dir <root>/profiles/<name>."""
    return Path(profile_dir).parent.parent / "hermes-agent" / "tools" / "mcp_tool_scope.py"


def patch_text(text: str) -> str | None:
    """The patched source, or None when already patched / the expected structure is absent (never guess)."""
    if MARKER in text:
        return None
    start = text.find("def _resolve_server_key(")
    if start < 0:
        return None
    # the function block ends at the next top-level definition / section comment
    nxt = re.search(r"\n(?:def |class |# [A-Z])", text[start + 1:])
    end = start + 1 + nxt.start() if nxt else len(text)
    func = text[start:end]
    a = func.find(_LOOP_END)
    b = func.find(_FINAL_RETURN, a + len(_LOOP_END)) if a >= 0 else -1
    if a < 0 or b < 0:
        return None
    after_loop = a + len(_LOOP_END)
    new_func = func[:after_loop] + _FALLBACK + func[b + len(_FINAL_RETURN):]
    return text[:start] + new_func + text[end:]


def ensure(profile_dir: Path) -> str:
    """Apply the patch if needed: «already» / «patched» / «absent» / «unrecognised». Never raises on structure."""
    path = scope_file(profile_dir)
    if not path.is_file():
        return "absent"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "absent"
    patched = patch_text(text)
    if patched is None:
        return "already" if MARKER in text else "unrecognised"
    try:
        backup = path.with_suffix(".py.sysai-scope-backup")
        if not backup.exists():
            shutil.copyfile(path, backup)
        path.write_text(patched, encoding="utf-8", newline="\n")
    except OSError:
        return "error"  # read-only installation / locked file: report, never crash the sync
    return "patched"
