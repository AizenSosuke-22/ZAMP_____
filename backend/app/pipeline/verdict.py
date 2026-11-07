"""Bucket 4 (PRD §8): Dossier -> Decision Card + Processed Invoice Record."""
from app.models import Dossier


def apply_review_policies(decision: str, dossier: Dossier, config: dict) -> tuple[str, str | None]:
    """Control policies that cap how far a decision may go without a human (PRD §10 config).

    Only ever downgrades auto_approve -> approve_pending_review; never touches flag / reject /
    fraud_alert, and never upgrades anything. Returns (decision, plain-English reason or None).
    """
    if (decision == "auto_approve"
            and config.get("review_policies", {}).get("ocr_always_pending_review")
            and dossier.categorization and dossier.categorization.text_source == "ocr"):
        return ("approve_pending_review",
                "This invoice was read from a scan, so our policy is that a person gives it a "
                "one-click check before it is posted - even though every check passed.")
    return decision, None
