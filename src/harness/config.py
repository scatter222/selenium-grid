"""Configuration layer.

Two sources feed the harness:

* An environment YAML file (``env/virtual.yaml`` or ``env/physical.yaml``) holding
  every *non-secret* value. It is validated into :class:`Settings`.
* Environment variables holding every *secret*. The YAML only names the variable
  (fields ending in ``_env``); :func:`resolve_secret` reads it and fails loudly if
  it is absent.

Run-level switches (which YAML file, whether a missing kit is fatal) come from
:class:`RunOptions`, a pydantic-settings model that reads ``HARNESS_*`` variables.
Page objects never import this module; fixtures pass them plain values instead.
"""

from __future__ import annotations

import os
import ssl
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PositiveFloat,
    PositiveInt,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from harness.errors import ConfigError, MissingSecretError

EnvVarName = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
"""Name of an environment variable that holds a secret."""


class _Strict(BaseModel):
    """Base for config sections: immutable, and unknown keys are an error.

    ``extra="forbid"`` is what stops a secret being pasted into YAML under an
    unexpected key such as ``password:`` -- validation fails instead.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class GridConfig(_Strict):
    """Selenium Grid hub location and the capacity we expect it to offer."""

    hub_url: HttpUrl
    expected_slots: dict[str, PositiveInt] = Field(
        description="Minimum number of slots per browserName, checked by ci/check_grid.py.",
    )


class BrowserConfig(_Strict):
    """Browser requested from the Grid. Nodes are Linux laptop images running Firefox."""

    name: Literal["firefox"]
    version: str = Field(description="browserVersion capability; empty string means any.")
    platform: str = "linux"
    headless: bool
    capture_console: bool = Field(
        description="Collect console output over WebDriver BiDi (Firefox has no get_log).",
    )
    accept_insecure_certs: bool


class TimeoutConfig(_Strict):
    """All timeouts, in seconds."""

    page_load: PositiveFloat
    element: PositiveFloat
    health_request: PositiveFloat
    health_total: PositiveFloat = Field(description="Overall budget for ci/wait_healthy.py.")
    grid_command: PositiveInt = Field(description="HTTP timeout for WebDriver commands.")


class TlsConfig(_Strict):
    """TLS verification for HTTP calls made from the runner (health checks, Grid)."""

    verify: bool
    ca_bundle: Path | None = Field(description="Internal CA bundle; null uses system CAs.")

    def httpx_verify(self) -> ssl.SSLContext | bool:
        """Return a value suitable for ``httpx.Client(verify=...)``."""
        if not self.verify:
            return False
        if self.ca_bundle is None:
            return True
        if not self.ca_bundle.is_file():
            raise ConfigError(f"tls.ca_bundle does not exist: {self.ca_bundle}")
        return ssl.create_default_context(cafile=str(self.ca_bundle))


class NetworkConfig(_Strict):
    """How the runner reaches the kit."""

    use_env_proxy: bool = Field(
        description="Honour HTTP(S)_PROXY for runner-to-kit traffic. Normally false.",
    )


class ChecksConfig(_Strict):
    """Which readiness checks run from the runner.

    Every check is an HTTP call from wherever pytest runs, normally the management
    network. Turn one off if that network can't reach the target; the Grid check
    always runs. See infra/README.md for how to find out what's reachable.
    """

    vyos: bool
    idp: bool
    apps: bool


class IdpConfig(_Strict):
    """Keycloak-style OIDC identity provider."""

    base_url: HttpUrl
    realm: str
    entry_app: str = Field(description="App whose URL starts the UI login flow.")
    health_path: str
    cookie_landing_path: str = Field(
        description="Cheap same-origin path loaded before injecting cookies (no redirect).",
    )


class VyosConfig(_Strict):
    """VyOS router HTTPS API used for the readiness check."""

    api_url: HttpUrl
    api_key_env: EnvVarName


class AppConfig(_Strict):
    """One web application VM."""

    base_url: HttpUrl
    health_path: str
    cookie_landing_path: str


class UserConfig(_Strict):
    """A test user. Only the *names* of the secret variables live here."""

    username: str
    role: str
    password_env: EnvVarName
    totp_seed_env: EnvVarName | None = Field(
        description="Env var holding the base32 TOTP seed; null if the user has no MFA.",
    )


class Settings(_Strict):
    """Validated contents of one environment YAML file."""

    name: str
    grid: GridConfig
    browser: BrowserConfig
    timeouts: TimeoutConfig
    tls: TlsConfig
    network: NetworkConfig
    checks: ChecksConfig
    idp: IdpConfig
    vyos: VyosConfig
    apps: dict[str, AppConfig]
    users: dict[str, UserConfig]
    default_user: str

    @model_validator(mode="after")
    def _references_exist(self) -> Self:
        if self.default_user not in self.users:
            known = ", ".join(sorted(self.users)) or "<none>"
            raise ValueError(f"default_user {self.default_user!r} is not in users ({known})")
        if self.idp.entry_app not in self.apps:
            known = ", ".join(sorted(self.apps)) or "<none>"
            raise ValueError(f"idp.entry_app {self.idp.entry_app!r} is not in apps ({known})")
        return self

    def secret_env_names(self) -> list[str]:
        """Return every environment variable name this config expects to hold a secret.

        The VyOS API key is only required while ``checks.vyos`` is enabled.
        """
        names = [self.vyos.api_key_env] if self.checks.vyos else []
        for user in self.users.values():
            names.append(user.password_env)
            if user.totp_seed_env is not None:
                names.append(user.totp_seed_env)
        return names

    def check_secrets(self, environ: Mapping[str, str] | None = None) -> None:
        """Raise :class:`MissingSecretError` naming *all* unset secret variables at once."""
        env = os.environ if environ is None else environ
        missing = [name for name in self.secret_env_names() if not env.get(name)]
        if missing:
            raise MissingSecretError(missing)

    def app(self, name: str) -> AppConfig:
        """Return the config for app ``name`` or raise a :class:`ConfigError` listing valid apps."""
        try:
            return self.apps[name]
        except KeyError:
            known = ", ".join(sorted(self.apps))
            raise ConfigError(f"Unknown app {name!r}; configured apps: {known}") from None

    def user(self, key: str) -> UserConfig:
        """Return the config for user ``key`` or raise a :class:`ConfigError`."""
        try:
            return self.users[key]
        except KeyError:
            known = ", ".join(sorted(self.users))
            raise ConfigError(f"Unknown user {key!r}; configured users: {known}") from None


def resolve_secret(env_name: str, environ: Mapping[str, str] | None = None) -> str:
    """Return the value of secret variable ``env_name``; raise if it is unset or empty."""
    env = os.environ if environ is None else environ
    value = env.get(env_name)
    if not value:
        raise MissingSecretError([env_name])
    return value


def read_yaml(path: Path) -> dict[str, object]:
    """Read ``path`` as a YAML mapping, raising :class:`ConfigError` on any problem."""
    if not path.is_file():
        raise ConfigError(f"Environment file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Environment file {path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Environment file {path} must contain a mapping at the top level")
    return data


def load_settings(path: Path | str) -> Settings:
    """Load and validate an environment YAML file into :class:`Settings`."""
    path = Path(path)
    data = read_yaml(path)
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        lines = [
            f"  - {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        ]
        raise ConfigError(f"Invalid environment file {path}:\n" + "\n".join(lines)) from exc


def key_paths(node: object, prefix: str = "") -> set[str]:
    """Return the set of dotted key paths in a parsed YAML tree.

    Lists contribute ``[]`` to the path so list items are compared structurally.
    Used to assert that every environment file has an identical shape.
    """
    paths: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths |= key_paths(value, path)
    elif isinstance(node, list):
        for item in node:
            paths |= key_paths(item, f"{prefix}[]")
    return paths


class RunOptions(BaseSettings):
    """Run-level switches read from ``HARNESS_*`` environment variables.

    Command-line flags (``--env``, ``--require-kit``) take precedence over these.
    """

    model_config = SettingsConfigDict(env_prefix="HARNESS_", extra="ignore")

    env_file: Path = Path("env/virtual.yaml")
    require_kit: bool = False


def env_files(directory: Path) -> Iterable[Path]:
    """Yield every environment YAML file in ``directory``, sorted by name."""
    return sorted(directory.glob("*.yaml"))
