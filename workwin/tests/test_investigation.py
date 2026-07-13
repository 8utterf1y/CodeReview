import unittest

from specdiff.investigation import (
    validate_investigations,
    validate_requirement_models,
    validate_verifications,
)


def requirement_models(responsibility="confirmed"):
    return {
        "requirements": [
            {
                "id": "REQ-1",
                "source": {"document": "spec.md", "section": "1", "quote": "The service MUST retry."},
                "interpretation": {"statement": "Retry transient failures."},
                "responsibility": {"status": responsibility, "reasoning": "The service is implemented here."},
                "behavior_model": {"triggers": ["failure"], "required_actions": ["retry"]},
                "proof_obligations": [
                    {
                        "id": "REQ-1-PO-1",
                        "claim": "Transient failures reach retry scheduling.",
                        "kind": "path_invariant",
                        "evidence_needed": ["entry path", "scheduler call"],
                        "success_condition": "Every transient failure path schedules a retry.",
                        "contradiction_condition": "A transient failure returns without scheduling.",
                    }
                ],
                "uncertainties": [],
                "inferred": False,
            }
        ]
    }


def investigations(status="supported", proposed="covered"):
    return {
        "investigations": [
            {
                "requirement_id": "REQ-1",
                "obligation_results": [
                    {
                        "obligation_id": "REQ-1-PO-1",
                        "status": status,
                        "queries": [{"type": "callers", "purpose": "Enumerate retry callers"}],
                        "evidence": [{"file": "src/retry.c", "line": 10, "quote": "schedule_retry();"}],
                    }
                ],
                "counterexample_searches": [{"type": "bypass_search"}],
                "proposed_status": proposed,
            }
        ]
    }


class InvestigationValidationTests(unittest.TestCase):
    def test_valid_proof_pipeline(self):
        models = requirement_models()
        investigation = investigations()
        verification = {
            "verifications": [
                {
                    "requirement_id": "REQ-1",
                    "verdict": "accepted",
                    "challenges": [],
                    "reasoning": "Evidence and bypass search support the obligation.",
                }
            ]
        }
        self.assertTrue(validate_requirement_models(models)["valid"])
        self.assertTrue(validate_investigations(investigation, models)["valid"])
        self.assertTrue(validate_verifications(verification, models, investigation)["valid"])

    def test_unresolved_responsibility_cannot_be_violated(self):
        result = validate_investigations(
            investigations(status="contradicted", proposed="violated"),
            requirement_models(responsibility="unresolved"),
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any("responsibility" in item for item in result["errors"]))

    def test_covered_requires_all_obligations_and_counterexample_search(self):
        investigation = investigations(status="unresolved", proposed="covered")
        investigation["investigations"][0]["counterexample_searches"] = []
        result = validate_investigations(investigation, requirement_models())
        self.assertFalse(result["valid"])
        self.assertTrue(any("every proof obligation" in item for item in result["errors"]))
        self.assertTrue(any("counterexample_searches" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
