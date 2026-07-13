"""CLI backed by the same orchestration and persistence service as the dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from evaluation_service.comparison import compare_batches
from evaluation_service.orchestration import EvaluationOrchestrator
from evaluation_service.persistence import EvaluationStore
from evaluation_service.schemas import EvaluationCreate, EvaluationLimits, ModelConfiguration
from evaluation_service.settings import Settings
from model_runners.registry import ProviderRegistry


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m model_eval", description="Frontier local model evaluations")
    root.add_argument("--database", type=Path, help="override the local SQLite database")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("providers", help="show provider status without revealing credentials")
    run = commands.add_parser("run", help="run one evaluation batch")
    run.add_argument("--provider", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--split", choices=("train", "dev", "eval"), default="eval")
    run.add_argument("--seed", type=int)
    run.add_argument("--seed-start", type=int, default=0)
    run.add_argument("--seed-count", type=int, default=1)
    run.add_argument("--attempts", type=int, default=1)
    run.add_argument("--concurrency", type=int, default=1)
    run.add_argument("--max-steps", type=int, default=64)
    run.add_argument("--max-model-calls", type=int, default=64)
    run.add_argument("--timeout", type=float, default=600)
    compare = commands.add_parser("compare", help="compare immutable stored batches")
    compare.add_argument("--batch", action="append", required=True)
    return root


async def _run_command(args: argparse.Namespace, store: EvaluationStore, registry: ProviderRegistry) -> int:
    request = EvaluationCreate(
        provider=args.provider, model=args.model, split=args.split,
        seed_start=args.seed if args.seed is not None else args.seed_start,
        seed_count=1 if args.seed is not None else args.seed_count,
        attempts=args.attempts, concurrency=args.concurrency,
        model_configuration=ModelConfiguration(),
        limits=EvaluationLimits(max_steps=args.max_steps, max_model_calls=args.max_model_calls, wall_clock_seconds=args.timeout),
    )
    orchestrator = EvaluationOrchestrator(store, registry)
    batch_id = orchestrator.create(request, start_background=False)
    await orchestrator.run_batch(batch_id)
    batch = store.get_batch(batch_id)
    _print(batch)
    return 0 if batch and batch["failed_runs"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings.from_environment()
    database = args.database or settings.database_path
    store = EvaluationStore(database)
    registry = ProviderRegistry()
    try:
        if args.command == "providers":
            _print({"providers": registry.list()})
            return 0
        if args.command == "compare":
            _print(compare_batches(store, args.batch))
            return 0
        if args.command == "run":
            return asyncio.run(_run_command(args, store, registry))
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 2
