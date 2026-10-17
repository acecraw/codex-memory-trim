#!/usr/bin/env python3
"""Prepare merged English draft verification, render advisory results and coverage."""
import argparse
import collections
import json
from pathlib import Path

import jev_review as review
import memory_pipeline as pipeline
import memory_queue as queue


def draft(index_root, candidate_path, output, client_path, epoch, byte_limit=16000):
    if not epoch.strip() or not 2000 <= byte_limit <= 32000:
        raise ValueError('Cache epoch and byte limit 2000..32000 required')
    db = pipeline.db_open(index_root)
    candidates = review.read(candidate_path)['candidates']
    root = Path(output)
    root.mkdir(mode=0o700)
    client, client_hash = review.client_module(client_path), pipeline.file_hash(client_path)
    jobs, batches, ids, covered, excluded = [], 0, set(), set(), []
    def flush():
        nonlocal jobs, batches
        if jobs:
            review.write_new(root / ('batch-%05d.json' % batches), {'version': pipeline.POLICY,
                'client_sha256': client_hash, 'cache_epoch': epoch, 'request_byte_limit': byte_limit, 'jobs': jobs})
            batches += 1
            jobs = []
    for candidate in candidates:
        ident = candidate['id']
        if ident in ids or not isinstance(ident, str) or not ident:
            raise ValueError('Candidate IDs must be unique nonempty strings')
        ids.add(ident)
        source_ids = candidate['source_ids']
        if not source_ids or len(source_ids) != len(set(source_ids)) or covered.intersection(source_ids):
            raise ValueError('Each source must belong to exactly one draft; overlapping coverage is ambiguous')
        rows = [db.execute('SELECT * FROM entries WHERE id=?', (sid,)).fetchone() for sid in source_ids]
        if any(row is None for row in rows):
            raise ValueError('Unknown source ID')
        if len(set(row['scope'] for row in rows)) != 1:
            raise ValueError('Cross-scope merge requires separate drafts')
        context_ids = candidate.get('context_only_source_ids', [])
        if len(context_ids) != len(set(context_ids)) or set(context_ids) - set(source_ids):
            raise ValueError('Context-only IDs must be a unique subset of source IDs')
        if context_ids and not candidate.get('context_only_justification', '').strip():
            raise ValueError('Context-only source roles require a reviewed justification')
        if any(row['id'] in context_ids and row['status'] != 'structure' for row in rows):
            raise ValueError('Factual memory entries cannot be marked context-only')
        content_rows = [row for row in rows if row['id'] not in context_ids]
        if not content_rows:
            raise ValueError('A draft needs at least one content source')
        covered.update(source_ids)
        original = {'id': review.digest(ident.encode())[:32],
            'text': '\n\n'.join(row['body'] for row in content_rows), 'scope': rows[0]['scope'],
            'context': '\n\n'.join(dict.fromkeys(pipeline.entry(row, db)['context'] for row in rows)),
            'source': '\n'.join(pipeline.entry(row)['source'] for row in rows),
            'protected': True, 'protected_literals': sorted(set(v for row in content_rows for v in json.loads(row['literals'])))}
        c = {'entry': original['id'], 'text': candidate['text'], 'retained_terms': candidate.get('retained_terms', []),
             'term_justification': candidate.get('term_justification', '')}
        job = review.build_jobs({'entries': [original], 'candidates': [c]}, client, only=['verify'], request_limit=None)[0]
        job['metadata'].update(candidate_id=ident, source_ids=source_ids,
                               sources=[pipeline.entry(row)['source'] for row in rows],
                               context_only_source_ids=context_ids,
                               context_only_justification=candidate.get('context_only_justification', ''),
                               scope_known=original['scope'] != 'unknown')
        job['payload']['state']['unit_ids'] = source_ids
        job['payload']['state']['applicable_rules'] = pipeline.rule_packet(db, original['scope'])
        job['payload']['questions']['preserves_meaning']['instructions'] += ' Original contains multiple source units: verify every source, including contradictory or historical facts. Do not silently resolve a conflict.'
        job['payload']['questions']['rule_conflict'] = {'type': 'noul', 'instructions': 'Does candidate present a claim conflicting with the supplied current rules as an instruction to follow? An explicitly labelled historical record is not an active instruction.'}
        job['key'] = queue.job_key(job['payload'], client_hash, epoch, job['metadata'])
        if queue.payload_bytes(job['payload']) > byte_limit:
            excluded.append({'candidate_id': ident, 'source_ids': source_ids, 'reason': 'request_byte_budget'})
        else:
            jobs.append(job)
            if len(jobs) == 1000:
                flush()
    flush()
    missing = [row[0] for row in db.execute('SELECT id FROM entries') if row[0] not in covered]
    coverage = {'version': pipeline.POLICY, 'batches': batches, 'candidates': candidates,
        'missing_source_ids': missing, 'excluded': excluded, 'all_sources_covered': not missing,
        'index_sha256': pipeline.file_hash(Path(index_root) / 'index.sqlite'),
        'inference_sent': False, 'native_memory_changed': False}
    review.write_new(root / 'coverage.json', coverage)
    review.write_new(root / 'draft-manifest.json', {'coverage_sha256': pipeline.file_hash(root / 'coverage.json'),
        'batch_sha256': {p.name: pipeline.file_hash(p) for p in sorted(root.glob('batch-*.json'))}})
    db.close()
    return {k: v for k, v in coverage.items() if k not in ('candidates', 'missing_source_ids', 'excluded')} | {'missing': len(missing), 'excluded': len(excluded)}


