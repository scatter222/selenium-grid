"""Environment files: identical shape, valid, secret-free, markers declared."""

import re
import tomllib
from pathlib import Path

import pytest

from harness.config import env_files, key_paths, load_settings, read_yaml, resolve_secret
from harness.errors import ConfigError, MissingSecretError

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
ENV_DIR = ROOT / "env"
ENV_FILES = list(env_files(ENV_DIR))
SECRETISH = re.compile(r"(password|passwd|secret|token|api_?key|seed|credential)", re.I)


def test_both_kits_have_an_env_file() -> None:
    """The virtual and physical kits are both described."""
    assert {p.name for p in ENV_FILES} >= {"virtual.yaml", "physical.yaml"}


def test_all_env_files_have_identical_keys() -> None:
    """Every env file has exactly the same key paths as every other."""
    shapes = {p.name: key_paths(read_yaml(p)) for p in ENV_FILES}
    reference_name, reference = next(iter(shapes.items()))
    for name, shape in shapes.items():
        assert shape == reference, (
            f"{name} vs {reference_name}: "
            f"only in {name}: {sorted(shape - reference)}; "
            f"only in {reference_name}: {sorted(reference - shape)}"
        )


@pytest.mark.parametrize("path", ENV_FILES, ids=lambda p: p.name)
def test_env_file_validates(path: Path) -> None:
    """Each env file loads into Settings."""
    settings = load_settings(path)
    assert settings.apps


@pytest.mark.parametrize("path", ENV_FILES, ids=lambda p: p.name)
def test_env_file_contains_no_secret_values(path: Path) -> None:
    """Secret-looking keys only ever name an env var (``*_env``)."""
    offending = [
        key
        for key in key_paths(read_yaml(path))
        if SECRETISH.search(key.rsplit(".", 1)[-1]) and not key.endswith("_env")
    ]
    assert not offending, f"{path.name} has secret-looking keys: {offending}"


def test_secret_pasted_into_yaml_is_rejected(tmp_path: Path) -> None:
    """An unexpected ``password:`` key fails validation instead of being ignored."""
    text = (
        (ENV_DIR / "virtual.yaml")
        .read_text()
        .replace(
            "    password_env: HARNESS_STANDARD_PASSWORD",
            "    password_env: HARNESS_STANDARD_PASSWORD\n    password: hunter2",
        )
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text(text)
    with pytest.raises(ConfigError, match=r"users\.standard\.password"):
        load_settings(bad)


def test_every_app_has_a_pytest_marker() -> None:
    """Each app in any env file is declared as a marker (unknown markers are errors)."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    markers = {m.split(":")[0] for m in pyproject["tool"]["pytest"]["ini_options"]["markers"]}
    apps = {app for path in ENV_FILES for app in load_settings(path).apps}
    assert apps <= markers, f"apps without a marker in pyproject.toml: {sorted(apps - markers)}"


def test_missing_secrets_are_all_reported_at_once() -> None:
    """check_secrets names every missing variable, not just the first."""
    settings = load_settings(ENV_DIR / "virtual.yaml")
    with pytest.raises(MissingSecretError) as info:
        settings.check_secrets(environ={})
    assert info.value.missing == sorted(settings.secret_env_names())
    assert "HARNESS_VYOS_API_KEY" in str(info.value)


def test_resolve_secret_reads_env_and_fails_loudly() -> None:
    """A present secret is returned; an absent or empty one raises with its name."""
    assert resolve_secret("X_SECRET", {"X_SECRET": "s3cret"}) == "s3cret"
    with pytest.raises(MissingSecretError, match="X_SECRET"):
        resolve_secret("X_SECRET", {"X_SECRET": ""})


def test_missing_env_file_is_a_clear_error(tmp_path: Path) -> None:
    """Pointing --env at a missing file names the file."""
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.yaml")
