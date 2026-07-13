"""Provider configuration and server-side URL security policy."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import ProviderConfigurationError


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    configured: bool
    detail: str


SECRET_ENV_VARS = {
    "openai-compatible": ("OPENAI_API_KEY", "OPENROUTER_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY",),
    "ollama": (),
    "scripted": (),
}


def configured(provider: str) -> bool:
    if provider in {"scripted", "ollama"}:
        return True
    return any(bool(os.getenv(name)) for name in SECRET_ENV_VARS.get(provider, ()))


def secret_for(provider: str) -> str | None:
    for name in SECRET_ENV_VARS.get(provider, ()):
        value = os.getenv(name)
        if value:
            return value
    return None


def base_url_for(provider: str) -> str:
    if provider == "ollama":
        return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")


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


def validate_provider_base_url(url: str) -> str:
    """Allow public HTTPS or explicit loopback HTTP; reject metadata/private SSRF targets."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ProviderConfigurationError("provider base URL must be an http(s) origin")
    host = parsed.hostname.lower()
    if host == "localhost":
        return url.rstrip("/")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror:
        addresses = set()
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback:
            continue
        if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ProviderConfigurationError("provider base URL resolves to a blocked network range")
    if parsed.scheme != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ProviderConfigurationError("public provider base URLs must use HTTPS")
    return url.rstrip("/")
