"""Neutral provider error types."""

from __future__ import annotations


class ModelRunnerError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_error", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ProviderConfigurationError(ModelRunnerError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="provider_not_configured", retryable=False)


class MalformedModelResponse(ModelRunnerError):
    def __init__(self, message: str = "provider returned a malformed tool call") -> None:
        super().__init__(message, code="malformed_model_response", retryable=False)


class ProviderTimeout(ModelRunnerError):
    def __init__(self) -> None:
        super().__init__("provider request timed out", code="provider_timeout", retryable=True)
