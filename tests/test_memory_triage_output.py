import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill/scripts'))
import jev_review as review
import memory_triage_output as output


class ExportTests(unittest.TestCase):
    def test_coverage_and_literal_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'input.json'
            source.write_text(json.dumps([{'id': 'a', 'scope': 'p', 'text': 'Keep `token_id`.', 'source': 'original:1'}]))
            candidate = root / 'candidate.json'
            proposal = {'input_sha256': review.digest(source.read_bytes()), 'candidates': []}
            candidate.write_text(json.dumps(proposal))
            with self.assertRaises(ValueError):
                output.export(source, candidate, root / 'missing')
            proposal['candidates'] = [{'id': 'c', 'source_ids': ['a'], 'text': 'Keep the ID.'}]
            candidate.write_text(json.dumps(proposal))
            with self.assertRaises(ValueError):
                output.export(source, candidate, root / 'lost')
            proposal['candidates'][0]['text'] = 'Keep token_id.'
            candidate.write_text(json.dumps(proposal))
            result = output.export(source, candidate, root / 'valid')
            self.assertEqual(result['sources'], 1)
            self.assertFalse(result['native_applied'])
            source.write_text(source.read_text() + '\n')
            with self.assertRaises(ValueError):
                output.export(source, candidate, root / 'stale')
