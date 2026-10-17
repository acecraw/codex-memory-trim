#!/usr/bin/env python3
"""Export reviewed English proposals; never apply them to native memory."""
import argparse
import collections
import re
from pathlib import Path

import jev_review as review


def export(input_path, candidates_path, output):
    raw = Path(input_path).read_bytes()
    entries = review.read(input_path)
    sources = {e['id']: e for e in entries}
    if len(sources) != len(entries):
        raise ValueError('Duplicate source IDs')
    proposal = review.read(candidates_path)
    if proposal['input_sha256'] != review.digest(raw):
        raise ValueError('Source snapshot changed')
    counts = collections.Counter()
    rows = []
    ids = set()
    for c in proposal['candidates']:
        if c['id'] in ids or not c['text'].strip() or not c['source_ids']:
            raise ValueError('Invalid candidate')
        ids.add(c['id'])
        if len(set(c['source_ids'])) != len(c['source_ids']):
            raise ValueError('Repeated source in candidate')
        original = [sources[s] for s in c['source_ids']]
        if len({s['scope'] for s in original}) != 1:
            raise ValueError('Cross-scope merge')
        counts.update(c['source_ids'])
        literals = sorted(set(v for s in original for v in re.findall(r'`([^`\n]+)`', s['text'])))
        checks = review.candidate_checks({'protected_literals': literals}, c)
        if any(checks.values()):
            raise ValueError('Candidate %s failed literal/language checks: %s' % (c['id'], checks))
        if c.get('retained_terms') and not c.get('term_justification', '').strip():
            raise ValueError('Chinese precision justification required')
        rows.append(dict(c, scope=original[0]['scope'], sources=[s['source'] for s in original],
                         source_contexts=[{'id': s['id'], 'context': s.get('context', '')} for s in original],
                         mechanical_checks=checks, semantic_status='requires_primary_review'))
    if set(counts) != set(sources) or any(n != 1 for n in counts.values()):
        raise ValueError('Every source must be covered exactly once')
    out = Path(output)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    review.write_new(out / 'coverage.json', {'input_sha256': review.digest(raw), 'source_count': len(sources),
        'candidate_count': len(rows), 'candidates': rows, 'native_applied': False,
        'warning': 'Mechanical coverage does not establish semantic preservation.'})
    lines = ['# Memory compression proposal', '', 'Review artifact; not applied to native memory.', '']
    for scope in dict.fromkeys(r['scope'] for r in rows):
        lines += ['## ' + scope, '']
        scoped = [r for r in rows if r['scope'] == scope]
        for heading in dict.fromkeys(r.get('context_heading', '') for r in scoped):
            if heading:
                lines += ['### ' + heading.replace('\n', ' '), '']
            for row in scoped:
                if row.get('context_heading', '') != heading:
                    continue
                lines += [row['text'].strip(), '', '<!-- Sources: ' + ', '.join(row['source_ids']) + ' -->', '']
    path = out / 'MEMORY.candidate.md'
    with path.open('x', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    path.chmod(0o600)
    return {'sources': len(sources), 'candidates': len(rows), 'native_applied': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--candidates', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(export(args.input, args.candidates, args.output))
