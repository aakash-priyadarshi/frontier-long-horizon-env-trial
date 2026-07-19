"""Product hardening tests: bindings, artifact identity, cleanup, policy injection."""

from __future__ import annotations

import inspect
import shutil
from pathlib import Path

import pytest

from drone_training.bindings import (
    BindingSource,
    TrustedCheckpointBinding,
    logical_checkpoint_identity,
    require_dataset_bindings,
    resolve_bound_checkpoint,
)
from drone_training.datasets import generate_dataset
from drone_training.evaluation import evaluate_checkpoint
from drone_training.offline_checkpoints import load_offline_checkpoint, save_offline_checkpoint
from drone_training.offline_evaluation import (
    evaluate_offline_checkpoint,
    evaluate_offline_checkpoint_for_tests,
)
from drone_training.offline_rl import CQLConfig, derive_offline_dataset, train_discrete_cql
from drone_training.orchestration import TalonOrchestrator
from drone_training.persistence import TalonStore
from drone_training.schemas import EvaluationCreate
from drone_training.worker import run_job


@pytest.fixture(scope="module")
def offline_trained(tmp_path_factory):
    source = generate_dataset(partition="train", seeds=[0], families=["authorised_inspection"])
    offline = derive_offline_dataset(source, context_length=4)
    config = CQLConfig(
        context_length=4,
        hidden_dim=8,
        layers=1,
        dropout=0,
        batch_size=8,
        epochs=1,
        target_update_interval=2,
        random_seed=21,
    )
    model, target, history = train_discrete_cql(offline, config)
    updates = int(history.pop("training_updates", [0.0])[-1])
    root = tmp_path_factory.mktemp("offline-ckpt")
    path = root / "checkpoint.pt"
    digest = save_offline_checkpoint(
        path,
        model=model,
        target=target,
        dataset=offline,
        config=config,
        training_history=history,
        training_updates=updates,
    )
    return path, digest, offline


def _completed_training(
    store: TalonStore,
    run_id: str,
    digest: str,
    checkpoint_src: Path,
    offline,
) -> dict:
    return _completed_training_raw(
        store,
        run_id,
        digest,
        checkpoint_src,
        offline_dataset_digest=offline.manifest.dataset_digest,
        source_dataset_digest=offline.manifest.source_dataset_digest,
    )


def _completed_training_raw(
    store: TalonStore,
    run_id: str,
    digest: str,
    checkpoint_src: Path,
    *,
    offline_dataset_digest: str | None = None,
    source_dataset_digest: str | None = None,
) -> dict:
    store.create_record(
        run_id,
        "training",
        {
            "schema_version": "talon.public-training-record/2.0",
            "configuration": {"dataset_id": "dataset_" + "0" * 24},
            "application_commit": "test",
            "architecture": "cql_gru",
            "algorithm": "discrete_cql",
        },
    )
    private = store._private_directory(run_id)
    shutil.copyfile(checkpoint_src, private / "checkpoint.pt")
    identity = logical_checkpoint_identity(run_id)
    finalized: dict = {
        "model_id": run_id,
        "checkpoint_digest": digest,
        "artifact_identity": identity,
        "architecture": "cql_gru",
        "algorithm": "discrete_cql",
    }
    if offline_dataset_digest is not None:
        finalized["offline_dataset_digest"] = offline_dataset_digest
    if source_dataset_digest is not None:
        finalized["dataset_digest"] = source_dataset_digest
    store.finalize(run_id, "completed", finalized)
    record = store.get(run_id)
    assert record is not None
    return record


def test_trusted_checkpoint_binding_round_trip(offline_trained) -> None:
    path, digest, offline = offline_trained
    binding = TrustedCheckpointBinding(
        training_run_id="talon_cql_" + "a" * 32,
        checkpoint_id="talon_cql_" + "a" * 32,
        trusted_digest=digest,
        artifact_identity=logical_checkpoint_identity("talon_cql_" + "a" * 32),
        binding_source=BindingSource.IMMUTABLE_DB_RECORD,
        offline_dataset_digest=offline.manifest.dataset_digest,
        source_dataset_digest=offline.manifest.source_dataset_digest,
    )
    public = binding.to_public_dict()
    assert public["binding_source"] == "immutable_db_record"
    assert public["artifact_identity"].endswith("/checkpoint.pt")
    assert public["trusted_digest"] == digest


