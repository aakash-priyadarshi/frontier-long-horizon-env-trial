from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_windows_one_click_launcher_bootstraps_and_starts_both_services() -> None:
    wrapper = read("start-frontier.cmd")
    script = read("scripts/start_frontier.ps1")

    assert "scripts\\start_frontier.ps1" in wrapper
    assert "Python.Python.3.12" in script
    assert "OpenJS.NodeJS.LTS" in script
    assert "Git.Git" in script
    assert "pip install -e" in script
    assert "npm.cmd ci" in script
    assert "evaluation_service.app:app" in script
    assert 'npm.cmd"' in script
    assert "/api/health" in script


def test_macos_one_click_launcher_bootstraps_and_starts_both_services() -> None:
    wrapper = read("start-frontier.command")
    script = read("scripts/start_frontier.sh")

    assert 'scripts/start_frontier.sh' in wrapper
    assert "python@3.12" in script
    assert 'install_or_upgrade_formula node' in script
    assert 'install_or_upgrade_formula git' in script
    assert 'pip install -e "$ROOT[test,adapters]"' in script
    assert 'npm ci --prefix "$DASHBOARD"' in script
    assert "evaluation_service.app:app" in script
    assert "npm run dev" in script
    assert "/api/health" in script


def test_ollama_is_optional_detected_and_never_auto_installed() -> None:
    scripts = (read("scripts/start_frontier.ps1"), read("scripts/start_frontier.sh"))

    for script in scripts:
        lowered = script.lower()
        assert "ollama is not installed" in lowered
        assert "local-model features will not" in lowered
        assert "ollama is installed and running" in lowered
        assert "tool compatibility" in lowered
        assert "/api/tags" in lowered
        assert "ollama pull" not in lowered
        assert "wingetpackage -id \"ollama" not in lowered
        assert "brew install ollama" not in lowered


def test_launchers_use_intentional_localhost_origin_and_loopback_bindings() -> None:
    for relative in ("scripts/start_frontier.ps1", "scripts/start_frontier.sh"):
        script = read(relative)
        assert "FRONTIER_DASHBOARD_ORIGIN" in script
        assert "http://localhost:" in script
        assert "127.0.0.1" in script
        assert "0.0.0.0" not in script
