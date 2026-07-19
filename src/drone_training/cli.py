"""Privileged local CLI for Talon dataset, training, and frozen evaluation."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import queue as queue_module
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .checkpoints import inspect_checkpoint
from .datasets import load_dataset
from .manifests import content_digest, write_immutable_json
from .worker import run_job


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m drone_training")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate-dataset")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--partition", choices=("train", "validation", "evaluation"), default="train")
    generate.add_argument("--seed-start", type=int, default=0)
    generate.add_argument("--seed-count", type=int, default=1)
    generate.add_argument("--family", action="append", dest="families")
    generate.add_argument("--timeout-seconds", type=int, default=60)

    for name in ("train-gru", "train-decision-transformer"):
        train = commands.add_parser(name)
        train.add_argument("--dataset", type=Path, required=True)
        train.add_argument("--output-dir", type=Path, required=True)
        train.add_argument("--epochs", type=int, default=20)
        train.add_argument("--learning-rate", type=float, default=1e-3)
        train.add_argument("--batch-size", type=int, default=32)
        train.add_argument("--context-length", type=int, default=20)
        train.add_argument("--seed", type=int, default=0)
        train.add_argument("--timeout-seconds", type=int, default=300)

    cql = commands.add_parser("train-cql")
    cql.add_argument("--dataset", type=Path, required=True)
    cql.add_argument("--output-dir", type=Path, required=True)
    cql.add_argument("--epochs", type=int, default=50)
    cql.add_argument("--learning-rate", type=float, default=3e-4)
    cql.add_argument("--batch-size", type=int, default=128)
    cql.add_argument("--context-length", type=int, default=20)
    cql.add_argument("--hidden-dim", type=int, default=256)
    cql.add_argument("--layers", type=int, default=2)
    cql.add_argument("--dropout", type=float, default=.1)
    cql.add_argument("--gamma", type=float, default=.99)
    cql.add_argument("--cql-alpha", type=float, default=1.0)
    cql.add_argument("--safety-threshold", type=float, default=.05)
    cql.add_argument("--target-update-interval", type=int, default=500)
    cql.add_argument("--gradient-clip", type=float, default=1.0)
    cql.add_argument("--seed", type=int, default=0)
    cql.add_argument("--timeout-seconds", type=int, default=900)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--checkpoint", type=Path, required=True)
    evaluate.add_argument(
        "--trusted-checkpoint-digest",
        "--checkpoint-digest",
        dest="checkpoint_digest",
        required=True,
        help=(
            "Trusted SHA-256 digest of the checkpoint file bytes. Must originate from an "
            "immutable completed-run record (API/DB). When supplied via CLI this is "
            "operator-supplied provenance, not a DB binding."
        ),
    )
    evaluate.add_argument("--family", required=True)
    evaluate.add_argument("--seed", type=int, default=0)
    evaluate.add_argument("--partition", choices=("validation", "evaluation"), default="evaluation")
    evaluate.add_argument("--timeout-seconds", type=int, default=30)
    evaluate.add_argument("--output", type=Path)

    evaluate_cql = commands.add_parser("evaluate-cql")
    evaluate_cql.add_argument("--checkpoint", type=Path, required=True)
    evaluate_cql.add_argument(
        "--trusted-checkpoint-digest",
        "--checkpoint-digest",
        dest="checkpoint_digest",
        required=True,
        help=(
            "Trusted SHA-256 digest of the checkpoint file bytes. Must originate from an "
            "immutable completed-run record (API/DB). When supplied via CLI this is "
            "operator-supplied provenance, not a DB binding."
        ),
    )
    evaluate_cql.add_argument(
        "--offline-dataset-digest",
        dest="offline_dataset_digest",
        default=None,
        help=(
            "Optional verified offline-dataset digest. When both this and "
            "--source-dataset-digest are supplied, they are passed to load. "
            "Product DB evaluation paths always bind both digests from the training record."
        ),
    )
    evaluate_cql.add_argument(
        "--source-dataset-digest",
        dest="source_dataset_digest",
        default=None,
        help=(
            "Optional verified source-dataset digest. Must be paired with "
            "--offline-dataset-digest. Product DB paths always bind both digests."
        ),
    )
    evaluate_cql.add_argument("--family", required=True)
    evaluate_cql.add_argument("--seed", type=int, default=0)
    evaluate_cql.add_argument("--partition", choices=("validation", "evaluation"), default="evaluation")
    evaluate_cql.add_argument("--timeout-seconds", type=int, default=30)
    evaluate_cql.add_argument("--output", type=Path)

    inspect = commands.add_parser("inspect-checkpoint")
    inspect.add_argument("--checkpoint", type=Path, required=True)
    inspect.add_argument(
        "--trusted-checkpoint-digest",
        "--checkpoint-digest",
        dest="checkpoint_digest",
        required=True,
        help=(
            "Trusted SHA-256 digest from an immutable completed-run record. CLI supply is "
            "operator-supplied provenance, not a DB binding."
        ),
    )
    inspect_dataset = commands.add_parser("inspect-dataset")
    inspect_dataset.add_argument("--dataset", type=Path, required=True)
    inspect_offline = commands.add_parser("inspect-offline-checkpoint")
    inspect_offline.add_argument("--checkpoint", type=Path, required=True)
    inspect_offline.add_argument(
        "--trusted-checkpoint-digest",
        "--checkpoint-digest",
        dest="checkpoint_digest",
        required=True,
        help=(
            "Trusted SHA-256 digest from an immutable completed-run record. CLI supply is "
            "operator-supplied provenance, not a DB binding."
        ),
    )
    inspect_offline.add_argument(
        "--offline-dataset-digest",
        dest="offline_dataset_digest",
        default=None,
        help=(
            "Optional verified offline-dataset digest. When both this and "
            "--source-dataset-digest are supplied, they are passed to load. "
            "Product DB evaluation paths always bind both digests from the training record."
        ),
    )
    inspect_offline.add_argument(
        "--source-dataset-digest",
        dest="source_dataset_digest",
        default=None,
        help=(
            "Optional verified source-dataset digest. Must be paired with "
            "--offline-dataset-digest. Product DB paths always bind both digests."
        ),
    )
    inspect_offline_dataset = commands.add_parser("inspect-offline-dataset")
    inspect_offline_dataset.add_argument("--dataset", type=Path, required=True)
    return parser


def _run_worker(operation: str, request: dict[str, Any], paths: dict[str, str], timeout: int) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue = context.Queue()
    cancelled = context.Event()
    process = context.Process(target=run_job, args=(operation, request, paths, queue, cancelled))
    process.start()
    deadline = time.monotonic() + timeout
    completed: dict[str, Any] | None = None
    try:
        while time.monotonic() < deadline:
            try:
                message = queue.get(timeout=0.1)
            except queue_module.Empty:
                if process.exitcode is not None:
                    break
                continue
            if message.get("type") == "completed":
                completed = message["data"]
                break
            if message.get("type") in {"failed", "cancelled", "timed_out"}:
                raise RuntimeError("Talon CLI worker did not complete")
        if completed is None:
            cancelled.set()
            if process.is_alive():
                process.terminate()
                process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
            raise TimeoutError("Talon CLI command exceeded its timeout")
        process.join(5)
        return completed
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        queue.close()
        queue.join_thread()


def _evaluation_entry(arguments: dict[str, Any], queue: Any) -> None:
    try:
        from .evaluation import evaluate_checkpoint

        value = evaluate_checkpoint(**arguments)
        queue.put({"type": "completed", "data": value["public"]})
    except Exception:
        queue.put({"type": "failed"})


def _offline_evaluation_entry(arguments: dict[str, Any], queue: Any) -> None:
    try:
        from .offline_evaluation import evaluate_offline_checkpoint

        value = evaluate_offline_checkpoint(**arguments)
        queue.put({"type": "completed", "data": value["public"]})
    except Exception:
        queue.put({"type": "failed"})


def _run_evaluation(arguments: dict[str, Any], timeout: int, *, offline: bool = False) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_offline_evaluation_entry if offline else _evaluation_entry, args=(arguments, queue))
    process.start()
    try:
        try:
            message = queue.get(timeout=timeout)
        except queue_module.Empty as exc:
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
            raise TimeoutError("Talon CLI evaluation exceeded its timeout") from exc
        if message.get("type") != "completed":
            raise RuntimeError("Talon CLI evaluation failed")
        process.join(5)
        return message["data"]
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        queue.close()
        queue.join_thread()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {
        "evaluate",
        "evaluate-cql",
        "inspect-checkpoint",
        "inspect-offline-checkpoint",
    }:
        print(
            "note: CLI --trusted-checkpoint-digest/--checkpoint-digest is operator-supplied "
            "provenance, not an immutable DB binding; it must still originate from a completed-run record.",
            file=sys.stderr,
        )
    if args.command == "generate-dataset":
        if args.seed_count < 1:
            raise SystemExit("--seed-count must be positive")
        if args.timeout_seconds < 1:
            raise SystemExit("--timeout-seconds must be positive")
        payload = _run_worker(
            "dataset",
            {
                "partition": args.partition,
                "seed_start": args.seed_start,
                "seed_count": args.seed_count,
                "families": args.families,
            },
            {
                "data_root": str(args.output.parent),
                "dataset": str(args.output),
            },
            args.timeout_seconds,
        )
    elif args.command in {"train-gru", "train-decision-transformer"}:
        architecture = "gru" if args.command == "train-gru" else "decision_transformer"
        verified_dataset = load_dataset(args.dataset)
        dataset_digest = verified_dataset.manifest.dataset_digest
        config = {
            "architecture": architecture,
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "batch_size": args.batch_size,
            "context_length": args.context_length,
            "random_seed": args.seed,
        }
        run_id = "talon_train_" + content_digest({"dataset": dataset_digest, "config": config}).split(":", 1)[1][:32]
        output = args.output_dir / run_id
        output.mkdir(parents=True, exist_ok=False)
        payload = _run_worker(
            "training",
            {**config, "run_id": run_id, "application_commit": _git_sha()},
            {
                "data_root": str(args.output_dir),
                "dataset": str(args.dataset),
                "checkpoint": str(output / "checkpoint.pt"),
                "manifest": str(output / "manifest.json"),
            },
            args.timeout_seconds,
        )
        payload["training_run_id"] = run_id
    elif args.command == "train-cql":
        verified_dataset = load_dataset(args.dataset)
        config = {
            "context_length": args.context_length, "hidden_dim": args.hidden_dim, "layers": args.layers,
            "dropout": args.dropout, "gamma": args.gamma, "cql_alpha": args.cql_alpha,
            "safety_threshold": args.safety_threshold, "learning_rate": args.learning_rate,
            "batch_size": args.batch_size, "epochs": args.epochs,
            "target_update_interval": args.target_update_interval, "gradient_clip": args.gradient_clip,
            "random_seed": args.seed,
        }
        run_id = "talon_cql_" + content_digest({"dataset": verified_dataset.manifest.dataset_digest, "config": config}).split(":", 1)[1][:32]
        output = args.output_dir / run_id
        output.mkdir(parents=True, exist_ok=False)
        payload = _run_worker("offline_training", {**config, "run_id": run_id, "application_commit": _git_sha()}, {
            "data_root": str(args.output_dir), "dataset": str(args.dataset),
            "offline_dataset": str(output / "offline_dataset.json"),
            "checkpoint": str(output / "checkpoint.pt"), "manifest": str(output / "manifest.json"),
        }, args.timeout_seconds)
        payload["training_run_id"] = run_id
    elif args.command in {"evaluate", "evaluate-cql"}:
        sha = _git_sha()
        evaluation_arguments: dict[str, Any] = {
            "checkpoint": args.checkpoint,
            "family": args.family,
            "seed": args.seed,
            "partition": args.partition,
            "expected_checkpoint_digest": args.checkpoint_digest,
            "environment_commit": sha,
            "verifier_commit": sha,
            "timeout_seconds": args.timeout_seconds,
        }
        if args.command == "evaluate-cql":
            offline_digest = getattr(args, "offline_dataset_digest", None)
            source_digest = getattr(args, "source_dataset_digest", None)
            if (offline_digest is None) ^ (source_digest is None):
                raise SystemExit(
                    "evaluate-cql requires both --offline-dataset-digest and "
                    "--source-dataset-digest when either is supplied "
                    "(product DB paths always bind both digests)"
                )
            if offline_digest is not None and source_digest is not None:
                evaluation_arguments["expected_offline_dataset_digest"] = offline_digest
                evaluation_arguments["expected_source_dataset_digest"] = source_digest
        payload = _run_evaluation(
            evaluation_arguments,
            args.timeout_seconds + 5,
            offline=args.command == "evaluate-cql",
        )
        if args.output:
            write_immutable_json(args.output, payload)
    elif args.command == "inspect-checkpoint":
        payload = inspect_checkpoint(args.checkpoint, expected_digest=args.checkpoint_digest)
    elif args.command == "inspect-offline-checkpoint":
        from .offline_checkpoints import inspect_offline_checkpoint

        offline_digest = getattr(args, "offline_dataset_digest", None)
        source_digest = getattr(args, "source_dataset_digest", None)
        if (offline_digest is None) ^ (source_digest is None):
            raise SystemExit(
                "inspect-offline-checkpoint requires both --offline-dataset-digest and "
                "--source-dataset-digest when either is supplied "
                "(product DB paths always bind both digests)"
            )
        inspect_kwargs: dict[str, Any] = {"expected_digest": args.checkpoint_digest}
        if offline_digest is not None and source_digest is not None:
            inspect_kwargs["expected_offline_dataset_digest"] = offline_digest
            inspect_kwargs["expected_source_dataset_digest"] = source_digest
        payload = inspect_offline_checkpoint(args.checkpoint, **inspect_kwargs)
    elif args.command == "inspect-offline-dataset":
        from .offline_rl import load_offline_dataset

        dataset = load_offline_dataset(args.dataset)
        payload = {
            "schema_version": dataset.schema_version,
            "dataset_digest": dataset.manifest.dataset_digest,
            "source_dataset_digest": dataset.manifest.source_dataset_digest,
            "partition": dataset.manifest.source_partition,
            "transition_count": dataset.manifest.transition_count,
            "feature_schema": dataset.manifest.feature_schema_version,
            "action_schema_version": dataset.manifest.action_schema_version,
            "integrity_verified": True,
        }
    else:
        dataset = load_dataset(args.dataset)
        payload = {
            "schema_version": dataset.schema_version,
            "dataset_id": dataset.manifest.dataset_id,
            "dataset_digest": dataset.manifest.dataset_digest,
            "partition": dataset.manifest.generator_partition,
            "trajectory_count": dataset.manifest.trajectory_count,
            "integrity_verified": True,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0
