from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from drone_decision_ground.observation import PublicObservation
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import build_environment
from drone_decision_verifier.leak_detection import find_public_leaks
from drone_training.api import build_talon_router
from drone_training.orchestration import TalonOrchestrator
from drone_training.persistence import TalonStore
from drone_training.replay import build_public_replay
from drone_training.scripted import SafeScriptedPolicy
from evaluation_service.settings import Settings


def _completed_public_episode() -> dict:
    config = ScenarioConfig(family_id="authorised_inspection", partition="evaluation")
    env = build_environment(config)
    policy = SafeScriptedPolicy()
    policy.reset()
    raw, _ = env.reset(seed=0, options={"scenario_config": config})
    while True:
        recommendation = policy.recommend(PublicObservation.model_validate(raw))
        raw, _, terminated, truncated, _ = env.step(recommendation)
        if terminated or truncated:
            break
    return {
        "schema_version": "talon.public-evaluation-episode/3.0",
        "evaluation_id": "talon_eval_replaytest",
        "checkpoint_digest": "sha256:" + "2" * 64,
        "environment_version": "talon.environment/2.0",
        "verifier_version": "talon.verifier/2.0",
        "result": env.grade(),
        "timeline": env.transcript(),
    }


def _app(tmp_path: Path) -> tuple[FastAPI, TalonStore]:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    settings = Settings(
        data_dir=tmp_path / "frontier",
        database_path=tmp_path / "frontier" / "evaluations.sqlite3",
        talon_data_dir=tmp_path,
        talon_database_path=tmp_path / "talon.sqlite3",
    )
    app = FastAPI()
    app.include_router(build_talon_router(store, orchestrator, settings))
    return app, store


def test_offline_routes_are_local_origin_bound_and_strict(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        rejected = client.post(
            "/api/drone/offline-rl/training-runs",
            json={"dataset_id": "dataset_" + "0" * 24},
            headers={"Origin": "https://unapproved.example"},
        )
        assert rejected.status_code == 403
        unavailable = client.post(
            "/api/drone/offline-rl/training-runs",
            json={"dataset_id": "dataset_" + "0" * 24},
            headers={"Origin": "http://localhost:3000"},
        )
        assert unavailable.status_code == 409
        malformed = client.post(
            "/api/drone/offline-rl/training-runs",
            json={"dataset_id": "dataset_" + "0" * 24, "unknown": True},
            headers={"Origin": "http://localhost:3000"},
        )
        assert malformed.status_code == 422
    store.close()


def test_public_replay_routes_export_and_sse_are_allowlisted(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    episode = _completed_public_episode()
    replay = build_public_replay(episode)
    episode["replay"] = replay.model_dump(mode="json")
    record_id = "talon_eval_" + "a" * 32
    store.create_record(record_id, "evaluation", {"schema_version": "talon.public-evaluation-record/3.0", "configuration": {}, "application_commit": "test"})
    store.finalize(record_id, "completed", {"episodes": [episode], "aggregate": {"episode_count": 1}})
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        path = f"/api/drone/episodes/{replay.episode_id}/replay"
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["replay_digest"] == replay.replay_digest
        assert find_public_leaks(response.json()) == []
        exported = client.get(path + "/export.json")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        assert find_public_leaks(exported.json()) == []
        with client.stream("GET", path + "/events") as events:
            body = "".join(events.iter_text())
        assert "event: replay_step" in body and "event: terminal" in body
        assert find_public_leaks(json.loads(next(line.removeprefix("data: ") for line in body.splitlines() if line.startswith("data: ")))) == []
        assert client.get(path + "/private").status_code == 404
    store.close()


def _seed_completed_evaluation(
    store: TalonStore,
    evaluation_id: str,
    *,
    domain: str,
    environment_version: str = "talon.environment/2.0",
    verifier_version: str = "talon.verifier/2.0",
    model_id: str = "model_alpha",
    algorithm: str = "behaviour_cloning",
) -> None:
    store.create_record(
        evaluation_id,
        "evaluation",
        {
            "schema_version": "talon.public-evaluation-record/3.0",
            "configuration": {},
            "application_commit": "test",
            "model_id": model_id,
            "algorithm": algorithm,
        },
    )
    store.finalize(
        evaluation_id,
        "completed",
        {
            "episodes": [
                {
                    "schema_version": "talon.public-evaluation-episode/3.0",
                    "evaluation_id": evaluation_id,
                    "checkpoint_digest": "sha256:" + "1" * 64,
                    "environment_version": environment_version,
                    "verifier_version": verifier_version,
                    "result": {
                        "episode_id": "ep_" + "0" * 24,
                        "score": 0.5,
                        "strict_success": False,
                        "verdict": "fail",
                        "safety_violation_count": 0,
                        "failed_categories": [],
                        "action_count": 1,
                        "result_digest": "sha256:" + "2" * 64,
                        "expected_calibration_error": 0.1,
                        "confidence_calibration_bins": [],
                    },
                    "timeline": [],
                }
            ],
            "aggregate": {
                "episode_count": 1,
                "strict_success_count": 0,
                "strict_success_rate": 0.0,
                "safety_violation_count": 0,
                "safety_violation_rate": 0.0,
                "average_score": 0.5,
                "abstention_rate": 0.0,
                "false_escalation_rate": 0.0,
                "missed_threat_rate": 0.0,
                "expected_calibration_error": 0.1,
                "held_out_action_accuracy": 0.5,
                "gate_intervention_rate": 0.0,
                "worst_case_score": 0.5,
            },
        },
    )
    store.write_private_artifact(
        evaluation_id,
        "verification.json",
        {"episodes": [{"manifest": {"evaluation_instance_digest": domain}}]},
    )


def test_comparison_create_retrieve_and_list_kind(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    left = "talon_eval_" + "b" * 32
    right = "talon_eval_" + "c" * 32
    _seed_completed_evaluation(store, left, domain="domain-shared", model_id="model_left")
    _seed_completed_evaluation(store, right, domain="domain-shared", model_id="model_right", algorithm="discrete_cql")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        created = client.post(
            "/api/drone/comparisons",
            json={"evaluation_ids": [left, right]},
            headers={"Origin": "http://localhost:3000", "Idempotency-Key": "compare-1"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["kind"] == "comparison"
        assert body["compatibility"] == {"domain_compatible": True, "runtime_versions_compatible": True}
        assert {item["evaluation_id"] for item in body["models"]} == {left, right}
        assert {item["evaluation_id"] for item in body["results"]} == {left, right}
        assert len(body["aligned_instances"]) == 1
        assert body["aligned_instances"][0]["instance_index"] == 1
        assert {item["evaluation_id"] for item in body["aligned_instances"][0]["outcomes"]} == {left, right}
        assert all("episode_id" in item and "strict_success" in item for item in body["aligned_instances"][0]["outcomes"])
        assert find_public_leaks(body) == []

        fetched = client.get(f"/api/drone/comparisons/{body['record_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["record_id"] == body["record_id"]
        assert fetched.json()["kind"] == "comparison"

        listed = client.get("/api/drone/comparisons")
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert any(item["record_id"] == body["record_id"] and item["kind"] == "comparison" for item in items)
        assert all(item["kind"] == "comparison" for item in items)
    store.close()


def test_comparison_domain_mismatch_returns_409(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    left = "talon_eval_" + "d" * 32
    right = "talon_eval_" + "e" * 32
    _seed_completed_evaluation(store, left, domain="domain-a")
    _seed_completed_evaluation(store, right, domain="domain-b")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/api/drone/comparisons",
            json={"evaluation_ids": [left, right]},
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "comparison_schema_or_domain_mismatch"
    store.close()
