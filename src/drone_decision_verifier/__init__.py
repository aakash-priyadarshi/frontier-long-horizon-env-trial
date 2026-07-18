"""Privileged strict-verification surface for Talon simulations."""

from .hidden_scenarios import build_environment, controller_factory
from .scoring import DroneDecisionVerifier, VERIFIER_VERSION

__all__ = ["DroneDecisionVerifier", "VERIFIER_VERSION", "build_environment", "controller_factory"]