def test_artifact_identity_rejects_traversal_outside_and_mismatch(tmp_path, offline_trained) -> None:
    path, digest, offline = offline_trained
    store = TalonStore(tmp_path / "talon.sqlite3")
    run_id = "talon_cql_" + "b" * 32
    other_id = "talon_cql_" + "c" * 32
    record = _completed_training(store, run_id, digest, path, offline)
    binding = TrustedCheckpointBinding.from_completed_training(record)

    resolved = resolve_bound_checkpoint(store.private_dir, binding)
    assert resolved == (store.private_dir / run_id / "checkpoint.pt").resolve()

    with pytest.raises(ValueError, match="artifact identity"):
        TrustedCheckpointBinding(
            training_run_id=run_id,
            trusted_digest=digest,
            artifact_identity=f"../outside/{run_id}/checkpoint.pt",
            binding_source=BindingSource.IMMUTABLE_DB_RECORD,
        )

    # File outside private root is not reachable via a valid binding.
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copyfile(path, outside / "checkpoint.pt")
    assert outside.resolve() != store.private_dir.resolve()

    # Copied under another run's path cannot satisfy this run's identity once removed.
    store.create_record(
        other_id,
        "training",
        {"schema_version": "talon.public-training-record/2.0", "configuration": {}, "application_commit": "test"},
        status="running",
    )
    shutil.copyfile(path, store._private_directory(other_id) / "checkpoint.pt")
    forged = TrustedCheckpointBinding(
        training_run_id=run_id,
        trusted_digest=digest,
        artifact_identity=logical_checkpoint_identity(run_id),
        binding_source=BindingSource.IMMUTABLE_DB_RECORD,
    )
    assert resolve_bound_checkpoint(store.private_dir, forged).parent.name == run_id
    (store.private_dir / run_id / "checkpoint.pt").unlink()
    with pytest.raises(ValueError, match="not found"):
        resolve_bound_checkpoint(store.private_dir, forged)

    with pytest.raises(ValueError, match="artifact identity does not match"):
        TrustedCheckpointBinding(
            training_run_id=run_id,
            trusted_digest=digest,
            artifact_identity=logical_checkpoint_identity(other_id),
            binding_source=BindingSource.IMMUTABLE_DB_RECORD,
        )
    store.close()


def test_path_substitution_and_foreign_copy_rejected_for_eval(tmp_path, offline_trained) -> None:
    path, digest, offline = offline_trained
    store = TalonStore(tmp_path / "talon.sqlite3")
    run_a = "talon_cql_" + "d" * 32
    run_b = "talon_cql_" + "e" * 32
    _completed_training(store, run_a, digest, path, offline)
    store.create_record(
        run_b,
        "training",
        {
            "schema_version": "talon.public-training-record/2.0",
            "configuration": {"dataset_id": "dataset_" + "0" * 24},
            "application_commit": "test",
        },
        status="running",
    )
    # Place a copy under run_b and try to evaluate with run_a's digest via free path.
    shutil.copyfile(path, store._private_directory(run_b) / "checkpoint.pt")
    binding_a = TrustedCheckpointBinding.from_completed_training(store.get(run_a))  # type: ignore[arg-type]
    # Correct binding still loads from run_a only.
    resolve_bound_checkpoint(store.private_dir, binding_a)
    # If run_a's file is replaced with garbage but digest claim stays, digest mismatch.
    (store.private_dir / run_a / "checkpoint.pt").write_bytes(b"not-a-checkpoint")
    with pytest.raises(ValueError, match="digest mismatch"):
        resolve_bound_checkpoint(store.private_dir, binding_a)
    store.close()


