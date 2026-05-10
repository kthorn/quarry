"""CLI entry point for the ranking pipeline.

Usage:
    python -m quarry.rank list-scorers
    python -m quarry.rank config get
    python -m quarry.rank config set --json '{"steps":[...]}'
    python -m quarry.rank train
    python -m quarry.rank evaluate
    python -m quarry.rank recompute
"""

from __future__ import annotations

import argparse
import json
import logging

# Import all scorers to populate the registry
import quarry.rank.scorers  # noqa: F401
from quarry.rank.config import RankingConfig, get_default_config
from quarry.rank.pipeline import RankingPipeline
from quarry.rank.registry import get_registered_names, get_step_info

log = logging.getLogger(__name__)


def _get_db():
    from quarry.store.db import get_db

    return get_db()


def cmd_list_scorers(args):
    """List all registered scorers."""
    names = get_registered_names()
    if not names:
        print("No scorers registered.")
        return

    print(f"{'Name':<25} {'Filter':<8} {'Feature':<9} {'Scorer':<8}")
    print("-" * 50)
    for name in names:
        info = get_step_info(name)
        if info:
            print(
                f"{name:<25} "
                f"{'Y' if info['is_filter'] else 'N':<8} "
                f"{'Y' if info['is_feature_extractor'] else 'N':<9} "
                f"{'Y' if info['is_scorer'] else 'N':<8}"
            )


def cmd_config_get(args):
    """Print current ranking config."""
    db = _get_db()
    config = db.get_active_pipeline_config(user_id=1)
    if config is None:
        config = get_default_config()
        print("# No active pipeline config found. Using default:")
    else:
        print(f"# Active config (id={config.id}):")
    print(config.model_dump_json(indent=2, exclude={"id"}))


def cmd_config_set(args):
    """Update ranking config from JSON string."""
    config_data = json.loads(args.json_str)
    config = RankingConfig(**config_data)
    config.validate_final_scorer()

    db = _get_db()
    new_id = db.insert_pipeline_config(
        user_id=1,
        config=config,
        description=args.description,
    )
    print(f"Pipeline config saved (id={new_id})")


def cmd_train(args):
    """Train classifier on current labels."""
    from quarry.rank.train import train_classifier

    db = _get_db()
    result = train_classifier(db=db, user_id=1, min_labels=args.min_labels)

    if "error" in result:
        print(result["error"])
        return

    print(f"Training complete. Model saved: {result['model_path']}")
    print(f"AUC: {result['cv_auc_mean']:.4f}, Samples: {result['training_samples']}")


def cmd_evaluate(args):
    """Cross-validation evaluation of current classifier."""

    from quarry.pipeline.embedder import deserialize_embedding, get_embedding_dim
    from quarry.rank.scorers.classifier import ClassifierScorer

    db = _get_db()
    rows = db.get_labels_with_postings(user_id=1)
    if not rows:
        print("No labeled postings found.")
        return

    dim = get_embedding_dim()
    signal_labels = []
    valid_postings = []

    for row in rows:
        signal, emb_bytes, posting_id = row
        if emb_bytes is None:
            continue
        try:
            emb = deserialize_embedding(emb_bytes, dim)
        except (ValueError, TypeError):
            continue
        from types import SimpleNamespace

        posting = SimpleNamespace(embedding=emb, id=posting_id)
        valid_postings.append(posting)
        signal_labels.append(signal)

    if len(signal_labels) < 5:
        print(f"Need at least 5 labeled postings, got {len(signal_labels)}.")
        return

    scorer = ClassifierScorer(min_training_labels=5)
    result = scorer.fit(signal_labels, valid_postings)
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("Evaluation failed.")


def cmd_recompute(args):
    """Re-run ranking pipeline on all postings."""

    db = _get_db()
    pipeline = RankingPipeline.load_for_user(db, user_id=1)
    if pipeline.config.id is None:
        print(
            "No active pipeline config. Insert one first with: quarry rank config set"
        )
        return

    postings = db.get_postings_with_scores(status="new", limit=10000)
    print(
        f"Scoring {len(postings)} postings with pipeline config #{pipeline.config.id}..."
    )
    scored = 0
    for posting_row in postings:
        posting_id = posting_row["id"]
        result = pipeline.run(posting_id)
        if not result.context.dropped:
            db.upsert_ranking_score(
                user_id=1,
                posting_id=posting_id,
                pipeline_config_id=pipeline.config.id,
                composite_score=result.context.final_score,
                component_scores=result.context.scores,
            )
            scored += 1

    print(f"Scored {scored} postings (composite_score > 0: {scored}).")


def main():
    parser = argparse.ArgumentParser(description="Quarry Ranking Pipeline CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list-scorers", help="List registered scorers")

    config_parser = sub.add_parser("config", help="Manage ranking config")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_sub.add_parser("get", help="Print current ranking config")
    set_parser = config_sub.add_parser("set", help="Update ranking config")
    set_parser.add_argument(
        "--json", dest="json_str", required=True, help="JSON config string"
    )
    set_parser.add_argument("--description", help="Human-readable description")

    train_parser = sub.add_parser("train", help="Train classifier on labels")
    train_parser.add_argument(
        "--min-labels", type=int, default=20, help="Minimum labels for training"
    )

    sub.add_parser("evaluate", help="Cross-validation evaluation")

    sub.add_parser("recompute", help="Re-run pipeline on all postings")

    args = parser.parse_args()
    if args.command == "list-scorers":
        cmd_list_scorers(args)
    elif args.command == "config":
        if args.config_action == "get":
            cmd_config_get(args)
        elif args.config_action == "set":
            cmd_config_set(args)
        else:
            parser.print_help()
    elif args.command == "train":
        cmd_train(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    elif args.command == "recompute":
        cmd_recompute(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
