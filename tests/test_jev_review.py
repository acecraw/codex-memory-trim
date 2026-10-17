import importlib.util
import contextlib
import io
import json
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("review", Path(__file__).resolve().parents[1] / "skill/scripts/jev_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def entry(ident="a", **changes):
    return dict(id=ident, text="Keep the API limit 1..10.", scope="project", context="Current rule.", source="fixture:1", protected=False, **changes)


def answers(value, confidence=1, enough=1):
    a = {k: {"score": value / 25, "confidence": confidence} for k in review.LEVELS}
    a["enough_context"] = {"noul": enough}
    return a


class ReviewTests(unittest.TestCase):
    def test_band_boundaries_do_not_round_up(self):
        for value, band in [(39.999, "low_value_candidate"), (40, "reference"), (59.999, "reference"), (60, "retain"), (79.999, "retain"), (80, "core")]:
            self.assertEqual(review.score_result(entry(), answers(value))["band"], band)

    def test_protection_overrides_low_score_and_uncertainty(self):
        e = entry()
        e["protected"] = True
        self.assertEqual(review.score_result(e, answers(10, enough=.1))["disposition"], "protected_retain")

    def test_uncertainty_is_review_not_low_value(self):
        self.assertEqual(review.score_result(entry(), answers(95, confidence=.3))["disposition"], "review")
        self.assertEqual(review.score_result(entry(), answers(10, enough=.3))["disposition"], "review")

    def test_compression_is_not_value(self):
        a = answers(60)
        a["compression"]["score"] = 0
        self.assertEqual(review.score_result(entry(), a)["value"], 60)

    def test_expected_answers_and_provenance_never_leave_in_state(self):
        e = entry(expected="secret label", private_customer="private")
        self.assertEqual(set(review.public_entry(e)), {"text", "scope", "context"})

    def test_shortlist_keeps_cross_scope_candidate_without_self_pairs(self):
        a, b = entry("a"), entry("b")
        b["scope"] = "other project"
        self.assertEqual(review.shortlist([a, b], 1), [("a", "b")])
        self.assertEqual(review.shortlist([a, b], 0), [])

    def test_language_and_exact_literal_guards(self):
        e = entry(protected_literals=["1..10"])
        bad = review.candidate_checks(e, {"text": "Keep 1..100. 授权"})
        self.assertEqual(bad["missing_literals"], ["1..10"])
        self.assertTrue(bad["unapproved_chinese"])
        good = review.candidate_checks(e, {"text": "Keep 1..10; retain 发票.", "retained_terms": ["发票"]})
        self.assertFalse(good["unapproved_chinese"])

    def test_duplicate_ids_and_invalid_pair_rejected(self):
        with self.assertRaises(ValueError):
            review.validate_input({"entries": [entry(), entry()]})
        with self.assertRaises(ValueError):
            review.validate_input({"entries": [entry()], "pairs": [{"a": "a", "b": "missing"}]})

    def test_literal_must_come_from_source(self):
        with self.assertRaises(ValueError):
            review.validate_input({"entries": [entry(protected_literals=["invented"])]})

    def test_reversed_duplicate_pair_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate pair"):
            review.validate_input({"entries": [entry("a"), entry("b")],
                "pairs": [{"a": "a", "b": "b"}, {"a": "b", "b": "a"}]})

    def test_chinese_terms_require_precision_justification(self):
        with self.assertRaisesRegex(ValueError, "justification"):
            review.validate_input({"entries": [entry()], "candidates": [
                {"entry": "a", "text": "Keep 发票.", "retained_terms": ["发票"]}]})

    def test_distribution_must_be_complete(self):
        q = {"s": {"type": "score", "criteria": ["a", "b"]}}
        with self.assertRaises(ValueError):
            review.strict_answer_check({"s": {"score": 0, "confidence": 1, "probabilities": {"0": 1}}}, q)

    def test_prepare_and_partial_report_keep_labels_local_and_reject_stale_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = root / "client.py"
            client.write_text("def validate_request(p): pass\ndef validate_response(r, p): pass\n")
            dataset = root / "input.json"
            dataset.write_text(json.dumps({"entries": [entry("a"), entry("b")],
                "pairs": [{"a": "a", "b": "b", "expected": ["equivalent"]}]}))
            plan = root / "plan"
            with contextlib.redirect_stdout(io.StringIO()):
                review.prepare(SimpleNamespace(input=dataset, output=plan, client=client, top_k=0))
            manifest = review.read(plan / "manifest.json")
            for req in manifest["requests"]:
                payload = (plan / req["path"]).read_text()
                self.assertNotIn('"expected"', payload)
                self.assertNotIn('fixture:1', payload)
            results = root / "results"
            (results / "raw").mkdir(parents=True)
            (results / "attempts").mkdir()
            req = manifest["requests"][0]
            jid = req["id"]
            a = {k: {"type": "score", "score": 3, "confidence": 1,
                "probabilities": {str(i): int(i == 3) for i in range(5)}} for k in review.LEVELS}
            a["enough_context"] = {"type": "noul", "noul": 1}
            review.write_new(results / "summary.json", {"records": [{"id": jid, "status": "completed"}]})
            attempt = results / "attempts" / (jid + ".json")
            review.write_new(attempt, {"sha256": req["sha256"]})
            review.write_new(results / "raw" / (jid + ".json"), {"model": "jev-test", "answers": a,
                "usage": {"input_tokens": 1, "output_tokens": 1}})
            args = SimpleNamespace(plan=plan / "plan.json", results=results, client=client, output=root / "report")
            with contextlib.redirect_stdout(io.StringIO()):
                review.report(args)
            report = review.read(root / "report" / "report.json")
            self.assertEqual(len(report["missing"]), 2)
            self.assertEqual(report["jobs"][0]["disposition"], "retain")
            pair_req = next(r for r in manifest["requests"] if r["id"] == "pair_0")
            pair_answers = {"relation": {"type": "choice", "choice": "conflict", "confidence": 1,
                "probabilities": {k: int(k == "conflict") for k in review.RELATIONS}}}
            pair_answers.update({k: {"type": "noul", "noul": 1} for k in ("same_scope", "a_unique", "b_unique")})
            review.write_new(results / "attempts/pair_0.json", {"sha256": pair_req["sha256"]})
            review.write_new(results / "raw/pair_0.json", {"model": "jev-test", "answers": pair_answers,
                "usage": {"input_tokens": 1, "output_tokens": 1}})
            (results / "summary.json").write_text(json.dumps({"records": [
                {"id": jid, "status": "completed"}, {"id": "pair_0", "status": "completed"}]}))
            args.output = root / "conflict-report"
            with contextlib.redirect_stdout(io.StringIO()):
                review.report(args)
            updated = review.read(args.output / "report.json")
            self.assertEqual(updated["jobs"][0]["disposition"], "conflict_review")
            attempt.write_text(json.dumps({"sha256": "0" * 64}))
            args.output = root / "stale-report"
            with self.assertRaisesRegex(ValueError, "attempt mismatch"):
                review.report(args)
            self.assertFalse(args.output.exists())


if __name__ == "__main__":
    unittest.main()