def report(plan_root, output, client_path):
    root, out = Path(plan_root).resolve(), Path(output)
    manifest = review.read(root / ('draft-manifest.json' if (root / 'coverage.json').exists() else 'plan.json'))
    actual_batches = {p.name: pipeline.file_hash(p) for p in sorted(root.glob('batch-*.json'))}
    if actual_batches != manifest['batch_sha256']:
        raise ValueError('Batch files changed or missing')
    if 'coverage_sha256' in manifest and pipeline.file_hash(root / 'coverage.json') != manifest['coverage_sha256']:
        raise ValueError('Draft coverage changed after planning')
    out.mkdir(mode=0o700)
    state = root / 'queue.sqlite'
    db = None
    if state.exists():
        import sqlite3
        db = sqlite3.connect(state.as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
    results, statuses, usage, model_counts = [], collections.Counter(), collections.Counter(), collections.Counter()
    for path in sorted(root.glob('batch-*.json')):
        batch, client = queue.load_batch(path, client_path)
        for job in batch['jobs']:
            row = db.execute('SELECT * FROM jobs WHERE key=?', (job['key'],)).fetchone() if db else None
            status = row['status'] if row else 'pending'
            result = {'key': job['key'], 'kind': job['kind'], 'metadata': job['metadata'], 'status': status}
            if status == 'completed':
                response = json.loads(row['response'])
                client.validate_response(response, job['payload'])
                answers = response['answers']
                review.strict_answer_check(answers, job['payload']['questions'])
                result['answers'] = answers
                result['model'], result['usage'] = response['model'], response['usage']
                model_counts[response['model']] += 1
                for key, value in response['usage'].items():
                    if isinstance(value, (int, float)):
                        usage[key] += value
                if job['kind'] == 'score':
                    result['value'] = review.score_result({'protected': True}, answers)
                    # A score is advisory; conflicts/uncertainty take priority.
                    result['requires_review'] = (answers['rule_conflict']['noul'] > .05 or
                                                answers['current_validity']['choice'] != 'current' or
                                                answers['current_validity']['probabilities']['current'] < .95 or
                                                result['value']['uncertain'])
                elif job['kind'] == 'pair':
                    result['merge_candidate'] = (answers['relation']['choice'] == 'equivalent' and
                        answers['relation']['probabilities']['equivalent'] >= .95 and answers['same_scope']['noul'] >= .95 and
                        answers['a_unique']['noul'] <= .05 and answers['b_unique']['noul'] <= .05)
                else:
                    checks = job['metadata']['checks']
                    result['gate_passed'] = (all(answers[k]['noul'] >= .95 for k in ('preserves_meaning', 'no_new_claims', 'english_output')) and
                        answers['rule_conflict']['noul'] <= .05 and not checks['missing_literals'] and
                        not checks['unapproved_chinese'] and job['metadata']['scope_known'])
            statuses[status] += 1
            results.append(result)
    if db:
        db.close()
    # Surface semantic conflicts with their source entries; never hide under value score.
    conflict_ids = set()
    for result in results:
        if result['kind'] == 'pair' and result.get('answers', {}).get('relation', {}).get('choice') == 'conflict':
            conflict_ids.update((result['metadata']['a'], result['metadata']['b']))
    for result in results:
        if result['kind'] == 'score' and result['metadata']['entry'] in conflict_ids:
            result['requires_review'] = True
            result['conflict_detected'] = True
    summary = {'status_counts': dict(statuses), 'usage': dict(usage), 'models': dict(model_counts),
               'actual_cost': 'unknown', 'native_memory_changed': False,
               'plan_coverage': {k: manifest[k] for k in ('entry_states', 'excluded', 'dedup_recall') if k in manifest},
               'usage_includes_reused_results': True, 'results': results}
    review.write_new(out / 'report.json', summary)
    coverage_path = root / 'coverage.json'
    if coverage_path.exists():
        coverage = review.read(coverage_path)
        by_id = {r['metadata']['candidate_id']: r for r in results if r['kind'] == 'verify'}
        lines = ['# English memory draft', '', 'Advisory draft. Native memory has not been changed.', '']
        accepted = 0
        ledger = []
        for c in coverage['candidates']:
            result = by_id.get(c['id'], {})
            passed = bool(result.get('gate_passed'))
            accepted += passed
            label = 'MODEL GATE PASSED — human review required' if passed else 'REVIEW REQUIRED'
            lines += ['## ' + c['id'], '', '**' + label + '**', '', c['text'], '',
                      'Source IDs: ' + ', '.join(c['source_ids']), '']
            ledger.append({'candidate_id': c['id'], 'source_ids': c['source_ids'], 'gate_passed': passed,
                           'sources': result.get('metadata', {}).get('sources', []),
                           'context_only_source_ids': c.get('context_only_source_ids', [])})
        review.write_new(out / 'MEMORY.candidate.md', '\n'.join(lines))
        review.write_new(out / 'coverage.json', {'entries': ledger, 'missing_source_ids': coverage['missing_source_ids'],
            'excluded': coverage['excluded'], 'all_sources_covered': coverage['all_sources_covered'],
            'all_model_gates_passed': accepted == len(coverage['candidates']) and bool(accepted),
            'native_memory_changed': False})
    review.write_new(out / 'report.md', '# Memory review\n\n' + json.dumps({k: v for k, v in summary.items() if k != 'results'}, indent=2) + '\n\nSee report.json for per-entry evidence. Scores never authorize deletion.\n')
    return {k: v for k, v in summary.items() if k != 'results'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('draft'); p.add_argument('--index', required=True); p.add_argument('--candidates', required=True)
    p.add_argument('--output', required=True); p.add_argument('--client', required=True); p.add_argument('--cache-epoch', required=True)
    p.add_argument('--request-byte-limit', type=int, default=16000)
    p = sub.add_parser('report'); p.add_argument('--plan', required=True); p.add_argument('--output', required=True); p.add_argument('--client', required=True)
    args = parser.parse_args()
    if args.command == 'draft': result = draft(args.index, args.candidates, args.output, args.client, args.cache_epoch, args.request_byte_limit)
    else: result = report(args.plan, args.output, args.client)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
