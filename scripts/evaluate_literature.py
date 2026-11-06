"""Local-only evaluation CLI. Default execution never connects to the API."""

import argparse
import json
from pathlib import Path
from uuid import UUID

import httpx

from bioagent.knowledge.evaluation import (
    EvaluationDataset,
    LiveBudget,
    export_blind,
    paired_summary,
    read_scores,
    run_evaluation,
    summarize,
    write_report,
)


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["run", "blind", "score", "pair"], nargs="?", default="run"
    )
    parser.add_argument("--dataset")
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", default="rag", choices=["rag", "wiki", "hybrid"])
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument("--dry-run", action="store_true")
    execution.add_argument("--live", action="store_true")
    parser.add_argument("--model-profile-id", type=UUID)
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--max-input-tokens", type=int)
    parser.add_argument("--max-input-bytes", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--split", choices=["development", "heldout", "all"], default="development")
    parser.add_argument("--reports", nargs="+")
    parser.add_argument("--scores")
    parser.add_argument("--key")
    args = parser.parse_args()
    output = Path(args.output)
    try:
        if args.command == "run":
            if not args.dataset:
                parser.error("--dataset is required")
            budget = None
            if args.live:
                if any(
                    value is None
                    for value in [
                        args.model_profile_id,
                        args.max_calls,
                        args.max_output_tokens,
                    ]
                ):
                    parser.error(
                        "live requires --model-profile-id, --max-calls, --max-output-tokens"
                    )
                if args.max_input_tokens is None and args.max_input_bytes is None:
                    parser.error(
                        "live requires an explicit input budget "
                        "(--max-input-bytes or --max-input-tokens)"
                    )
                budget = LiveBudget(
                    max_calls=args.max_calls,
                    max_input_tokens=args.max_input_tokens,
                    max_input_bytes=args.max_input_bytes,
                    max_output_tokens=args.max_output_tokens,
                )
            report = run_evaluation(
                load(args.dataset),
                live=args.live,
                mode=args.mode,
                model_profile_id=args.model_profile_id,
                budget=budget,
                api_url=args.api_url,
                split=args.split,
                checkpoint=output / "results.json",
            )
            write_report(report, output / "results.json")
            print(
                json.dumps(
                    {
                        "execution": report["execution"],
                        "counts": report["counts"],
                        "quality_status": report["quality_status"],
                    }
                )
            )
        elif args.command == "blind":
            if not args.dataset or not args.reports:
                parser.error("blind requires --dataset and --reports")
            export_blind(
                EvaluationDataset.model_validate(load(args.dataset)),
                [load(p) for p in args.reports],
                output,
            )
            print("Blind packet, blank scores and separate manager key written.")
        else:
            if not args.reports or not args.scores or not args.key:
                parser.error("score/pair requires --reports --scores --key")
            reports = [load(p) for p in args.reports]
            scores = [read_scores(Path(args.scores), load(args.key), r["run_id"]) for r in reports]
            if args.command == "pair":
                if len(reports) != 2:
                    parser.error("pair requires exactly two reports")
                report = paired_summary(*reports, *scores)
            else:
                if len(reports) != 1:
                    parser.error("score requires exactly one report")
                report = summarize(reports[0], scores[0])
            write_report(report, output / "summary.json")
            print(json.dumps(report, ensure_ascii=False))
    except (ValueError, OSError, KeyError, httpx.HTTPError):
        # Validation/transport inputs may contain private paths, source text or responses.
        parser.exit(
            2,
            "Evaluation rejected: invalid protocol/configuration or unavailable local API. "
            "See documentation; no raw diagnostic is printed.\n",
        )


if __name__ == "__main__":
    main()
