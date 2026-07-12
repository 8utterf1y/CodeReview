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
    frame_obligations,
    init_audit,
    finish_audit,
    next_action,
    submit_conclusion,
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

    def _frame_default(self, workspace=None, req_id="REQ-1"):
        workspace = workspace or self.workspace
        framed = frame_obligations(workspace, self._payload(f"frame-{req_id}.json", {
            "requirement_id": req_id,
            "obligations": [{"description": "The implementation should satisfy the requirement.", "source_clause_ids": [req_id]}],
        }))
        return framed["obligations"][0]["id"]

    def test_spec_loader_rejects_filesystem_root(self):
        with self.assertRaisesRegex(ValueError, "refusing to scan filesystem root"):
            load_spec_texts(Path("/"))

    def test_query_mode_aliases_are_normalized(self):
        self._frame_default()
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
        self.assertEqual(action["next_action"], "frame_obligations")
        self.assertIn("code_hints", action)
        framed = frame_obligations(workspace, self._payload("simple-satisfied-frame.json", {
            "requirement_id": "REQ-1",
            "obligations": [{"description": "The implementation should retry transient failures.", "source_clause_ids": ["REQ-1"]}],
        }))
        obligation_id = framed["obligations"][0]["id"]
        self.assertEqual(next_action(workspace)["next_action"], "investigate")
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        submit_conclusion(workspace, self._payload("simple-satisfied-submit.json", {
            "requirement_id": "REQ-1", "conclusion": "satisfied",
            "summary": "The error handler schedules a retry.",
            "obligation_results": [{"obligation_id": obligation_id, "status": "supported", "evidence_ids": query["evidence_ids"]}],
            "uncertainties": [],
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
        framed = frame_obligations(workspace, self._payload("simple-mismatch-frame.json", {
            "requirement_id": "REQ-1",
            "obligations": [{"description": "Retry behavior should be absent in this mismatch fixture.", "source_clause_ids": ["REQ-1"]}],
        }))
        obligation_id = framed["obligations"][0]["id"]
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        negative_query = code_query(workspace, "REQ-1", "investigator", "concept", query="alternate_retry")
        submit_conclusion(workspace, self._payload("simple-mismatch-submit.json", {
            "requirement_id": "REQ-1", "conclusion": "mismatch", "mismatch_kind": "contradiction",
            "summary": "The observed behavior contradicts the requirement.", "title": "Retry behavior mismatch",
            "severity": "high", "confidence": 0.8,
            "obligation_results": [{"obligation_id": obligation_id, "status": "contradicted", "evidence_ids": query["evidence_ids"]}],
            "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "query_ids": [negative_query["query_id"]], "result": "none"}],
            "uncertainties": [],
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
        self._frame_default()
        repository = json.loads((self.workspace / "code-index" / "repository.json").read_text())
        self.assertEqual(repository["languages"]["c"], 1)
        self.assertEqual(repository["build_systems"], ["make"])
        symbols = (self.workspace / "code-index" / "symbols.jsonl").read_text()
        self.assertIn("handle_error", symbols)
        symbol_query = code_query(self.workspace, "REQ-1", "investigator", "symbol", query="handle_error")
        self.assertGreaterEqual(symbol_query["result_count"], 1)
        repo_map = code_query(self.workspace, "REQ-1", "investigator", "repo_map", limit=5)
        self.assertGreaterEqual(repo_map["result_count"], 1)
        self.assertEqual(audit_status(self.workspace)["counts"]["investigation_framed"], 1)

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
        self._frame_default()
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
        self._frame_default()
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
                "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "query_ids": [investigation_query["query_id"]], "result": "none"}],
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
        with self.assertRaisesRegex(ValueError, "call frame_obligations first"):
            submit_conclusion(self.workspace, self._payload("bad-mismatch.json", {
                "requirement_id": "REQ-1", "conclusion": "mismatch", "mismatch_kind": "contradiction",
                "summary": "Mismatch without worksheet details.",
                "title": "Retry behavior mismatch", "severity": "high", "confidence": 0.8,
                "obligation_results": [], "uncertainties": [],
                "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "query_ids": [], "result": "none"}],
            }))

    def test_frame_obligations_rejects_outside_clause(self):
        root = Path(self.temp.name)
        reqs = root / "pack.json"
        reqs.write_text(json.dumps({"requirement_packs": [{
            "id": "PACK-1", "document": "RFC 9999", "section": "3",
            "quote": "A receiver MUST validate messages.", "normalized": "Validate messages.",
            "keywords": ["validate"], "clause_ids": ["RFC9999:3:p0001"],
            "clauses": [{"id": "RFC9999:3:p0001", "document": "RFC 9999", "section": "3", "quote": "A receiver MUST validate messages."}],
        }]}), encoding="utf-8")
        workspace = root / "pack-audit"
        init_audit(self.repo, reqs, workspace)
        with self.assertRaisesRegex(ValueError, "source_clause_ids must belong"):
            frame_obligations(workspace, self._payload("outside-clause.json", {
                "requirement_id": "PACK-1",
                "obligations": [{"description": "Validate messages.", "source_clause_ids": ["RFC9999:9:p0001"]}],
            }))

    def test_code_search_rejected_before_framing(self):
        with self.assertRaisesRegex(ValueError, "call frame_obligations first"):
            code_query(self.workspace, "REQ-1", "investigator", "concept", query="retry")

    def test_submit_conclusion_requires_all_obligation_results(self):
        root = Path(self.temp.name)
        workspace = root / "two-obligations"
        init_audit(self.repo, self.requirements, workspace)
        framed = frame_obligations(workspace, self._payload("two-frame.json", {
            "requirement_id": "REQ-1",
            "obligations": [
                {"description": "First obligation.", "source_clause_ids": ["REQ-1"]},
                {"description": "Second obligation.", "source_clause_ids": ["REQ-1"]},
            ],
        }))
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        with self.assertRaisesRegex(ValueError, "missing obligation result"):
            submit_conclusion(workspace, self._payload("missing-result.json", {
                "requirement_id": "REQ-1", "conclusion": "satisfied",
                "summary": "Only one obligation was checked.",
                "obligation_results": [{"obligation_id": framed["obligations"][0]["id"], "status": "supported", "evidence_ids": query["evidence_ids"]}],
                "uncertainties": [],
            }))

    def test_submit_conclusion_rejects_unknown_obligation_id(self):
        root = Path(self.temp.name)
        workspace = root / "unknown-obligation"
        init_audit(self.repo, self.requirements, workspace)
        self._frame_default(workspace)
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        with self.assertRaisesRegex(ValueError, "unknown obligation id"):
            submit_conclusion(workspace, self._payload("unknown-obligation.json", {
                "requirement_id": "REQ-1", "conclusion": "satisfied",
                "summary": "Unknown obligation.",
                "obligation_results": [{"obligation_id": "OBL-FAKE", "status": "supported", "evidence_ids": query["evidence_ids"]}],
                "uncertainties": [],
            }))

    def test_negative_check_searched_requires_query_ids(self):
        root = Path(self.temp.name)
        workspace = root / "negative-query-binding"
        init_audit(self.repo, self.requirements, workspace)
        obligation_id = self._frame_default(workspace)
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        with self.assertRaisesRegex(ValueError, "status=searched requires query_ids"):
            submit_conclusion(workspace, self._payload("bad-negative.json", {
                "requirement_id": "REQ-1", "conclusion": "mismatch", "mismatch_kind": "contradiction",
                "summary": "Negative check lacks query binding.", "title": "Mismatch", "severity": "high", "confidence": 0.8,
                "obligation_results": [{"obligation_id": obligation_id, "status": "contradicted", "evidence_ids": query["evidence_ids"]}],
                "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "query_ids": [], "result": "none"}],
                "uncertainties": [],
            }))

    def test_final_issue_uses_failed_obligation_clause_provenance(self):
        root = Path(self.temp.name)
        reqs = root / "pack.json"
        reqs.write_text(json.dumps({"requirement_packs": [{
            "id": "PACK-2", "document": "RFC 9999", "section": "3",
            "quote": "Pack quote.", "normalized": "Validate and respond.",
            "keywords": ["validate", "respond"], "clause_ids": ["RFC9999:3:p0001", "RFC9999:3:p0002"],
            "clauses": [
                {"id": "RFC9999:3:p0001", "document": "RFC 9999", "section": "3", "quote": "A receiver MUST validate messages."},
                {"id": "RFC9999:3:p0002", "document": "RFC 9999", "section": "3", "quote": "A receiver MUST respond to valid messages."},
            ],
        }]}), encoding="utf-8")
        workspace = root / "provenance-audit"
        out = root / "issues.json"
        init_audit(self.repo, reqs, workspace, out)
        framed = frame_obligations(workspace, self._payload("provenance-frame.json", {
            "requirement_id": "PACK-2",
            "obligations": [{"description": "Validate and respond.", "source_clause_ids": ["RFC9999:3:p0001", "RFC9999:3:p0002"]}],
        }))
        obligation_id = framed["obligations"][0]["id"]
        query = code_query(workspace, "PACK-2", "investigator", "concept", query="schedule_retry")
        negative_query = code_query(workspace, "PACK-2", "investigator", "concept", query="validate respond")
        submit_conclusion(workspace, self._payload("provenance-conclusion.json", {
            "requirement_id": "PACK-2", "conclusion": "mismatch", "mismatch_kind": "contradiction",
            "summary": "Implementation evidence contradicts the obligation.", "title": "Validation mismatch",
            "severity": "high", "confidence": 0.8,
            "obligation_results": [{"obligation_id": obligation_id, "status": "contradicted", "evidence_ids": query["evidence_ids"]}],
            "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "query_ids": [negative_query["query_id"]], "result": "none"}],
            "uncertainties": [],
        }))
        submit_simple_review(workspace, self._payload("provenance-review.json", {
            "requirement_id": "PACK-2", "verdict": "accept",
            "reason": "The supplied packet supports the mismatch.", "unsupported_claims": [],
        }))
        finish_audit(workspace)
        issue = json.loads(out.read_text())["issues"][0]
        self.assertEqual(
            [item["clause_id"] for item in issue["spec_evidence_items"]],
            ["RFC9999:3:p0001", "RFC9999:3:p0002"],
        )

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
        self.assertEqual(action["next_action"], "frame_obligations")
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
