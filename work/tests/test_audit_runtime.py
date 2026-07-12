import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import urllib.error

from specdiff.audit_runtime import (
    assemble_result,
    audit_status,
    code_query,
    init_audit,
    finish_audit,
    next_action,
    submit_simple_investigation,
    submit_simple_review,
    submit_investigation,
    submit_verification,
    verification_conclusion_context,
)
from specdiff.coverage_gate import validate_result
from specdiff.spec_loader import extract_audit_requirements, load_spec_texts
from specdiff.rfc_prepare import load_rfc_text, prepare_rfc_requirements


class AuditRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "src" / "retry.c").write_text(
            "void schedule_retry(void);\nvoid handle_error(void) { schedule_retry(); }\n",
            encoding="utf-8",
        )
        (self.repo / "Makefile").write_text("SRCS=src/retry.c\n", encoding="utf-8")
        self.requirements = root / "requirements.json"
        self.requirements.write_text(
            json.dumps({"requirements": [{
                "id": "REQ-1", "document": "spec.md", "section": "1",
                "quote": "The service MUST retry.", "normalized": "Retry transient failures.",
                "keywords": ["retry"],
            }]}),
            encoding="utf-8",
        )
        self.workspace = root / "audit"
        init_audit(self.repo, self.requirements, self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def _payload(self, name, payload):
        path = Path(self.temp.name) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_spec_loader_rejects_filesystem_root(self):
        with self.assertRaisesRegex(ValueError, "refusing to scan filesystem root"):
            load_spec_texts(Path("/"))

    def test_query_mode_aliases_are_normalized(self):
        query = code_query(self.workspace, "REQ-1", "investigator", "defs", query="handle_error")
        self.assertEqual(query["mode"], "symbol")
        self.assertEqual(query["parameters"]["requested_mode"], "defs")

    def test_reference_inventory_is_not_an_audit_requirement(self):
        reference_doc = Path(self.temp.name) / "references.md"
        reference_doc.write_text("## Relevant standards\n\n| RFC | Title |\n| --- | --- |\n| RFC 9999 | Example |\n")
        self.assertEqual(extract_audit_requirements(reference_doc), [])

    def test_canonical_requirement_json_is_preserved(self):
        model = Path(self.temp.name) / "requirements.json"
        model.write_text(json.dumps({"requirements": [{
            "id": "REQ-JSON", "document": "design.md", "section": "Retry",
            "quote": "The client MUST retry.", "normalized": "Retry transient failures.",
            "keywords": ["retry"],
        }]}), encoding="utf-8")
        requirements = extract_audit_requirements(model)
        self.assertEqual(requirements[0].id, "REQ-JSON")
        self.assertEqual(requirements[0].source, "parsed_requirement_json")

    def test_prepare_rfcs_uses_cached_official_text_and_excludes_vocabulary(self):
        root = Path(self.temp.name)
        inventory = root / "inventory.md"
        inventory.write_text(
            "| RFC | Title |\n| --- | --- |\n| RFC 2119 | Key Words for Use in RFCs to Indicate Requirement Levels |\n| RFC 9999 | Example Protocol |\n",
            encoding="utf-8",
        )
        cache = root / "rfc-cache"
        cache.mkdir()
        (cache / "rfc9999.txt").write_text(
            "RFC 9999 Example\n\n3.  Message Processing\n\nA receiver MUST validate the incoming message before processing it.\n",
            encoding="utf-8",
        )
        payload = prepare_rfc_requirements(inventory, cache, offline=True)
        self.assertEqual(payload["artifact_type"], "rfc_corpus")
        self.assertEqual(len(payload["clauses"]), 1)
        self.assertLess(len(payload["requirement_packs"]), len(payload["clauses"]) + 2)
        self.assertEqual(payload["excluded_references"][0]["rfc"], "2119")

    def test_rfc_fetch_retries_and_falls_back_to_second_mirror(self):
        root = Path(self.temp.name)
        cache = root / "rfc-cache"
        attempts = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"RFC 9999 Example\n\n3.  Message Processing\n\nA receiver MUST validate the incoming message.\n"

        def fake_urlopen(request, timeout):
            attempts.append((request.full_url, timeout))
            if "rfc-editor" in request.full_url:
                raise urllib.error.URLError(TimeoutError("The read operation timed out"))
            return FakeResponse()

        with mock.patch("specdiff.rfc_prepare.urllib.request.urlopen", side_effect=fake_urlopen):
            text, source = load_rfc_text("9999", cache, offline=False)
        self.assertIn("MUST validate", text)
        self.assertIn("ietf.org", source["source_url"])
        self.assertTrue(any("rfc-editor" in url for url, _timeout in attempts))
        self.assertTrue(any("ietf.org" in url for url, _timeout in attempts))

    def test_rfc_fetch_timeout_has_actionable_error(self):
        root = Path(self.temp.name)
        cache = root / "rfc-cache"
        with mock.patch(
            "specdiff.rfc_prepare.urllib.request.urlopen",
            side_effect=urllib.error.URLError(TimeoutError("The read operation timed out")),
        ):
            with self.assertRaisesRegex(TimeoutError, r"RFC 9999 fetch failed after retries"):
                load_rfc_text("9999", cache, offline=False)

    def test_simple_workflow_satisfied_finishes_without_reviewer(self):
        root = Path(self.temp.name)
        workspace = root / "simple-satisfied"
        out = root / "simple-satisfied.json"
        init_audit(self.repo, self.requirements, workspace, out)
        action = next_action(workspace)
        self.assertEqual(action["next_action"], "investigate")
        self.assertIn("code_hints", action)
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        submit_simple_investigation(workspace, self._payload("simple-satisfied-submit.json", {
            "requirement_id": "REQ-1", "conclusion": "satisfied",
            "summary": "The error handler schedules a retry.",
            "evidence_ids": query["evidence_ids"], "uncertainties": [],
        }))
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        result = finish_audit(workspace)
        self.assertTrue(result["assembled"])
        self.assertEqual(json.loads(out.read_text())["coverage_summary"]["status_counts"], {"covered": 1})

    def test_simple_workflow_mismatch_gets_one_lightweight_review(self):
        root = Path(self.temp.name)
        workspace = root / "simple-mismatch"
        out = root / "simple-mismatch.json"
        init_audit(self.repo, self.requirements, workspace, out)
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        submit_simple_investigation(workspace, self._payload("simple-mismatch-submit.json", {
            "requirement_id": "REQ-1", "conclusion": "mismatch", "mismatch_kind": "contradiction",
            "summary": "The observed behavior contradicts the requirement.", "title": "Retry behavior mismatch",
            "severity": "high", "confidence": 0.8,
            "evidence_ids": query["evidence_ids"], "uncertainties": [],
            "obligations": [{"id": "OBL-1", "description": "Retry must be absent here.", "source_clause_ids": ["REQ-1"]}],
            "findings": [{"obligation_id": "OBL-1", "status": "contradicted", "evidence_ids": query["evidence_ids"]}],
            "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "result": "none"}],
        }))
        action = next_action(workspace)
        self.assertEqual(action["next_action"], "review")
        self.assertEqual(action["review_packet"]["requirement"]["id"], "REQ-1")
        submit_simple_review(workspace, self._payload("simple-review.json", {
            "requirement_id": "REQ-1", "verdict": "accept",
            "reason": "The supplied source evidence supports the mismatch.", "unsupported_claims": [],
        }))
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        finish_audit(workspace)
        self.assertEqual(len(json.loads(out.read_text())["issues"]), 1)

    def test_index_v1_and_controlled_assembly(self):
        repository = json.loads((self.workspace / "code-index" / "repository.json").read_text())
        self.assertEqual(repository["languages"]["c"], 1)
        self.assertEqual(repository["build_systems"], ["make"])
        symbols = (self.workspace / "code-index" / "symbols.jsonl").read_text()
        self.assertIn("handle_error", symbols)
        symbol_query = code_query(self.workspace, "REQ-1", "investigator", "symbol", query="handle_error")
        self.assertGreaterEqual(symbol_query["result_count"], 1)
        repo_map = code_query(self.workspace, "REQ-1", "investigator", "repo_map", limit=5)
        self.assertGreaterEqual(repo_map["result_count"], 1)
        self.assertEqual(audit_status(self.workspace)["pending_investigations"], ["REQ-1"])

        investigation_query = code_query(
            self.workspace, "REQ-1", "investigator", "concept", query="schedule_retry"
        )
        counterexample_query = code_query(
            self.workspace, "REQ-1", "investigator", "concept", query="return failure"
        )
        submit_investigation(
            self.workspace,
            self._payload("investigation.json", {
                "requirement_id": "REQ-1", "proposed_status": "covered",
                "reasoning": "The error path schedules retry.",
                "query_ids": [investigation_query["query_id"]],
                "evidence_ids": investigation_query["evidence_ids"],
                "counterexample_query_ids": [counterexample_query["query_id"]],
            }),
        )
        with self.assertRaisesRegex(ValueError, "blocked"):
            assemble_result(self.workspace, Path(self.temp.name) / "early.json")

        verifier_query = code_query(
            self.workspace, "REQ-1", "verifier", "source", path="src/retry.c", start=1, end=2
        )
        submit_verification(
            self.workspace,
            self._payload("verification.json", {
                "requirement_id": "REQ-1", "verdict": "accepted",
                "reasoning": "Source inspection confirms the call and no contrary branch in the function.",
                "query_ids": [verifier_query["query_id"]],
                "evidence_ids": verifier_query["evidence_ids"],
                "challenges": [{
                    "check": "bypass_path", "outcome": "passed",
                    "note": "No contrary branch in the inspected function.",
                    "evidence_ids": verifier_query["evidence_ids"],
                }],
                "recommended_status": "covered",
            }),
        )
        self.assertTrue(audit_status(self.workspace)["assembly_allowed"])
        out = Path(self.temp.name) / "issues.json"
        assembled = assemble_result(self.workspace, out)
        self.assertTrue(assembled["assembled"])
        self.assertTrue(Path(assembled["sarif"]).exists())
        self.assertEqual(json.loads(out.read_text())["coverage_summary"]["status_counts"], {"covered": 1})
        self.assertTrue(validate_result(out)["valid"])

    def test_locked_requirements_cannot_be_modified(self):
        path = self.workspace / "requirements.json"
        payload = json.loads(path.read_text())
        payload["requirements"][0]["normalized"] = "Changed"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "locked requirements"):
            audit_status(self.workspace)

    def test_submission_rejects_fabricated_query_ids(self):
        with self.assertRaisesRegex(ValueError, "invalid investigator query"):
            submit_investigation(
                self.workspace,
                self._payload("bad.json", {
                    "requirement_id": "REQ-1", "proposed_status": "partial",
                    "reasoning": "Claim", "query_ids": ["Q-FAKE"],
                    "evidence_ids": ["E-FAKE"],
                }),
            )

    def test_low_risk_exact_local_fact_can_skip_agent_verification(self):
        source = code_query(
            self.workspace, "REQ-1", "investigator", "source", path="src/retry.c", start=2, end=2
        )
        countercheck = code_query(
            self.workspace, "REQ-1", "investigator", "concept", query="schedule_retry"
        )
        submit_investigation(
            self.workspace,
            self._payload("local.json", {
                "requirement_id": "REQ-1", "proposed_status": "covered", "claim_scope": "local_fact",
                "reasoning": "The inspected function contains the required retry call.",
                "query_ids": [source["query_id"]], "evidence_ids": source["evidence_ids"],
                "counterexample_query_ids": [countercheck["query_id"]],
            }),
        )
        status = audit_status(self.workspace)
        self.assertTrue(status["assembly_allowed"])
        self.assertEqual(status["counts"]["verification_not_required"], 1)

    def test_verifier_sees_conclusion_only_after_own_query(self):
        investigation_query = code_query(
            self.workspace, "REQ-1", "investigator", "concept", query="schedule_retry"
        )
        submit_investigation(
            self.workspace,
            self._payload("path.json", {
                "requirement_id": "REQ-1", "proposed_status": "partial", "claim_scope": "behavior_path",
                "reasoning": "A behavior gap needs verification.",
                "query_ids": [investigation_query["query_id"]],
                "evidence_ids": investigation_query["evidence_ids"],
                "counterexample_query_ids": [],
                "issue": {"title": "Gap", "match_type": "partial_match", "severity": "low", "confidence": 0.6, "description": "Gap"},
                "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "result": "none"}],
            }),
        )
        with self.assertRaisesRegex(ValueError, "verifier-owned query"):
            verification_conclusion_context(self.workspace, "REQ-1")
        code_query(self.workspace, "REQ-1", "verifier", "source", path="src/retry.c", start=1, end=2)
        context = verification_conclusion_context(self.workspace, "REQ-1")
        self.assertEqual(context["investigation"]["proposed_status"], "partial")

    def test_rfc2119_reference_is_not_product_pack(self):
        root = Path(self.temp.name)
        inventory = root / "rfc2119.md"
        inventory.write_text("| RFC | Title |\n| --- | --- |\n| RFC 2119 | Key Words for Use in RFCs to Indicate Requirement Levels |\n", encoding="utf-8")
        payload = prepare_rfc_requirements(inventory, root / "cache", offline=True)
        self.assertEqual(payload["clauses"], [])
        self.assertEqual(payload["requirement_packs"], [])
        self.assertEqual(payload["excluded_references"][0]["rfc"], "2119")

    def test_mismatch_requires_obligations_and_findings(self):
        query = code_query(self.workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        with self.assertRaisesRegex(ValueError, "non-empty obligations"):
            submit_simple_investigation(self.workspace, self._payload("bad-mismatch.json", {
                "requirement_id": "REQ-1", "conclusion": "mismatch", "mismatch_kind": "contradiction",
                "summary": "Mismatch without worksheet details.",
                "title": "Retry behavior mismatch", "severity": "high", "confidence": 0.8,
                "evidence_ids": query["evidence_ids"], "uncertainties": [],
                "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "result": "none"}],
            }))

    def test_obsoleted_rfc_is_historical_context(self):
        root = Path(self.temp.name)
        inventory = root / "obsolete.md"
        inventory.write_text("| RFC | Title |\n| --- | --- |\n| RFC 1000 | Old Protocol |\n| RFC 2000 | New Protocol |\n", encoding="utf-8")
        cache = root / "cache"
        cache.mkdir()
        (cache / "rfc1000.txt").write_text("1.  Behavior\n\nA node MUST send old packets.\n", encoding="utf-8")
        (cache / "rfc2000.txt").write_text("Obsoletes: 1000\n\n1.  Behavior\n\nA node MUST send new packets.\n", encoding="utf-8")
        payload = prepare_rfc_requirements(inventory, cache, offline=True)
        self.assertEqual(payload["scope"]["RFC1000"]["scope_status"], "historical_context")
        self.assertTrue(all("RFC1000" not in pack["document_ids"] for pack in payload["requirement_packs"]))

    def test_cross_section_behavior_keeps_limited_context(self):
        root = Path(self.temp.name)
        inventory = root / "cross.md"
        inventory.write_text("| RFC | Title |\n| --- | --- |\n| RFC 3000 | Cross Section Protocol |\n", encoding="utf-8")
        cache = root / "cache"
        cache.mkdir()
        (cache / "rfc3000.txt").write_text(
            "1.  Terms\n\nRandom delay means a bounded randomly selected value.\n\n"
            "5.  Behavior A\n\nBehavior A SHOULD use random delay.\n\n"
            "6.  Behavior B\n\nBehavior B uses the same mechanism as Section 5.\n",
            encoding="utf-8",
        )
        payload = prepare_rfc_requirements(inventory, cache, offline=True)
        behavior_pack = next(pack for pack in payload["requirement_packs"] if pack["pack_type"] == "requirement_behavior")
        self.assertIn("RFC3000:5:p0001", behavior_pack["clause_ids"])
        self.assertLessEqual(len(behavior_pack["clause_ids"]), 12)
        self.assertEqual(len(payload["clauses"]), len(payload["dispositions"]))

    def test_missing_capability_pack_is_distributable(self):
        root = Path(self.temp.name)
        inventory = root / "cap.md"
        inventory.write_text("| RFC | Title |\n| --- | --- |\n| RFC 4000 | Protocol X |\n", encoding="utf-8")
        cache = root / "cache"
        cache.mkdir()
        (cache / "rfc4000.txt").write_text("1.  Protocol X\n\nThe system MUST support protocol X.\n", encoding="utf-8")
        payload = prepare_rfc_requirements(inventory, cache, offline=True)
        requirements = root / "packs.json"
        requirements.write_text(json.dumps(payload), encoding="utf-8")
        workspace = root / "cap-audit"
        init_audit(self.repo, requirements, workspace)
        action = next_action(workspace)
        self.assertEqual(action["next_action"], "investigate")
        self.assertTrue(action["requirement_pack"]["id"].startswith("PACK-RFC4000"))

    def test_corpus_compression_and_determinism(self):
        root = Path(self.temp.name)
        inventory = root / "many.md"
        inventory.write_text("| RFC | Title |\n| --- | --- |\n| RFC 5000 | Many Clauses |\n", encoding="utf-8")
        cache = root / "cache"
        cache.mkdir()
        body = []
        for index in range(1, 31):
            body.append(f"{index}.  Section {index}\n\nThis section provides informational context only.\n")
        for index in range(31, 36):
            body.append(f"{index}.  Required {index}\n\nA receiver MUST process message type {index}.\n")
        (cache / "rfc5000.txt").write_text("\n".join(body), encoding="utf-8")
        first = prepare_rfc_requirements(inventory, cache, offline=True)
        second = prepare_rfc_requirements(inventory, cache, offline=True)
        self.assertGreater(len(first["clauses"]), len(first["requirement_packs"]))
        self.assertEqual(len(first["clauses"]), len(first["dispositions"]))
        self.assertEqual(
            [(pack["id"], pack["clause_ids"]) for pack in first["requirement_packs"]],
            [(pack["id"], pack["clause_ids"]) for pack in second["requirement_packs"]],
        )


if __name__ == "__main__":
    unittest.main()
