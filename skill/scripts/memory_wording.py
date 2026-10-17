#!/usr/bin/env python3
"""Assemble reviewed per-entry wording into the original MEMORY.md layout.

Writes a local proposal only. Never writes native memory, configuration or SQLite.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def protected(text):
    return set(re.findall(r'`[^`\n]+`|\[Task [^\]]+\]|\[(?:ad-hoc note|skysight memory|chronicle memory)\]', text))


def assemble(run, replacements, output, native):
    run, replacements, output, native = map(lambda p: Path(p).resolve(),
                                            (run, replacements, output, native))
    forbidden = {(Path.home() / '.codex/memories').resolve(), native.parent,
                 (Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'memories').resolve()}
    if any(output == p or p in output.parents for p in forbidden):
        raise ValueError('Native memory cannot be an output destination')
    raw = (run / 'backup/memories/MEMORY.md').read_bytes()
    expected = next(f['sha256'] for f in read(run / 'backup-manifest.json')['files']
                    if f['path'] == 'MEMORY.md')
    if sha(raw) != expected or native.read_bytes() != raw:
        raise ValueError('Snapshot or live memory changed; rebase before assembly')
    original = raw.decode('utf-8')
    lines = original.splitlines(keepends=True)
    entries = read(run / 'input.json')
    proposals = {}
    for path in sorted(replacements.glob('worker-*/replacements.json')):
        rows = read(path)['entries']
        assigned = set(read(path.parent / 'assignment.json')['source_ids'])
        if {r['id'] for r in rows} != assigned or len(rows) != len(assigned):
            raise ValueError('Incomplete or duplicate worker coverage: ' + str(path))
        for row in rows:
            if row['id'] in proposals:
                raise ValueError('Overlapping worker ownership')
            proposals[row['id']] = row['text']
    if set(proposals) != {e['id'] for e in entries}:
        raise ValueError('Source coverage is incomplete')
    edits, findings, spans = [], [], []
    for entry in entries:
        match = re.search(r':(\d+)-(\d+)$', entry['source'])
        if not match:
            raise ValueError('Invalid source range')
        start, end = map(int, match.groups())
        old = ''.join(lines[start - 1:end])
        if old != entry['text']:
            raise ValueError('Source range mismatch: ' + entry['id'])
        new = proposals[entry['id']]
        if '[ad-hoc note]' in old:
            if new != old:
                findings.append({'id': entry['id'], 'error': 'ad_hoc_changed'})
        elif not new.strip().startswith('- ') or re.search(r'^#', new, re.M):
            findings.append({'id': entry['id'], 'error': 'invalid_entry_structure'})
        missing = sorted(protected(old) - protected(new))
        if missing:
            findings.append({'id': entry['id'], 'error': 'protected_literals_missing', 'values': missing})
        # Number flags are review evidence, not an automatic semantic verdict.
        numbers = lambda s: set(re.findall(r'\d+(?:[.,:/-]\d+)*', s))
        changed_numbers = sorted(numbers(old) - numbers(new))
        if changed_numbers:
            findings.append({'id': entry['id'], 'error': 'numbers_need_review', 'values': changed_numbers})
        replacement = new.rstrip() + re.search(r'\n*$', old).group()
        if new.strip() == old.strip() or '[ad-hoc note]' in old:
            replacement = old
        spans.append((start, end, replacement))
        if replacement != old:
            edits.append({'id': entry['id'], 'source': entry['source'],
                          'bytes_before': len(old.encode()), 'bytes_after': len(replacement.encode())})
    previous_end = 0
    for start, end, _ in sorted(spans):
        if start <= previous_end or end < start:
            raise ValueError('Overlapping or invalid source spans')
        previous_end = end
    for start, end, replacement in sorted(spans, reverse=True):
        lines[start - 1:end] = [replacement]
    candidate = ''.join(lines)
    if re.findall(r'^#{1,6} .+$', original, re.M) != re.findall(r'^#{1,6} .+$', candidate, re.M):
        raise ValueError('Heading structure changed')
    if native.read_bytes() != raw:
        raise ValueError('Native changed during assembly')
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = {'source_sha256': sha(raw), 'candidate_sha256': sha(candidate.encode()),
              'source_bytes': len(raw), 'candidate_bytes': len(candidate.encode()),
              'byte_reduction_percent': round(100 * (1 - len(candidate.encode()) / len(raw)), 2),
              'source_entries': len(entries), 'changed_entries': len(edits),
              'unchanged_outside_entry_spans': True, 'native_applied': False,
              'findings': findings, 'edits': edits,
              'status': 'Review proposal only; mechanical checks do not establish semantic equivalence.'}
    artifacts = {'MEMORY.compressed.md': candidate,
                 'MEMORY.original.md': original,
                 'MEMORY.diff': ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                                           fromfile='MEMORY.original.md', tofile='MEMORY.compressed.md')),
                 'report.json': json.dumps(report, ensure_ascii=False, indent=2) + '\n'}
    for name, text in artifacts.items():
        (output / name).write_text(text)
        (output / name).chmod(0o600)
    return {k: v for k, v in report.items() if k not in ('findings', 'edits')} | {'finding_count': len(findings)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--replacements', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--native', default=str(Path.home() / '.codex/memories/MEMORY.md'))
    args = parser.parse_args()
    print(json.dumps(assemble(args.run, args.replacements, args.output, args.native), indent=2))