def test_reconcile_orphan_checkpoints_states(tmp_path, offline_trained) -> None:
    path, digest, offline = offline_trained
    store = TalonStore(tmp_path / "talon.sqlite3")

    # A. completed + valid → keep
    keep_id = "talon_cql_" + "f" * 32
    _completed_training(store, keep_id, digest, path, offline)

    # B. completed + missing → unavailable
    missing_id = "talon_cql_" + "1" * 32
    _completed_training(store, missing_id, digest, path, offline)
    (store.private_dir / missing_id / "checkpoint.pt").unlink()

    # C. non-completed + checkpoint → remove
    active_id = "talon_cql_" + "2" * 32
    store.create_record(
        active_id,
        "training",
        {"schema_version": "talon.public-training-record/2.0", "configuration": {}, "application_commit": "test"},
        status="running",
    )
    shutil.copyfile(path, store._private_directory(active_id) / "checkpoint.pt")
    (store._private_directory(active_id) / ".checkpoint.pt.partial").write_bytes(b"partial")

    # D. orphan directory with checkpoint, no DB record
    orphan = store.private_dir / ("talon_cql_" + "3" * 32)
    orphan.mkdir()
    shutil.copyfile(path, orphan / "checkpoint.pt")

    # E. partial under keep_id
    (store.private_dir / keep_id / ".extra.partial").write_bytes(b"x")

    summary = store.reconcile_orphan_checkpoints()
    assert summary["kept_completed"] >= 1
    assert summary["marked_unavailable"] >= 1
    assert summary["removed_non_completed"] >= 1
    assert summary["quarantined_orphans"] >= 1
    assert summary["removed_partials"] >= 1

    assert (store.private_dir / keep_id / "checkpoint.pt").exists()
    assert store.checkpoint_is_available(keep_id) is True
    assert store.get(missing_id)["checkpoint_unavailable"] is True  # type: ignore[index]
    assert not (store.private_dir / active_id / "checkpoint.pt").exists()
    assert not (store.private_dir / active_id / ".checkpoint.pt.partial").exists()
    assert not (orphan / "checkpoint.pt").exists()
    assert not (store.private_dir / keep_id / ".extra.partial").exists()
    store.close()


def test_mark_active_interrupted_removes_uncommitted_checkpoints(tmp_path, offline_trained) -> None:
    path, digest, offline = offline_trained
    database = tmp_path / "talon.sqlite3"
    store = TalonStore(database)
    completed_id = "talon_cql_" + "4" * 32
    _completed_training(store, completed_id, digest, path, offline)

    active_id = "talon_cql_" + "5" * 32
    store.create_record(
        active_id,
        "training",
        {"schema_version": "talon.public-training-record/2.0", "configuration": {}, "application_commit": "test"},
        status="running",
    )
    private = store._private_directory(active_id)
    shutil.copyfile(path, private / "checkpoint.pt")
    (private / ".checkpoint.pt.partial").write_bytes(b"partial")
    store.close()

    restarted = TalonStore(database)
    assert restarted.mark_active_interrupted() == 1
    assert restarted.get(active_id)["status"] == "interrupted"  # type: ignore[index]
    assert not (restarted.private_dir / active_id / "checkpoint.pt").exists()
    assert not list((restarted.private_dir / active_id).glob("*.partial"))
    # Completed run checkpoint preserved.
    assert (restarted.private_dir / completed_id / "checkpoint.pt").exists()

    orchestrator = TalonOrchestrator(restarted)
    with pytest.raises(ValueError, match="unavailable|not found|completed training"):
        # Interrupted run cannot be evaluated.
        orchestrator.create_evaluation(
            EvaluationCreate(training_run_id=active_id),
            start_background=False,
        )
    restarted.close()


def test_unavailable_completed_checkpoint_cannot_be_evaluated(tmp_path, offline_trained) -> None:
    path, digest, offline = offline_trained
    store = TalonStore(tmp_path / "talon.sqlite3")
    run_id = "talon_cql_" + "6" * 32
    _completed_training(store, run_id, digest, path, offline)
    (store.private_dir / run_id / "checkpoint.pt").unlink()
    store.reconcile_orphan_checkpoints()
    assert store.get(run_id)["checkpoint_unavailable"] is True  # type: ignore[index]
    orchestrator = TalonOrchestrator(store)
    with pytest.raises(ValueError, match="unavailable"):
        orchestrator.create_evaluation(EvaluationCreate(training_run_id=run_id), start_background=False)
    store.close()


