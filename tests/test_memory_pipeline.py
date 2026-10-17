import concurrent.futures
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill/scripts'))
import memory_pipeline as pipeline
import memory_queue as queue
import memory_output as output
import jev_review as review

CLIENT = Path(__file__).parent / 'fixtures' / 'mock_jev_client.py'


def response(payload):
    answers = {}
    for key, question in payload['questions'].items():
        kind = question['type']
        if kind == 'noul':
            answers[key] = {'type': kind, 'noul': 0 if key in ('rule_conflict', 'a_unique', 'b_unique') else 1}
        else:
            criteria = question['criteria']
            keys = list(criteria) if kind == 'choice' else [str(i) for i in range(len(criteria))]
            selected = keys[0] if kind == 'choice' else keys[-1]
            answers[key] = {'type': kind, kind: selected if kind == 'choice' else int(selected),
                            'confidence': 1, 'probabilities': {k: int(k == selected) for k in keys}}
    return json.dumps({'model': 'jev-mock', 'answers': answers, 'usage': {'input_tokens': 1, 'output_tokens': 1}})


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'memory.md'
        self.source.write_text('# Task Group: Project\nscope: project only\n\n## Task 1: recovery\n### rollout_summary_files\n- run.md (historical)\n### knowledge\n- Preserve `token_id`.\n  - Nested exception.\n  ```text\n# code heading\n- code bullet\n  ```\n- Keep the source and timestamp.\n')
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'sources': [{'path': str(self.source), 'scope': 'project'}]}))
        self.index = self.root / 'index'
        pipeline.index(self.config, self.index)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lossless_partition_and_code_nested(self):
        rows = list(pipeline.units(self.source))
        self.assertEqual(''.join(r[3] for r in rows), self.source.read_text())
        unit = next(r[3] for r in rows if 'Preserve' in r[3])
        self.assertIn('- Nested exception.', unit)
        self.assertIn('# code heading', unit)
        self.assertIn('- code bullet', unit)
        db = pipeline.db_open(self.index)
        row = db.execute("SELECT * FROM entries WHERE body LIKE '- Preserve%'").fetchone()
        self.assertIn('run.md', pipeline.entry(row, db)['context'])
        db.close()

    def test_ids_stable_when_other_entry_changes(self):
        db = pipeline.db_open(self.index)
        before = db.execute("SELECT id FROM entries WHERE body LIKE '- Preserve%'").fetchone()[0]
        db.close()
        self.source.write_text(self.source.read_text().replace('Keep the source', 'Keep the original source'))
        pipeline.index(self.config, self.root / 'second')
        db = pipeline.db_open(self.root / 'second')
        self.assertEqual(before, db.execute("SELECT id FROM entries WHERE body LIKE '- Preserve%'").fetchone()[0])
        db.close()

    def test_plan_dry_run_resume_and_draft(self):
        plan = self.root / 'plan'
        stats = pipeline.plan(self.index, plan, CLIENT, 'mock-epoch')
        self.assertEqual(stats['concurrency'], 500)
        self.assertEqual(stats['jobs']['score'], 2)
        batch, client = queue.load_batch(plan / 'batch-00000.json', CLIENT)
        db = queue.connect(plan / 'queue.sqlite')
        result = queue.dispatch(batch, db, client, 500, sender=lambda job: response(job['payload']))
        self.assertEqual(result['status_counts'], {'completed': len(batch['jobs'])})
        result = queue.dispatch(batch, db, client, sender=lambda job: self.fail('cached request resent'))
        self.assertEqual(result['attempted'], 0)
        db.close()
        output.report(plan, self.root / 'report', CLIENT)
        packet_dir = self.root / 'packets'
        pipeline.packets(self.index, packet_dir, report_path=self.root / 'report/report.json')
        packet = review.read(packet_dir / 'packet-00000.json')
        self.assertTrue(any(e['jev_evidence'] for e in packet['entries']))
        self.assertLessEqual(len((packet_dir / 'packet-00000.json').read_bytes()), 40000)
        # One merged draft accounts for every source unit, with literal preserved.
        ids = [e['id'] for e in packet['entries']]
        candidates = self.root / 'candidates.json'
        candidates.write_text(json.dumps({'candidates': [{'id': 'english', 'source_ids': ids,
            'text': 'Preserve token_id, the source and timestamp, including the nested exception.'}]}))
        draft_plan = self.root / 'draft'
        summary = output.draft(self.index, candidates, draft_plan, CLIENT, 'mock-epoch')
        self.assertEqual(summary['missing'], 0)
        batch, client = queue.load_batch(draft_plan / 'batch-00000.json', CLIENT)
        db = queue.connect(draft_plan / 'queue.sqlite')
        queue.dispatch(batch, db, client, sender=lambda job: response(job['payload']))
        db.close()
        output.report(draft_plan, self.root / 'export', CLIENT)
        self.assertTrue(review.read(self.root / 'export/coverage.json')['all_sources_covered'])
        self.assertEqual(self.source.read_bytes(), (self.index / 'snapshots/0000.md').read_bytes())

    def test_unknown_scope_not_sent(self):
        self.config.write_text(json.dumps({'sources': [{'path': str(self.source)}]}))
        root = self.root / 'unknown'
        pipeline.index(self.config, root)
        stats = pipeline.plan(root, self.root / 'empty', CLIENT, 'mock')
        self.assertEqual(stats['batches'], 0)
        self.assertEqual(stats['entry_states']['review'], 2)

    def test_failure_stops_and_interrupted_is_not_retried(self):
        jobs = [{'key': str(i), 'payload': {'questions': {}}} for i in range(10)]
        db = queue.connect(self.root / 'state.sqlite')
        def fail(job):
            raise TimeoutError()
        result = queue.dispatch({'jobs': jobs}, db, None, concurrency=1, sender=fail)
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['status_counts'], {'unknown': 1, 'pending': 9})
        with self.assertRaises(ValueError):
            queue.dispatch({'jobs': jobs}, db, None, sender=fail)
        db.execute("INSERT INTO jobs(key,status) VALUES('interrupted','running')")
        db.commit()
        with self.assertRaises(ValueError):
            queue.dispatch({'jobs': [{'key': 'interrupted'}]}, db, None, sender=fail)
        self.assertEqual(db.execute("SELECT status FROM jobs WHERE key='interrupted'").fetchone()[0], 'unknown')
        db.close()

    def test_batch_limit_and_tamper(self):
        plan = self.root / 'plan'
        pipeline.plan(self.index, plan, CLIENT, 'mock')
        path = plan / 'batch-00000.json'
        data = review.read(path)
        data['jobs'][0]['payload']['state']['memory']['text'] += 'changed'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            queue.load_batch(path, CLIENT)
        with self.assertRaises(ValueError):
            queue.dispatch({'jobs': []}, None, None, concurrency=501)

    def test_oversize_is_explicit(self):
        self.source.write_text('# Project\n- ' + 'large ' * 40000)
        index = self.root / 'large'
        pipeline.index(self.config, index)
        stats = pipeline.plan(index, self.root / 'large-plan', CLIENT, 'mock')
        self.assertEqual(stats['excluded']['oversized_score'], 1)
        result = pipeline.packets(index, self.root / 'large-packets')
        self.assertEqual(result['oversized'], 1)

    def test_cross_plan_cache_and_unknown_reuse(self):
        plan = self.root / 'plan'
        pipeline.plan(self.index, plan, CLIENT, 'mock')
        batch, client = queue.load_batch(plan / 'batch-00000.json', CLIENT)
        previous = plan / 'queue.sqlite'
        db = queue.connect(previous)
        queue.dispatch(batch, db, client, sender=lambda job: response(job['payload']))
        db.close()
        other = queue.connect(self.root / 'other.sqlite')
        self.assertEqual(queue.reuse_state(other, previous, batch, client), len(batch['jobs']))
        result = queue.dispatch(batch, other, client, sender=lambda job: self.fail('resent'))
        self.assertEqual(result['attempted'], 0)
        other.close()
        db = queue.connect(previous)
        db.execute("UPDATE jobs SET status='unknown' WHERE key=?", (batch['jobs'][0]['key'],))
        db.commit(); db.close()
        other = queue.connect(self.root / 'unknown.sqlite')
        queue.reuse_state(other, previous, batch, client)
        with self.assertRaises(ValueError):
            queue.dispatch(batch, other, client, sender=lambda job: self.fail('resent unknown'))
        other.close()

    def test_draft_missing_and_changed_coverage(self):
        db = pipeline.db_open(self.index)
        ident = db.execute("SELECT id FROM entries WHERE status='ready' LIMIT 1").fetchone()[0]
        db.close()
        candidate = self.root / 'candidate.json'
        candidate.write_text(json.dumps({'candidates': [{'id': 'one', 'source_ids': [ident], 'text': 'A draft.'}]}))
        plan = self.root / 'draft'
        stats = output.draft(self.index, candidate, plan, CLIENT, 'mock')
        self.assertGreater(stats['missing'], 0)
        output.report(plan, self.root / 'export', CLIENT)
        coverage = review.read(self.root / 'export/coverage.json')
        self.assertFalse(coverage['all_model_gates_passed'])
        self.assertFalse(coverage['all_sources_covered'])
        changed = review.read(plan / 'coverage.json')
        changed['candidates'][0]['text'] = 'An altered claim.'
        (plan / 'coverage.json').write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            output.report(plan, self.root / 'altered-export', CLIENT)

    def test_context_only_roles_preserve_provenance_without_rewriting_headings(self):
        db = pipeline.db_open(self.index)
        rows = db.execute('SELECT * FROM entries').fetchall()
        db.close()
        structural = [r['id'] for r in rows if r['status'] == 'structure']
        factual = [r['id'] for r in rows if r['status'] == 'ready']
        candidate = {'id': 'combined', 'source_ids': [r['id'] for r in rows],
                     'context_only_source_ids': structural,
                     'context_only_justification': 'Reviewed headings and source reference metadata.',
                     'text': 'Preserve token_id and the nested exception; keep source and timestamp.'}
        path = self.root / 'candidate-roles.json'
        path.write_text(json.dumps({'candidates': [candidate]}))
        plan = self.root / 'roles-plan'
        result = output.draft(self.index, path, plan, CLIENT, 'mock')
        self.assertEqual(result['missing'], 0)
        payload = review.read(plan / 'batch-00000.json')['jobs'][0]['payload']
        self.assertNotIn('# Task Group', payload['state']['original']['text'])
        self.assertIn('run.md', payload['state']['original']['context'])
        candidate['context_only_source_ids'] = structural + [factual[0]]
        path.write_text(json.dumps({'candidates': [candidate]}))
        with self.assertRaises(ValueError):
            output.draft(self.index, path, self.root / 'invalid-roles', CLIENT, 'mock')

    def test_1000_batch_boundary(self):
        self.source.write_text('# Project\n' + ''.join('- Unique memory number %d.\n' % i for i in range(1001)))
        root = self.root / 'many'
        pipeline.index(self.config, root)
        plan = self.root / 'many-plan'
        stats = pipeline.plan(root, plan, CLIENT, 'mock', top_k=0)
        self.assertEqual(stats['batches'], 2)
        self.assertEqual(len(review.read(plan / 'batch-00000.json')['jobs']), 1000)
        self.assertEqual(len(review.read(plan / 'batch-00001.json')['jobs']), 1)
        for batch in plan.glob('batch-*.json'):
            queue.load_batch(batch, CLIENT)

    def test_actual_500_inflight_offline(self):
        # A barrier makes every worker overlap; no API, credentials or private data.
        barrier = threading.Barrier(500, timeout=30)
        client = review.client_module(CLIENT)
        jobs = [{'key': str(i), 'payload': {'questions': {}}} for i in range(500)]
        db = queue.connect(self.root / '500.sqlite')
        def send(job):
            barrier.wait()
            return response(job['payload'])
        result = queue.dispatch({'jobs': jobs}, db, client, 500, sender=send)
        self.assertEqual(result['peak_inflight'], 500)
        self.assertEqual(result['status_counts'], {'completed': 500})
        db.close()


if __name__ == '__main__':
    unittest.main()
