"""Project-authored optional dataset plugin, not shipped by upstream LegalKit.

Copy into LegalKit/legalkit/datasets/CAIL2026ContractReview only when using
the full upstream runner and its dependencies. See docs/LEGALKIT.md.
"""
from cail_review.legalkit_adapter import (
    Evaluator,
    Generator,
    load_json_predictions,
    load_tasks,
)

__all__ = ["Evaluator", "Generator", "load_json_predictions", "load_tasks"]