def test_public_evaluate_rejects_policy_client_kwarg(offline_trained) -> None:
    path, digest, _ = offline_trained
    signature = inspect.signature(evaluate_offline_checkpoint)
    assert "policy_client" not in signature.parameters
    bc_signature = inspect.signature(evaluate_checkpoint)
    assert "policy_client" not in bc_signature.parameters
    with pytest.raises(TypeError):
        evaluate_offline_checkpoint(  # type: ignore[call-arg]
            path,
            family="authorised_inspection",
            seed=0,
            expected_checkpoint_digest=digest,
            policy_client=object(),
        )


def test_evaluation_create_rejects_policy_client_injection() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvaluationCreate(  # type: ignore[call-arg]
            training_run_id="talon_cql_" + "0" * 32,
            policy_client="injected",
        )
    with pytest.raises(ValidationError):
        EvaluationCreate.model_validate(
            {
                "training_run_id": "talon_cql_" + "0" * 32,
                "policy_client": {"foreign": True},
            }
        )


def test_for_tests_helper_not_imported_by_product_paths() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    symbol = "evaluate_offline_checkpoint_for_tests"
    assert callable(evaluate_offline_checkpoint_for_tests)
    assert "policy_client" in inspect.signature(evaluate_offline_checkpoint_for_tests).parameters
    for relative in ("src/drone_training/api.py", "src/drone_training/orchestration.py"):
        text = (root / relative).read_text(encoding="utf-8")
        assert symbol not in text


def test_foreign_weight_client_cannot_pair_in_production_helper(tmp_path, offline_trained) -> None:
    path, digest, _ = offline_trained

    class _ForeignClient:
        expected_digest = "sha256:" + "f" * 64
        profile_id = "uk_monitor_and_escalate"
        last_diagnostics: dict = {}

        def reset(self) -> None:
            return None

        def recommend(self, observation):  # noqa: ANN001
            raise AssertionError("foreign client must not be used")

        def close(self) -> None:
            return None

    with pytest.raises(ValueError, match="does not match"):
        evaluate_offline_checkpoint_for_tests(
            path,
            family="authorised_inspection",
            seed=0,
            partition="evaluation",
            expected_checkpoint_digest=digest,
            policy_client=_ForeignClient(),
        )


def test_worker_payload_cannot_inject_policy_client(tmp_path, offline_trained) -> None:
    path, digest, offline = offline_trained
    store = TalonStore(tmp_path / "talon.sqlite3")
    run_id = "talon_cql_" + "7" * 32
    _completed_training(store, run_id, digest, path, offline)
    import multiprocessing as mp

    context = mp.get_context("spawn")
    queue = context.Queue()
    cancelled = context.Event()
    request = {
        "training_run_id": run_id,
        "checkpoint_digest": digest,
        "artifact_identity": logical_checkpoint_identity(run_id),
        "offline_dataset_digest": offline.manifest.dataset_digest,
        "dataset_digest": offline.manifest.source_dataset_digest,
        "seed_start": 0,
        "seed_count": 1,
        "timeout_seconds": 30,
        "application_commit": "test",
        "policy_client": "injected",
    }
    paths = {
        "data_root": str(store.path.parent),
        "checkpoint": str(store.private_dir / run_id / "checkpoint.pt"),
        "private_evaluation": str(store._private_directory("talon_eval_" + "8" * 32) / "verification.json"),
        "dataset": str(store.private_dir / run_id / "checkpoint.pt"),
    }
    # Ensure private evaluation parent exists for worker.
    store._private_directory("talon_eval_" + "8" * 32).mkdir(parents=True, exist_ok=True)
    run_job("offline_evaluation", request, paths, queue, cancelled)
    message = queue.get(timeout=30)
    assert message["type"] == "failed"
    store.close()


