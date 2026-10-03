"""Path safety and name sanitization."""

import pytest

from server.errors import McpError
from server.security.paths import resolve_inside_root, sanitize_name, is_within
from server.config import config


def test_reject_traversal():
    with pytest.raises(McpError):
        resolve_inside_root("../../secret.txt")


def test_reject_windows_system_path():
    with pytest.raises(McpError):
        resolve_inside_root(r"C:\Windows\System32\drivers\etc\hosts")


def test_reject_unc():
    with pytest.raises(McpError):
        resolve_inside_root(r"\\server\share\evil.fzz")


def test_reject_arbitrary_drive():
    with pytest.raises(McpError):
        resolve_inside_root(r"D:\evil.fzz")


def test_project_dir_inside_root_ok():
    p = resolve_inside_root(str(config.projects_active / "WTL-FZ-2026-0001"))
    assert is_within(p, config.projects_dir)


def test_name_sanitization_powershell_injection():
    with pytest.raises(McpError):
        sanitize_name('x; rm -rf C:\\')
    with pytest.raises(McpError):
        sanitize_name("name`whoami")


def test_name_sanitization_ok():
    assert sanitize_name("My LED Circuit 2026") == "My LED Circuit 2026"
