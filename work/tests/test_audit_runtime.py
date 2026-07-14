import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import urllib.error

from specdiff.audit_runtime import (
    _audit_lock,
    _lock_file_posix,
    _lock_file_windows,
    _unlock_file_posix,
    _unlock_file_windows,
    assemble_result,
    audit_status,
    code_query,
    dispatch_result,
    frame_obligations,
    init_audit,
    finish_audit,
    next_action,
    submit_batch_results,
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

    def test_audit_lock_creates_lock_byte(self):
        lock_workspace = Path(self.temp.name) / "lock-workspace"
        with _audit_lock(lock_workspace):
            self.assertGreaterEqual((lock_workspace / ".audit.lock").stat().st_size, 1)

    def test_posix_lock_backend_enters_and_releases(self):
        calls = []

        class FakeFcntl:
            LOCK_EX = 1
            LOCK_UN = 2

            def flock(self, _fd, operation):
                calls.append(operation)

        with mock.patch.dict("sys.modules", {"fcntl": FakeFcntl()}):
            with tempfile.TemporaryFile() as handle:
                _lock_file_posix(handle)
                _unlock_file_posix(handle)

        self.assertEqual(calls, [FakeFcntl.LOCK_EX, FakeFcntl.LOCK_UN])

    def test_windows_lock_backend_uses_msvcrt_locking(self):
        calls = []

        class FakeMsvcrt:
            LK_NBLCK = 10
            LK_UNLCK = 11

            def locking(self, _fd, mode, nbytes):
                calls.append((mode, nbytes))

        fake = FakeMsvcrt()
        with mock.patch.dict("sys.modules", {"msvcrt": fake}):
            with tempfile.TemporaryFile() as handle:
                _lock_file_windows(handle, timeout=0.1)
                _unlock_file_windows(handle)

        self.assertEqual(calls, [(fake.LK_NBLCK, 1), (fake.LK_UNLCK, 1)])

    def test_windows_lock_contention_times_out(self):
        class BusyMsvcrt:
            LK_NBLCK = 10
            LK_UNLCK = 11

            def locking(self, _fd, _mode, _nbytes):
                raise OSError("busy")

        with mock.patch.dict("sys.modules", {"msvcrt": BusyMsvcrt()}):
            with mock.patch("specdiff.audit_runtime.time.monotonic", side_effect=[0.0, 1.0]):
                with mock.patch("specdiff.audit_runtime.time.sleep"):
                    with tempfile.TemporaryFile() as handle:
                        with self.assertRaises(TimeoutError):
                            _lock_file_windows(handle, timeout=0.1)

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
        dispatch_result(workspace, self._payload("simple-satisfied-frame-dispatch.json", {
            "requirement_id": "REQ-1", "action": "frame_obligations", "action_id": action["action_id"],
        }))
        obligation_id = framed["obligations"][0]["id"]
        investigate_action = next_action(workspace)
        self.assertEqual(investigate_action["next_action"], "investigate")
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        submit_conclusion(workspace, self._payload("simple-satisfied-submit.json", {
            "requirement_id": "REQ-1", "conclusion": "satisfied",
            "summary": "The error handler schedules a retry.",
            "obligation_results": [{"obligation_id": obligation_id, "status": "supported", "evidence_ids": query["evidence_ids"]}],
            "uncertainties": [],
        }))
        dispatch_result(workspace, self._payload("simple-satisfied-investigate-dispatch.json", {
            "requirement_id": "REQ-1", "action": "investigate", "action_id": investigate_action["action_id"],
        }))
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        result = finish_audit(workspace)
        self.assertTrue(result["assembled"])
        self.assertEqual(json.loads(out.read_text())["coverage_summary"]["status_counts"], {"covered": 1})

    def test_next_action_finish_then_audit_finish_succeeds(self):
        root = Path(self.temp.name)
        workspace = root / "finish-invariant"
        out = root / "finish-invariant.json"
        init_audit(self.repo, self.requirements, workspace, out)
        obligation_id = self._frame_default(workspace)
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        submit_conclusion(workspace, self._payload("finish-submit.json", {
            "requirement_id": "REQ-1", "conclusion": "satisfied",
            "summary": "The error handler schedules a retry.",
            "obligation_results": [{"obligation_id": obligation_id, "status": "supported", "evidence_ids": query["evidence_ids"]}],
            "uncertainties": [],
        }))
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        self.assertTrue(finish_audit(workspace)["assembled"])

    def test_simple_workflow_mismatch_gets_one_lightweight_review(self):
        root = Path(self.temp.name)
        workspace = root / "simple-mismatch"
        out = root / "simple-mismatch.json"
        init_audit(self.repo, self.requirements, workspace, out)
        frame_action = next_action(workspace)
        framed = frame_obligations(workspace, self._payload("simple-mismatch-frame.json", {
            "requirement_id": "REQ-1",
            "obligations": [{"description": "Retry behavior should be absent in this mismatch fixture.", "source_clause_ids": ["REQ-1"]}],
        }))
        dispatch_result(workspace, self._payload("simple-mismatch-frame-dispatch.json", {
            "requirement_id": "REQ-1", "action": "frame_obligations", "action_id": frame_action["action_id"],
        }))
        obligation_id = framed["obligations"][0]["id"]
        investigate_action = next_action(workspace)
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
        dispatch_result(workspace, self._payload("simple-mismatch-investigate-dispatch.json", {
            "requirement_id": "REQ-1", "action": "investigate", "action_id": investigate_action["action_id"],
        }))
        action = next_action(workspace)
        self.assertEqual(action["next_action"], "review")
        self.assertEqual(action["review_packet"]["requirement"]["id"], "REQ-1")
        submit_simple_review(workspace, self._payload("simple-review.json", {
            "requirement_id": "REQ-1", "verdict": "accept",
            "reason": "The supplied source evidence supports the mismatch.", "unsupported_claims": [],
        }))
        dispatch_result(workspace, self._payload("simple-review-dispatch.json", {
            "requirement_id": "REQ-1", "action": "review", "action_id": action["action_id"],
        }))
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        finish_audit(workspace)
        self.assertEqual(len(json.loads(out.read_text())["issues"]), 1)

    def test_dispatch_result_failed_when_state_unchanged(self):
        action = next_action(self.workspace)
        result = dispatch_result(self.workspace, self._payload("dispatch-unchanged.json", {
            "requirement_id": "REQ-1", "action": "frame_obligations", "action_id": action["action_id"],
        }))
        self.assertEqual(result["dispatch_status"], "failed")
        self.assertEqual(result["reason"], "state_unchanged")
        self.assertEqual(result["expected_state"], "framed")
        self.assertEqual(result["current_state"], "pending")

    def test_dispatch_result_without_active_action_returns_structured_failure(self):
        result = dispatch_result(self.workspace, self._payload("dispatch-missing-action.json", {
            "requirement_id": "REQ-1", "action": "frame_obligations", "action_id": "A-STALE",
        }))
        self.assertEqual(result["dispatch_status"], "failed")
        self.assertEqual(result["reason"], "action_not_found")
        self.assertEqual(result["recovery_action"], "call_audit_next")

    def test_committed_action_repeated_dispatch_result_is_idempotent(self):
        action = next_action(self.workspace)
        frame_obligations(self.workspace, self._payload("stale-complete-frame.json", {
            "requirement_id": "REQ-1",
            "obligations": [{"description": "The implementation should satisfy the requirement.", "source_clause_ids": ["REQ-1"]}],
        }))
        first = dispatch_result(self.workspace, self._payload("dispatch-stale-complete.json", {
            "requirement_id": "REQ-1", "action": "frame_obligations", "action_id": action["action_id"],
        }))
        second = dispatch_result(self.workspace, self._payload("dispatch-stale-complete-again.json", {
            "requirement_id": "REQ-1", "action": "frame_obligations", "action_id": action["action_id"],
        }))
        self.assertEqual(first["dispatch_status"], "completed")
        self.assertEqual(second["dispatch_status"], "completed")
        self.assertEqual(second["reason"], "already_committed")

    def test_action_lifecycle_commits_after_state_transition(self):
        action = next_action(self.workspace)
        self.assertEqual(action["action"]["status"], "dispatched")
        frame_obligations(self.workspace, self._payload("lifecycle-frame.json", {
            "requirement_id": "REQ-1",
            "obligations": [{"description": "The implementation should satisfy the requirement.", "source_clause_ids": ["REQ-1"]}],
        }))
        result = dispatch_result(self.workspace, self._payload("lifecycle-dispatch.json", {
            "requirement_id": "REQ-1", "action": "frame_obligations", "action_id": action["action_id"],
        }))
        self.assertEqual(result["dispatch_status"], "completed")
        actions = json.loads((self.workspace / "actions.json").read_text())["actions"]
        self.assertEqual(actions[0]["status"], "committed")
        self.assertEqual(actions[0]["expected_before"], "pending")
        self.assertEqual(actions[0]["expected_after"], "framed")

    def test_conclusion_submit_then_dispatch_result_completed(self):
        frame_action = next_action(self.workspace)
        obligation_id = self._frame_default()
        dispatch_result(self.workspace, self._payload("conclusion-frame-dispatch.json", {
            "requirement_id": "REQ-1", "action": "frame_obligations", "action_id": frame_action["action_id"],
        }))
        investigate_action = next_action(self.workspace)
        query = code_query(self.workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        submit_conclusion(self.workspace, self._payload("conclusion-submit.json", {
            "requirement_id": "REQ-1", "conclusion": "satisfied",
            "summary": "The error handler schedules a retry.",
            "obligation_results": [{"obligation_id": obligation_id, "status": "supported", "evidence_ids": query["evidence_ids"]}],
            "uncertainties": [],
        }))
        result = dispatch_result(self.workspace, self._payload("conclusion-dispatch.json", {
            "requirement_id": "REQ-1", "action": "investigate", "action_id": investigate_action["action_id"],
        }))
        self.assertEqual(result["dispatch_status"], "completed")
        self.assertEqual(result["current_state"], "submitted")

    def test_audit_next_does_not_create_new_action_when_outstanding_exists(self):
        first = next_action(self.workspace)
        second = next_action(self.workspace)
        actions = json.loads((self.workspace / "actions.json").read_text())["actions"]
        self.assertEqual(second["next_action"], "awaiting_dispatch_result")
        self.assertEqual(second["action_id"], first["action_id"])
        self.assertEqual(len(actions), 1)

    def test_first_dispatch_failure_retries_same_action(self):
        self._frame_default()
        action = next_action(self.workspace)
        result = dispatch_result(self.workspace, self._payload("dispatch-retry.json", {
            "requirement_id": "REQ-1", "action": "investigate", "action_id": action["action_id"],
        }))
        self.assertEqual(result["dispatch_status"], "failed")
        self.assertEqual(result["recovery_action"], "retry_same_action")
        self.assertEqual(result["attempt"], 1)
        actions = json.loads((self.workspace / "actions.json").read_text())["actions"]
        self.assertEqual([item["status"] for item in actions[-2:]], ["failed", "dispatched"])

    def test_second_investigation_failure_marks_unknown_and_continues(self):
        root = Path(self.temp.name)
        reqs = root / "two-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "REQ-A", "document": "spec.md", "section": "1", "quote": "A MUST retry.", "normalized": "Retry A.", "keywords": ["retry"]},
            {"id": "REQ-B", "document": "spec.md", "section": "2", "quote": "B MUST retry.", "normalized": "Retry B.", "keywords": ["retry"]},
        ]}), encoding="utf-8")
        workspace = root / "dispatch-two-reqs"
        init_audit(self.repo, reqs, workspace)
        state = json.loads((workspace / "audit-state.json").read_text())
        state["batch_mode"] = False
        (workspace / "audit-state.json").write_text(json.dumps(state), encoding="utf-8")
        self._frame_default(workspace, "REQ-A")
        action = next_action(workspace)
        first = dispatch_result(workspace, self._payload("dispatch-investigate-first.json", {
            "requirement_id": "REQ-A", "action": "investigate", "action_id": action["action_id"],
        }))
        retry = first["retry_packet"]
        second = dispatch_result(workspace, self._payload("dispatch-investigate-second.json", {
            "requirement_id": "REQ-A", "action": "investigate", "action_id": retry["action_id"],
        }))
        self.assertEqual(first["recovery_action"], "retry_same_action")
        self.assertEqual(second["dispatch_status"], "failed_finalized")
        self.assertEqual(second["recovery_action"], "terminal_fallback")
        action_after_fallback = next_action(workspace)
        self.assertEqual(action_after_fallback["requirement_pack"]["id"], "REQ-B")
        status = audit_status(workspace)
        self.assertEqual(status["counts"]["investigation_submitted"], 1)

    def test_failed_investigation_does_not_block_audit(self):
        root = Path(self.temp.name)
        workspace = root / "failed-investigation"
        out = root / "failed-investigation.json"
        init_audit(self.repo, self.requirements, workspace, out)
        self._frame_default(workspace)
        action = next_action(workspace)
        dispatch_result(workspace, self._payload("failed-investigation-1.json", {
            "requirement_id": "REQ-1", "action": "investigate", "action_id": action["action_id"],
        }))
        retry = next(item for item in json.loads((workspace / "actions.json").read_text())["actions"] if item["status"] == "dispatched")
        result = dispatch_result(workspace, self._payload("failed-investigation-2.json", {
            "requirement_id": "REQ-1", "action": "investigate", "action_id": retry["action_id"],
        }))
        self.assertEqual(result["dispatch_status"], "failed_finalized")
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        assembled = finish_audit(workspace)
        self.assertTrue(assembled["assembled"])
        payload = json.loads(out.read_text())
        self.assertEqual(payload["coverage_summary"]["status_counts"], {"unknown": 1})
        self.assertEqual(payload["unverified_requirements"][0]["reason"], "investigator_failed_to_submit")

    def test_validation_failure_does_not_change_business_state(self):
        before = audit_status(self.workspace)
        with self.assertRaisesRegex(ValueError, "source_clause_ids must belong"):
            frame_obligations(self.workspace, self._payload("invalid-frame.json", {
                "requirement_id": "REQ-1",
                "obligations": [{"description": "Invalid source.", "source_clause_ids": ["OTHER"]}],
            }))
        after = audit_status(self.workspace)
        self.assertEqual(before["counts"], after["counts"])
        self.assertEqual(json.loads((self.workspace / "investigation-drafts.json").read_text())["drafts"], [])

    def test_repeated_submit_conclusion_is_idempotent(self):
        root = Path(self.temp.name)
        workspace = root / "idempotent-submit"
        init_audit(self.repo, self.requirements, workspace)
        obligation_id = self._frame_default(workspace)
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        payload = {
            "requirement_id": "REQ-1", "conclusion": "satisfied",
            "summary": "The error handler schedules a retry.",
            "obligation_results": [{"obligation_id": obligation_id, "status": "supported", "evidence_ids": query["evidence_ids"]}],
            "uncertainties": [],
        }
        first = submit_conclusion(workspace, self._payload("idempotent-1.json", payload))
        second = submit_conclusion(workspace, self._payload("idempotent-2.json", payload))
        self.assertTrue(first["accepted"])
        self.assertTrue(second["idempotent"])
        investigations = json.loads((workspace / "investigations.json").read_text())["investigations"]
        self.assertEqual(len(investigations), 1)

    def test_batch_planner_groups_multiple_packs(self):
        root = Path(self.temp.name)
        reqs = root / "batch-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "RFC 2710", "section": "4.1", "quote": "MLD listener MUST report.", "normalized": "MLD listener reports.", "keywords": ["mld"]},
            {"id": "PACK-B", "document": "RFC 2710", "section": "4.2", "quote": "MLD listener MUST delay.", "normalized": "MLD listener delays.", "keywords": ["mld"]},
        ]}), encoding="utf-8")
        workspace = root / "batch-plan"
        init_audit(self.repo, reqs, workspace)
        action = next_action(workspace)
        self.assertEqual(action["next_action"], "investigate_batch")
        self.assertEqual(set(action["batch"]["requirement_ids"]), {"PACK-A", "PACK-B"})
        self.assertNotIn("|4|", action["batch"]["group_key"])

    def test_budgeted_batch_planner_caps_large_pack_sets(self):
        root = Path(self.temp.name)
        reqs = root / "many-batch-reqs.json"
        rows = []
        for index in range(80):
            topic = "retry" if index % 2 == 0 else "handler"
            rows.append({
                "id": f"PACK-{index:03d}", "document": f"RFC {6000 + index}",
                "section": f"{index}.1", "quote": f"The service MUST {topic}.",
                "normalized": f"The service {topic}s.", "keywords": [topic],
            })
        reqs.write_text(json.dumps({"requirements": rows}), encoding="utf-8")
        workspace = root / "many-batches"
        init_audit(self.repo, reqs, workspace)
        batches = json.loads((workspace / "batches.json").read_text())["batches"]
        self.assertLessEqual(len(batches), 30)

    def test_code_affinity_groups_different_sections_by_locality(self):
        root = Path(self.temp.name)
        repo = root / "affinity-repo"
        (repo / "src" / "net").mkdir(parents=True)
        (repo / "src" / "net" / "mld.c").write_text(
            "void mld_report(void) {}\nvoid mld_delay(void) {}\n",
            encoding="utf-8",
        )
        reqs = root / "affinity-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "RFC 2710", "section": "4.1", "quote": "MLD MUST report.", "normalized": "MLD reports.", "keywords": ["mld_report"]},
            {"id": "PACK-B", "document": "RFC 2710", "section": "7.9", "quote": "MLD MUST delay.", "normalized": "MLD delays.", "keywords": ["mld_delay"]},
        ]}), encoding="utf-8")
        workspace = root / "affinity-audit"
        init_audit(repo, reqs, workspace)
        batch = json.loads((workspace / "batches.json").read_text())["batches"][0]
        self.assertEqual(set(batch["requirement_ids"]), {"PACK-A", "PACK-B"})
        self.assertIn("src/net", batch["code_hints"]["components"])
        action = next_action(workspace)
        self.assertNotIn("normalized", action["batch"]["requirements"][0])

    def test_batch_partial_submit_missing_pack_becomes_unknown_and_finishes(self):
        root = Path(self.temp.name)
        reqs = root / "batch-missing-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "RFC 2710", "section": "4.1", "quote": "MLD listener MUST report.", "normalized": "MLD listener reports.", "keywords": ["mld"]},
            {"id": "PACK-B", "document": "RFC 2710", "section": "4.2", "quote": "MLD listener MUST delay.", "normalized": "MLD listener delays.", "keywords": ["mld"]},
        ]}), encoding="utf-8")
        workspace = root / "batch-missing"
        out = root / "batch-missing.json"
        init_audit(self.repo, reqs, workspace, out)
        action = next_action(workspace)
        query = code_query(workspace, "PACK-A", "investigator", "concept", query="schedule_retry")
        submit_batch_results(workspace, self._payload("batch-results.json", {
            "batch_id": action["batch_id"],
            "results": [{
                "requirement_id": "PACK-A", "status": "covered",
                "summary": "PACK-A has evidence.", "spec_clause_ids": [],
                "evidence_ids": query["evidence_ids"], "confidence": 0.8,
            }],
        }))
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        finish_audit(workspace)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["coverage_summary"]["status_counts"], {"covered": 1, "unknown": 1})
        self.assertEqual(payload["unverified_requirements"][0]["requirement_id"], "PACK-B")

    def test_batch_scoped_evidence_can_be_reused_across_packs(self):
        root = Path(self.temp.name)
        reqs = root / "batch-evidence-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "spec", "section": "1", "quote": "The service MUST retry.", "normalized": "Retry.", "keywords": ["retry"]},
            {"id": "PACK-B", "document": "spec", "section": "2", "quote": "The handler MUST retry.", "normalized": "Retry handler.", "keywords": ["retry"]},
        ]}), encoding="utf-8")
        workspace = root / "batch-evidence"
        init_audit(self.repo, reqs, workspace)
        action = next_action(workspace)
        query = code_query(workspace, action["batch_id"], "investigator", "concept", query="schedule_retry")
        evidence_ids = query["evidence_ids"]
        result = submit_batch_results(workspace, self._payload("batch-shared-evidence.json", {
            "batch_id": action["batch_id"],
            "results": [
                {"requirement_id": "PACK-A", "status": "covered", "summary": "Shared retry evidence.", "spec_clause_ids": [], "evidence_ids": evidence_ids, "confidence": 0.8},
                {"requirement_id": "PACK-B", "status": "covered", "summary": "Same implementation path.", "spec_clause_ids": [], "evidence_ids": evidence_ids, "confidence": 0.75},
            ],
        }))
        self.assertEqual(len(result["accepted_results"]), 2)
        self.assertEqual(result["rejected_results"], [])

    def test_active_batch_code_search_needs_no_requirement_id(self):
        root = Path(self.temp.name)
        reqs = root / "batch-alias-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "spec", "section": "1", "quote": "The service MUST retry.", "normalized": "Retry.", "keywords": ["retry"]},
            {"id": "PACK-B", "document": "spec", "section": "2", "quote": "The handler MUST retry.", "normalized": "Retry handler.", "keywords": ["retry"]},
        ]}), encoding="utf-8")
        workspace = root / "batch-alias"
        init_audit(self.repo, reqs, workspace)
        action = next_action(workspace)
        query = code_query(workspace, "", "investigator", "concept", query="schedule_retry")
        self.assertEqual(query["requirement_id"], action["batch_id"])
        self.assertEqual(query["batch_id"], action["batch_id"])
        evidence = json.loads((workspace / "evidence.jsonl").read_text().splitlines()[0])
        self.assertEqual(evidence["batch_id"], action["batch_id"])

    def test_wrong_pack_or_semantic_id_does_not_break_active_batch_discovery(self):
        root = Path(self.temp.name)
        reqs = root / "batch-wrong-id-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "spec", "section": "1", "quote": "The service MUST retry.", "normalized": "Retry.", "keywords": ["retry"]},
            {"id": "PACK-B", "document": "spec", "section": "2", "quote": "The handler MUST retry.", "normalized": "Retry handler.", "keywords": ["retry"]},
        ]}), encoding="utf-8")
        workspace = root / "batch-wrong-id"
        init_audit(self.repo, reqs, workspace)
        action = next_action(workspace)
        query = code_query(workspace, "MLD-002", "investigator", "concept", query="schedule_retry")
        self.assertEqual(query["requirement_id"], action["batch_id"])
        self.assertEqual(query["parameters"]["requested_requirement_id"], "MLD-002")
        result = submit_batch_results(workspace, self._payload("batch-wrong-id-results.json", {
            "batch_id": action["batch_id"],
            "results": [
                {"requirement_id": "PACK-A", "status": "covered", "summary": "Shared evidence.", "spec_clause_ids": [], "evidence_ids": query["evidence_ids"], "confidence": 0.8},
                {"requirement_id": "PACK-B", "status": "covered", "summary": "Same shared evidence.", "spec_clause_ids": [], "evidence_ids": query["evidence_ids"], "confidence": 0.8},
            ],
        }))
        self.assertEqual(len(result["accepted_results"]), 2)

    def test_text_query_falls_back_when_rg_is_missing(self):
        with mock.patch("specdiff.audit_runtime.subprocess.run", side_effect=FileNotFoundError()):
            self._frame_default()
            query = code_query(self.workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        self.assertTrue(query["evidence_ids"])
        evidence = json.loads((self.workspace / "evidence.jsonl").read_text().splitlines()[-1])
        self.assertEqual(evidence["backend"], "python_text_search")

    def test_batch_query_budget_limits_broad_text_search(self):
        root = Path(self.temp.name)
        reqs = root / "batch-budget-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "spec", "section": "1", "quote": "The service MUST retry.", "normalized": "Retry.", "keywords": ["retry"]},
            {"id": "PACK-B", "document": "spec", "section": "2", "quote": "The handler MUST retry.", "normalized": "Retry handler.", "keywords": ["retry"]},
        ]}), encoding="utf-8")
        workspace = root / "batch-budget"
        init_audit(self.repo, reqs, workspace)
        action = next_action(workspace)
        for index in range(6):
            code_query(workspace, action["batch_id"], "investigator", "concept", query=f"retry|schedule_retry|handle_error|{index}")
        with self.assertRaisesRegex(ValueError, "batch text query budget exceeded"):
            code_query(workspace, action["batch_id"], "investigator", "concept", query="one_more_text_query")

    def test_invalid_batch_result_does_not_reject_valid_results(self):
        root = Path(self.temp.name)
        reqs = root / "batch-invalid-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "spec", "section": "1", "quote": "The service MUST retry.", "normalized": "Retry.", "keywords": ["retry"]},
            {"id": "PACK-B", "document": "spec", "section": "2", "quote": "The handler MUST retry.", "normalized": "Retry handler.", "keywords": ["retry"]},
        ]}), encoding="utf-8")
        workspace = root / "batch-invalid"
        out = root / "batch-invalid.json"
        init_audit(self.repo, reqs, workspace, out)
        action = next_action(workspace)
        query = code_query(workspace, action["batch_id"], "investigator", "concept", query="schedule_retry")
        result = submit_batch_results(workspace, self._payload("batch-invalid-results.json", {
            "batch_id": action["batch_id"],
            "results": [
                {"requirement_id": "PACK-A", "status": "covered", "summary": "Valid.", "spec_clause_ids": [], "evidence_ids": query["evidence_ids"], "confidence": 0.8},
                {"requirement_id": "PACK-B", "status": "covered", "summary": "Invalid evidence.", "spec_clause_ids": [], "evidence_ids": ["E-NOPE"], "confidence": 0.8},
            ],
        }))
        self.assertEqual([item["requirement_id"] for item in result["accepted_results"]], ["PACK-A"])
        self.assertEqual(result["rejected_results"][0]["requirement_id"], "PACK-B")
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        finish_audit(workspace)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["coverage_summary"]["status_counts"], {"covered": 1, "unknown": 1})

    def test_partial_batch_result_outputs_issue(self):
        root = Path(self.temp.name)
        reqs = root / "batch-partial-reqs.json"
        reqs.write_text(json.dumps({"requirements": [
            {"id": "PACK-A", "document": "spec", "section": "1", "quote": "The service MUST retry.", "normalized": "Retry.", "keywords": ["retry"]},
            {"id": "PACK-B", "document": "spec", "section": "2", "quote": "The handler SHOULD retry.", "normalized": "Retry handler.", "keywords": ["retry"]},
        ]}), encoding="utf-8")
        workspace = root / "batch-partial"
        out = root / "batch-partial.json"
        init_audit(self.repo, reqs, workspace, out)
        action = next_action(workspace)
        query = code_query(workspace, action["batch_id"], "investigator", "concept", query="schedule_retry")
        submit_batch_results(workspace, self._payload("batch-partial-results.json", {
            "batch_id": action["batch_id"],
            "results": [
                {
                    "requirement_id": "PACK-A", "status": "partial",
                    "summary": "Retry path exists but behavior is incomplete.",
                    "spec_clause_ids": [], "evidence_ids": query["evidence_ids"], "confidence": 0.7,
                    "issue": {"title": "Retry behavior is partial", "severity": "medium"},
                },
                {"requirement_id": "PACK-B", "status": "unknown", "summary": "Not investigated.", "spec_clause_ids": [], "evidence_ids": [], "confidence": 0.1},
            ],
        }))
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        finish_audit(workspace)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["coverage_summary"]["status_counts"], {"partial": 1, "unknown": 1})
        self.assertEqual(payload["issues"][0]["requirement_id"], "PACK-A")
        self.assertTrue(out.with_suffix(".sarif").exists())

    def test_failed_review_can_continue(self):
        root = Path(self.temp.name)
        workspace = root / "failed-review"
        out = root / "failed-review.json"
        init_audit(self.repo, self.requirements, workspace, out)
        obligation_id = self._frame_default(workspace)
        query = code_query(workspace, "REQ-1", "investigator", "concept", query="schedule_retry")
        negative_query = code_query(workspace, "REQ-1", "investigator", "concept", query="alternate_retry")
        submit_conclusion(workspace, self._payload("failed-review-submit.json", {
            "requirement_id": "REQ-1", "conclusion": "mismatch", "mismatch_kind": "contradiction",
            "summary": "The observed behavior contradicts the requirement.", "title": "Mismatch",
            "severity": "high", "confidence": 0.8,
            "obligation_results": [{"obligation_id": obligation_id, "status": "contradicted", "evidence_ids": query["evidence_ids"]}],
            "negative_checks": [{"dimension": "alternative_implementation", "status": "searched", "query_ids": [negative_query["query_id"]], "result": "none"}],
            "uncertainties": [],
        }))
        self.assertEqual(next_action(workspace)["next_action"], "review")
        dispatch_result(workspace, self._payload("failed-review-1.json", {
            "requirement_id": "REQ-1", "action": "review",
        }))
        result = dispatch_result(workspace, self._payload("failed-review-2.json", {
            "requirement_id": "REQ-1", "action": "review",
        }))
        self.assertEqual(result["dispatch_status"], "failed_finalized")
        self.assertEqual(next_action(workspace)["next_action"], "finish")
        finish_audit(workspace)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["coverage_summary"]["status_counts"], {"unknown": 1})
        self.assertEqual(payload["unverified_requirements"][0]["reason"], "reviewer_failed_to_submit")

    def test_source_query_returns_one_evidence_span(self):
        root = Path(self.temp.name)
        repo = root / "span-repo"
        repo.mkdir()
        (repo / "foo.c").write_text("\n".join(f"int line_{index};" for index in range(1, 151)), encoding="utf-8")
        reqs = root / "span-reqs.json"
        reqs.write_text(json.dumps({"requirements": [{
            "id": "REQ-SPAN", "document": "spec.md", "section": "1",
            "quote": "The module MUST expose a source span.", "normalized": "Expose source span.",
            "keywords": ["source"],
        }]}), encoding="utf-8")
        workspace = root / "span-audit"
        init_audit(repo, reqs, workspace)
        self._frame_default(workspace, "REQ-SPAN")
        query = code_query(workspace, "REQ-SPAN", "investigator", "source", path="foo.c", start=100, end=130)
        self.assertEqual(query["result_count"], 1)
        self.assertEqual(len(query["evidence_ids"]), 1)
        evidence = json.loads((workspace / "evidence.jsonl").read_text().splitlines()[0])
        self.assertEqual(evidence["start_line"], 100)
        self.assertEqual(evidence["end_line"], 130)
        self.assertEqual(evidence["precision"], "exact_source_span")

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
        self.assertEqual(action["next_action"], "investigate_batch")
        self.assertTrue(action["batch"]["requirement_ids"][0].startswith("PACK-RFC4000"))

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