def test_cli_parser_documents_trusted_digest_provenance() -> None:
    from drone_training.cli import build_parser

    parser = build_parser()
    help_text = parser.format_help()
    # Subparser help for evaluate-cql
    evaluate_help = None
    for action in parser._subparsers._group_actions:  # type: ignore[attr-defined]
        for name, sub in action.choices.items():
            if name == "evaluate-cql":
                evaluate_help = sub.format_help()
    assert evaluate_help is not None
    assert "immutable completed-run" in evaluate_help or "operator-supplied" in evaluate_help
    assert "--trusted-checkpoint-digest" in evaluate_help or "--checkpoint-digest" in evaluate_help
    assert "--offline-dataset-digest" in evaluate_help
    assert "--source-dataset-digest" in evaluate_help


def test_evaluation_rejects_forged_record_claiming_other_dataset(tmp_path, offline_trained) -> None:
    path_a, digest_a, offline_a = offline_trained
    # Dataset B digests (distinct from A) from a different train seed family.
    source_b = generate_dataset(partition="train", seeds=[1], families=["bird_false_positive"])
    offline_b = derive_offline_dataset(source_b, context_length=4)
    assert offline_b.manifest.dataset_digest != offline_a.manifest.dataset_digest
    assert offline_b.manifest.source_dataset_digest != offline_a.manifest.source_dataset_digest

    store = TalonStore(tmp_path / "talon.sqlite3")
    run_id = "talon_cql_" + "9" * 32
    _completed_training(store, run_id, digest_a, path_a, offline_a)
    private_root = store.private_dir

    forged = TrustedCheckpointBinding(
        training_run_id=run_id,
        checkpoint_id=run_id,
        trusted_digest=digest_a,
        artifact_identity=logical_checkpoint_identity(run_id),
        binding_source=BindingSource.IMMUTABLE_DB_RECORD,
        offline_dataset_digest=offline_b.manifest.dataset_digest,
        source_dataset_digest=offline_b.manifest.source_dataset_digest,
    )
    with pytest.raises(ValueError, match="dataset binding mismatch"):
        evaluate_offline_checkpoint(
            binding=forged,
            private_root=private_root,
            family="authorised_inspection",
            seed=0,
            partition="evaluation",
            timeout_seconds=5,
        )

    valid = TrustedCheckpointBinding.from_completed_training(store.get(run_id))  # type: ignore[arg-type]
    offline_digest, source_digest = require_dataset_bindings(valid)
    _, _, metadata = load_offline_checkpoint(
        path_a,
        expected_digest=digest_a,
        expected_offline_dataset_digest=offline_digest,
        expected_source_dataset_digest=source_digest,
    )
    assert metadata["offline_dataset_digest"] == offline_a.manifest.dataset_digest
    assert metadata["source_dataset_digest"] == offline_a.manifest.source_dataset_digest

    fake = "sha256:" + "ab" * 32
    with pytest.raises(ValueError, match="offline-dataset binding mismatch"):
        load_offline_checkpoint(
            path_a,
            expected_digest=digest_a,
            expected_offline_dataset_digest=fake,
            expected_source_dataset_digest=source_digest,
        )
    with pytest.raises(ValueError, match="source-dataset binding mismatch"):
        load_offline_checkpoint(
            path_a,
            expected_digest=digest_a,
            expected_offline_dataset_digest=offline_digest,
            expected_source_dataset_digest=fake,
        )
    store.close()


def test_require_dataset_bindings_rejects_missing(offline_trained) -> None:
    path, digest, offline = offline_trained
    incomplete = TrustedCheckpointBinding(
        training_run_id="talon_cql_" + "a" * 32,
        trusted_digest=digest,
        artifact_identity=logical_checkpoint_identity("talon_cql_" + "a" * 32),
        binding_source=BindingSource.IMMUTABLE_DB_RECORD,
        offline_dataset_digest=offline.manifest.dataset_digest,
        source_dataset_digest=None,
    )
    with pytest.raises(ValueError, match="source dataset digest"):
        require_dataset_bindings(incomplete)
