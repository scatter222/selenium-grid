"""Consistency checks for infra/: templates, install scripts, and pinned versions."""

import json
import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
PLACEHOLDER = re.compile(r"@([A-Z_]+)@")
# template -> the script that renders it
RENDERERS = {
    INFRA / "hub" / "hub.toml.tmpl": INFRA / "hub" / "install.sh",
    INFRA / "node" / "node.toml.tmpl": INFRA / "node" / "install.sh",
    INFRA / "standalone" / "standalone.toml.tmpl": INFRA / "standalone" / "run.sh",
}


def _versions() -> dict[str, str]:
    pairs = (
        line.split("#", 1)[0].strip().split("=", 1)
        for line in (INFRA / "versions.env").read_text().splitlines()
    )
    return {p[0]: p[1] for p in pairs if len(p) == 2}


@pytest.mark.parametrize("template", list(RENDERERS), ids=lambda p: p.parent.name)
def test_every_placeholder_is_filled_by_its_script(template: Path) -> None:
    """Each @KEY@ in a template is passed as KEY=... by the script that renders it."""
    wanted = set(PLACEHOLDER.findall(template.read_text()))
    given = set(re.findall(r'"([A-Z_]+)=', RENDERERS[template].read_text()))
    assert wanted <= given, f"{template.name}: not filled: {sorted(wanted - given)}"


@pytest.mark.parametrize("template", list(RENDERERS), ids=lambda p: p.parent.name)
def test_rendered_template_is_valid_toml(template: Path) -> None:
    """With placeholders filled, the config parses and any stereotype is valid JSON."""
    numeric = {"PORT", "SESSIONS"}
    rendered = PLACEHOLDER.sub(
        lambda m: "2" if any(k in m.group(1) for k in numeric) else "x", template.read_text()
    )
    config = tomllib.loads(rendered)
    for driver in config.get("node", {}).get("driver-configuration", []):
        stereotype = json.loads(driver["stereotype"])
        assert stereotype["browserName"] == "firefox"


def test_grid_version_matches_python_client() -> None:
    """The Grid server jar and the selenium Python package are the same version."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pinned = next(d for d in pyproject["project"]["dependencies"] if d.startswith("selenium=="))
    assert pinned == f"selenium=={_versions()['SELENIUM_VERSION']}"


def test_checksums_are_pinned() -> None:
    """Every downloaded artifact has a SHA-256 in versions.env."""
    versions = _versions()
    for key in ("SELENIUM_JAR_SHA256", "GECKODRIVER_SHA256"):
        assert re.fullmatch(r"[0-9a-f]{64}", versions[key]), key


@pytest.mark.parametrize("unit", sorted(INFRA.glob("*/*.service")), ids=lambda p: p.name)
def test_units_use_installed_paths(unit: Path) -> None:
    """Systemd units point at the jar and config the install scripts write."""
    versions = _versions()
    text = unit.read_text()
    assert f"User={versions['SELENIUM_USER']}" in text
    assert f"{versions['SELENIUM_HOME']}/selenium-server.jar" in text
    assert f"--config {versions['SELENIUM_CONF']}/" in text
    assert "Environment=SE_OFFLINE=true" in text
