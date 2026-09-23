"""Enforce the layering rules by inspecting source code (backs up ruff's TID251)."""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "harness"
SELENIUM_ALLOWED = {SRC / "driver.py", SRC / "waits.py"}
ALL_PY = sorted(
    p for d in ("src", "tests", "ci") for p in (ROOT / d).rglob("*.py") if ".venv" not in p.parts
)
TEST_FILES = sorted((ROOT / "tests").rglob("test_*.py"))
PAGE_FILES = sorted((SRC / "pages").rglob("*.py"))


def _imports(path: Path) -> Iterator[str]:
    """Yield every module (and ``module.name``) imported by ``path``."""
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def test_only_toolkit_imports_selenium() -> None:
    """Rule 3: selenium is imported only by harness.driver and harness.waits."""
    offenders = [
        _rel(p)
        for p in ALL_PY
        if p not in SELENIUM_ALLOWED
        and any(m == "selenium" or m.startswith("selenium.") for m in _imports(p))
    ]
    assert not offenders, f"selenium imported outside the toolkit: {offenders}"


def _is_sleep(node: ast.AST) -> bool:
    """True for ``x.sleep`` attribute access or ``from x import sleep``."""
    if isinstance(node, ast.Attribute):
        return node.attr == "sleep"
    if isinstance(node, ast.ImportFrom):
        return any(alias.name == "sleep" for alias in node.names)
    return False


def test_no_sleep_anywhere() -> None:
    """Rule 4: nothing calls or imports time.sleep (or asyncio.sleep)."""
    offenders = [
        f"{_rel(path)}:{getattr(node, 'lineno', '?')}"
        for path in ALL_PY
        for node in ast.walk(ast.parse(path.read_text()))
        if _is_sleep(node)
    ]
    assert not offenders, f"sleep found at: {offenders}"


def test_tests_use_no_locators_or_waits() -> None:
    """Rule 1: test modules never touch the wait/locator toolkit or the raw driver API."""
    banned = ("harness.waits", "harness.driver", "selenium")
    offenders = [
        f"{_rel(p)} imports {m}"
        for p in TEST_FILES
        if p.parent.name != "unit"
        for m in _imports(p)
        if m.startswith(banned)
    ]
    assert not offenders, offenders


def test_page_objects_do_not_read_config() -> None:
    """Rule 2: page objects never import the config layer or read the environment."""
    offenders = [
        f"{_rel(p)} imports {m}"
        for p in PAGE_FILES
        for m in _imports(p)
        if m.startswith(("harness.config", "os", "pydantic", "yaml", "dotenv"))
    ]
    assert not offenders, offenders
