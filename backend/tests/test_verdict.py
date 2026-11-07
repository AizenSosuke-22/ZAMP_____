from datetime import datetime, timezone

import pytest

from app import settings
from app.models import Categorization, Dossier
from app.pipeline.verdict import apply_review_policies


def dossier(text_source):
    return Dossier(case_id="CASE-000001", config_version=1, run_started=datetime.now(timezone.utc),
                   categorization=Categorization(
                       routing_bucket="C" if text_source == "ocr" else "B", text_source=text_source,
                       page_count=1, model="m", prompt_version="p", cache_hit=False, ungrounded_fields=[]))


def config(on=True):
    c = settings.load_config()
    c["review_policies"]["ocr_always_pending_review"] = on
    return c


def test_default_config_has_policy_on():
    assert settings.load_config()["review_policies"]["ocr_always_pending_review"] is True


def test_ocr_invoice_capped_at_pending_review():
    decision, reason = apply_review_policies("auto_approve", dossier("ocr"), config(on=True))
    assert decision == "approve_pending_review"
    assert "scan" in reason


def test_policy_off_lets_ocr_invoice_auto_approve():
    assert apply_review_policies("auto_approve", dossier("ocr"), config(on=False)) == ("auto_approve", None)


def test_text_layer_invoice_unaffected():
    assert apply_review_policies("auto_approve", dossier("text_layer"), config()) == ("auto_approve", None)


@pytest.mark.parametrize("decision", ["approve_pending_review", "flag", "reject", "fraud_alert"])
def test_policy_never_changes_other_decisions(decision):
    assert apply_review_policies(decision, dossier("ocr"), config()) == (decision, None)
