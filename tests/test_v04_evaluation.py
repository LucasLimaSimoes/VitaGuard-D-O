from pathlib import Path

from vitaguard_do.evaluation.ground_truth import evaluate_policy
from vitaguard_do.extraction.models import EvidenceValidationReport
from vitaguard_do.models.schema import PolicyRecord


ROOT = Path(__file__).resolve().parents[1]


def test_ground_truth_evaluator_scores_identity_as_perfect():
    path = ROOT / "tests" / "ground_truth" / "vitaguard_do_essencial.json"
    policy = PolicyRecord.model_validate_json(path.read_text(encoding="utf-8"))
    report = evaluate_policy(
        policy,
        policy,
        policy_name="self-test",
        evidence_report=EvidenceValidationReport(total_claims=10, valid_claims=10, invalid_claims=0),
    )
    assert report.scalar_accuracy == 1.0
    assert report.financial_accuracy == 1.0
    assert report.canonical_macro_f1 == 1.0
    assert report.nested_sublimit_accuracy == 1.0
    assert report.evidence_validity_rate == 1.0


def test_financial_evaluator_treats_equivalent_decimal_scales_as_equal():
    path = ROOT / "tests" / "ground_truth" / "vitaguard_do_essencial.json"
    expected = PolicyRecord.model_validate_json(path.read_text(encoding="utf-8"))
    extracted = expected.model_copy(deep=True)

    for item in extracted.policy_limits + extracted.policy_deductibles:
        if item.value.numeric_value is not None:
            item.value.numeric_value = item.value.numeric_value.quantize(
                item.value.numeric_value.__class__("0.0")
            )

    report = evaluate_policy(
        extracted,
        expected,
        policy_name="decimal-scale-test",
        evidence_report=EvidenceValidationReport(total_claims=1, valid_claims=1),
    )
    assert report.financial_accuracy == 1.0
    assert report.nested_sublimit_accuracy == 1.0
