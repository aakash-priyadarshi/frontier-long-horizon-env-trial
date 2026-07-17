"""Runtime provider credentials and server-side URL security policy."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import threading
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from .errors import ProviderConfigurationError


SECRET_ENV_VARS = {
    "openai-compatible": ("OPENAI_API_KEY", "OPENROUTER_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY",),
    "ollama": (),
    "scripted": (),
}

BASE_URL_ENV_VARS = {
    "openai-compatible": "OPENAI_BASE_URL",
    "ollama": "OLLAMA_BASE_URL",
}

DEFAULT_BASE_URLS = {
    "openai-compatible": "https://api.openai.com/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_ENV_BYTES = 1_048_576


def _parse_local_env(path: Path | None) -> dict[str, str]:
    """Read literal dotenv values without expansion, execution, or secret logging."""

    if path is None or not path.is_file():
        return {}
    try:
        if path.stat().st_size > _MAX_ENV_BYTES:
            raise ProviderConfigurationError("local .env file is too large")
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProviderConfigurationError("local .env file could not be read") from exc
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or not _ENV_NAME.fullmatch(name):
            continue
        raw_value = raw_value.strip()
        if raw_value.startswith('"') and raw_value.endswith('"'):
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, str):
                continue
        elif raw_value.startswith("'") and raw_value.endswith("'"):
            value = raw_value[1:-1]
        else:
            value = raw_value
        if "\0" not in value:
            values[name] = value
    return values


def validate_provider_base_url(url: str, *, local_only: bool = False) -> str:
    """Allow public HTTPS or explicit loopback HTTP and reject unsafe targets."""
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderConfigurationError("provider base URL must be an http(s) origin without credentials, query, or fragment")
    host = parsed.hostname.lower()
    if host == "localhost":
        if parsed.scheme != "http" and local_only:
            raise ProviderConfigurationError("local provider URLs must use loopback HTTP")
        return url.rstrip("/")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror:
        addresses = set()
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback:
            continue
        if local_only:
            raise ProviderConfigurationError("local provider URLs must resolve to loopback")
        if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ProviderConfigurationError("provider base URL resolves to a blocked network range")
    if local_only and not addresses:
        raise ProviderConfigurationError("local provider URL must resolve to loopback")
    if parsed.scheme != "https" and host not in {"127.0.0.1", "::1"}:
        raise ProviderConfigurationError("public provider base URLs must use HTTPS")
    return url.rstrip("/")


class RuntimeProviderSettings:
    """Server-side settings with session, local-dotenv, and process-env precedence."""

    def __init__(
        self,
        environment: Mapping[str, str] | None = None,
        *,
        local_env_path: Path | None = None,
    ) -> None:
        self._environment = environment if environment is not None else os.environ
        self._local_env_path = local_env_path
        self._local_environment = _parse_local_env(local_env_path)
        self._session_credentials: dict[str, str] = {}
        self._session_base_urls: dict[str, str] = {}
        self._lock = threading.RLock()

    def credential_source(self, provider: str) -> str:
        if provider not in SECRET_ENV_VARS:
            raise KeyError(provider)
        if not SECRET_ENV_VARS[provider]:
            return "not_required"
        with self._lock:
            if provider in self._session_credentials:
                return "session"
            if any(bool(self._local_environment.get(name)) for name in SECRET_ENV_VARS[provider]):
                return "local_env"
        if any(bool(self._environment.get(name)) for name in SECRET_ENV_VARS[provider]):
            return "environment"
        return "missing"

    def configured(self, provider: str) -> bool:
        return self.credential_source(provider) != "missing"

    def secret_for(self, provider: str) -> str | None:
        with self._lock:
            secret = self._session_credentials.get(provider)
            local_values = dict(self._local_environment)
        if secret:
            return secret
        for name in SECRET_ENV_VARS.get(provider, ()):
            value = local_values.get(name)
            if value:
                return value
            value = self._environment.get(name)
            if value:
                return value
        return None

    @staticmethod
    def _validate_credential(provider: str, secret: str) -> str:
        if provider not in SECRET_ENV_VARS or not SECRET_ENV_VARS[provider]:
            raise ProviderConfigurationError("this provider does not accept credentials")
        if not secret or len(secret) > 16_384 or any(character in secret for character in "\r\n\0"):
            raise ProviderConfigurationError("credential format is invalid")
        return secret

    def update_session(
        self,
        provider: str,
        *,
        credential: str | None = None,
        update_credential: bool = False,
        base_url: str | None = None,
        update_base_url: bool = False,
    ) -> None:
        validated_credential = None
        validated_base_url = None
        if update_credential:
            if credential is None:
                raise ProviderConfigurationError("credential cannot be null")
            validated_credential = self._validate_credential(provider, credential)
        if update_base_url:
            if provider not in BASE_URL_ENV_VARS:
                if base_url:
                    raise ProviderConfigurationError("this provider does not support a custom base URL")
            elif base_url:
                validated_base_url = validate_provider_base_url(base_url, local_only=provider == "ollama")
        with self._lock:
            if update_credential and validated_credential is not None:
                self._session_credentials[provider] = validated_credential
            if update_base_url and provider in BASE_URL_ENV_VARS:
                if validated_base_url:
                    self._session_base_urls[provider] = validated_base_url
                else:
                    self._session_base_urls.pop(provider, None)

    def set_session_credential(self, provider: str, secret: str) -> None:
        self.update_session(provider, credential=secret, update_credential=True)

    def clear_session_credential(self, provider: str) -> bool:
        with self._lock:
            return self._session_credentials.pop(provider, None) is not None

    def _write_local_environment(self, updates: Mapping[str, str | None]) -> None:
        path = self._local_env_path
        if path is None:
            raise ProviderConfigurationError("local .env persistence is not configured")
        try:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError as exc:
            raise ProviderConfigurationError("local .env file could not be read") from exc
        if len(existing.encode("utf-8")) > _MAX_ENV_BYTES:
            raise ProviderConfigurationError("local .env file is too large")
        pending = dict(updates)
        lines: list[str] = []
        for line in existing.splitlines():
            candidate = line.strip()
            if candidate.startswith("export "):
                candidate = candidate[7:].lstrip()
            name = candidate.partition("=")[0].strip()
            if name in pending and _ENV_NAME.fullmatch(name):
                value = pending.pop(name)
                if value is not None:
                    lines.append(f"{name}={json.dumps(value)}")
                continue
            lines.append(line)
        for name, value in pending.items():
            if value is not None:
                lines.append(f"{name}={json.dumps(value)}")
        content = "\n".join(lines).rstrip("\n") + "\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            temporary.write_text(content, encoding="utf-8")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, path)
        except OSError as exc:
            raise ProviderConfigurationError("local .env file could not be updated") from exc
        self._local_environment = _parse_local_env(path)

    def persist_local(
        self,
        provider: str,
        *,
        credential: str | None = None,
        update_credential: bool = False,
        base_url: str | None = None,
        update_base_url: bool = False,
    ) -> None:
        """Atomically persist an explicitly opted-in provider configuration."""

        updates: dict[str, str | None] = {}
        if update_credential:
            if credential is None:
                raise ProviderConfigurationError("credential cannot be null")
            validated = self._validate_credential(provider, credential)
            for index, name in enumerate(SECRET_ENV_VARS[provider]):
                updates[name] = validated if index == 0 else None
        if update_base_url:
            env_name = BASE_URL_ENV_VARS.get(provider)
            if env_name is None:
                if base_url:
                    raise ProviderConfigurationError("this provider does not support a custom base URL")
            else:
                updates[env_name] = (
                    validate_provider_base_url(base_url, local_only=provider == "ollama")
                    if base_url else None
                )
        if not updates:
            raise ProviderConfigurationError("credential or base URL is required")
        with self._lock:
            self._write_local_environment(updates)
            if update_credential:
                self._session_credentials.pop(provider, None)
            if update_base_url:
                self._session_base_urls.pop(provider, None)

    def clear_local_credential(self, provider: str) -> bool:
        names = SECRET_ENV_VARS.get(provider)
        if not names:
            return False
        with self._lock:
            existed = any(bool(self._local_environment.get(name)) for name in names)
            if existed:
                self._write_local_environment({name: None for name in names})
            return existed

    def base_url_for(self, provider: str) -> str:
        if provider not in BASE_URL_ENV_VARS:
            raise ProviderConfigurationError("this provider does not support a custom base URL")
        with self._lock:
            session_value = self._session_base_urls.get(provider)
            local_value = self._local_environment.get(BASE_URL_ENV_VARS[provider])
        value = session_value or local_value or self._environment.get(BASE_URL_ENV_VARS[provider]) or DEFAULT_BASE_URLS[provider]
        return validate_provider_base_url(value, local_only=provider == "ollama")

    def set_session_base_url(self, provider: str, url: str | None) -> None:
        self.update_session(provider, base_url=url, update_base_url=True)

    def public_base_url(self, provider: str) -> str | None:
        if provider not in BASE_URL_ENV_VARS:
            return None
        return self.base_url_for(provider)


_DEFAULT_SETTINGS = RuntimeProviderSettings()


def configured(provider: str, settings: RuntimeProviderSettings | None = None) -> bool:
    return (settings or _DEFAULT_SETTINGS).configured(provider)


def secret_for(provider: str, settings: RuntimeProviderSettings | None = None) -> str | None:
    return (settings or _DEFAULT_SETTINGS).secret_for(provider)


def base_url_for(provider: str, settings: RuntimeProviderSettings | None = None) -> str:
    return (settings or _DEFAULT_SETTINGS).base_url_for(provider)


def custom_headers_for(provider: str) -> dict[str, str]:
    if provider != "openai-compatible":
        return {}
    raw = os.getenv("OPENAI_EXTRA_HEADERS_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderConfigurationError("OPENAI_EXTRA_HEADERS_JSON must be valid JSON") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
    ):
        raise ProviderConfigurationError("OPENAI_EXTRA_HEADERS_JSON must be a string mapping")
    return parsed
