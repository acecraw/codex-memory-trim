import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill/scripts'))
import jev_review as review
import memory_queue as queue
import memory_triage as triage

CLIENT = Path(__file__).parent / 'fixtures' / 'mock_jev_client.py'


def response(payload):
    answers = {}
    for key, question in payload['questions'].items():
        if question['type'] == 'noul':
            answers[key] = {'type': 'noul', 'noul': 1 if key == 'requires_followup' else 0}
        else:
            selected = 'open_obligation' if key == 'time_status' else next(iter(question['criteria']))
            answers[key] = {'type': 'choice', 'choice': selected, 'confidence': 1,
                            'probabilities': {k: int(k == selected) for k in question['criteria']}}
    return json.dumps({'model': 'jev-mock', 'answers': answers, 'usage': {'input_tokens': 2, 'output_tokens': 3}})


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.input = self.root / 'input.json'
        self.entries = [
            {'id': 'a', 'scope': 'one', 'text': 'Submit invoice by 2020-01-01; payment still pending.', 'context': 'No settlement receipt.', 'source': 'memory.md:1'},
            {'id': 'b', 'scope': 'one', 'text': 'Submit invoice by 2020-01-01; payment still pending.', 'context': 'No settlement receipt.', 'source': 'memory.md:2'},
            {'id': 'c', 'scope': 'other', 'text': 'Submit invoice by 2020-01-01; payment still pending.', 'context': 'Other customer.', 'source': 'memory.md:3'},
        ]
        self.input.write_text(json.dumps(self.entries))

    def tearDown(self):
        self.tmp.cleanup()

    def run_queue(self, directory):
        db = queue.connect(directory / 'queue.sqlite')
        for path in sorted(directory.glob('batch-*.json')):
            batch, client = queue.load_batch(path, CLIENT)
            queue.dispatch(batch, db, client, sender=lambda j: response(j['payload']))
        db.close()

    def test_expired_deadline_is_explicitly_not_closure_and_unused_not_abandoned(self):
        plan = triage.annotate(self.input, self.root / 'annotations', CLIENT, '2026-09-25')
        self.assertEqual(plan['jobs'], 3)
        batch, _ = queue.load_batch(self.root / 'annotations/batch-00000.json', CLIENT)
        questions = batch['jobs'][0]['payload']['questions']
        self.assertIn('past deadline alone', questions['time_status']['instructions'])
        self.assertIn('imperative wording', questions['time_status']['instructions'])
        self.assertIn('unused idea is not abandoned', questions['usefulness']['instructions'])
        self.assertIn('one-off task', questions['usefulness']['instructions'])
        self.assertIn('tentative idea', questions['usefulness']['instructions'])
        self.assertEqual(list(questions['memory_kind']['criteria']), list(triage.MEMORY_KIND))
        self.assertEqual(list(questions['time_status']['criteria']), list(triage.TIME))
        self.assertEqual(list(questions['usefulness']['criteria']), list(triage.USEFULNESS))
        self.assertNotIn('score', questions)

    def test_scope_exact_duplicate_and_bounded_retrieval(self):
        self.assertEqual(triage.shortlist(self.entries, 3), [('a', 'b')])
        self.assertEqual(triage.shortlist(self.entries, 0), [])

    def test_incomplete_queue_rejected_and_results_preserved(self):
        ann = self.root / 'annotations'
        triage.annotate(self.input, ann, CLIENT, '2026-09-25')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            triage.relations(self.input, ann, self.root / 'relations', CLIENT)
        self.run_queue(ann)
        rel = self.root / 'relations'
        result = triage.relations(self.input, ann, rel, CLIENT)
        self.assertEqual(result['jobs'], 1)
        exported = review.read(rel / 'annotations.results.json')
        self.assertEqual(len(exported['results']), 3)
        self.assertIn('raw_response', exported['results'][0])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            triage.packets(self.input, ann, rel, self.root / 'packets', CLIENT)
        self.run_queue(rel)
        coverage = triage.packets(self.input, ann, rel, self.root / 'packets2', CLIENT)
        self.assertEqual(set(coverage['covered_ids']), {'a', 'b', 'c'})
        self.assertEqual(set(coverage['id_to_packet']), {'a', 'b', 'c'})
        self.assertEqual(len(review.read(self.root / 'packets2/relations.results.json')['results']), 1)

    def test_packet_bounds_and_oversized_exclusion(self):
        self.entries += [{'id': 'x%d' % i, 'scope': 'one', 'text': 'Unrelated item %d' % i,
                          'context': 'Context', 'source': 'memory.md:%d' % (i + 4)} for i in range(10)]
        self.entries.append({'id': 'large', 'scope': 'one', 'text': 'large ' * 4000,
                             'context': 'Context', 'source': 'memory.md:99'})
        self.input.write_text(json.dumps(self.entries))
        ann = self.root / 'annotations'
        triage.annotate(self.input, ann, CLIENT, '2026-09-25')
        self.run_queue(ann)
        rel = self.root / 'relations'
        triage.relations(self.input, ann, rel, CLIENT, top_k=0)
        coverage = triage.packets(self.input, ann, rel, self.root / 'packets', CLIENT)
        self.assertEqual(len(coverage['covered_ids']) + len(coverage['excluded']), len(self.entries))
        self.assertIn('large', {x['id'] for x in coverage['excluded']})
        for name in coverage['packets']:
            path = self.root / 'packets' / name
            self.assertLessEqual(len(path.read_bytes()), 16000)
            self.assertLessEqual(len(review.read(path)['entries']), 8)


if __name__ == '__main__':
    unittest.main()
