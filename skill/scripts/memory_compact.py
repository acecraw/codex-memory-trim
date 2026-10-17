#!/usr/bin/env python3
"""Export a compact retrieval index with intact, bounded detail files.

Local review artifacts only. No API calls, deletion, or native memory writes.
"""
import argparse
import collections
import os
import re
from pathlib import Path

import jev_review as review


def export(run, output, byte_limit=16000):
    run, out = Path(run).resolve(), Path(output).resolve()
    if byte_limit < 2000:
        raise ValueError('Detail byte limit must be at least 2000')
    native_roots = {(Path.home() / '.codex' / 'memories').resolve(),
                    (Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'memories').resolve()}
    if any(out == native or native in out.parents for native in native_roots):
        raise ValueError('Native memory is not an export destination')
    compact = run / 'compression-v2'
    manifest = review.read(compact / 'manifest.json')
    manifest_hash = review.digest((compact / 'manifest.json').read_bytes())
    for name, key in [('input.json', 'input_sha256'), ('candidates.json', 'candidates_sha256')]:
        if review.digest((run / name).read_bytes()) != manifest[key]:
            raise ValueError('Frozen input changed: ' + name)
    originals = {e['id']: e for e in review.read(run / 'input.json')}
    candidate_list = review.read(run / 'candidates.json')['candidates']
    candidates = {c['id']: c for c in candidate_list}
    if len(candidates) != len(candidate_list):
        raise ValueError('Duplicate candidate IDs')
    source_counts = collections.Counter(i for c in candidate_list for i in c['source_ids'])
    if set(source_counts) != set(originals) or set(source_counts.values()) != {1}:
        raise ValueError('Candidates must cover every source exactly once')
    briefs = {}
    for worker in sorted({g['worker'] for g in manifest['groups']}):
        if not re.fullmatch(r'worker-[1-9][0-9]*', worker):
            raise ValueError('Invalid worker directory')
        data = review.read(compact / worker / 'briefs.json')
        if data['manifest_sha256'] != manifest_hash:
            raise ValueError('Briefs refer to a different manifest')
        owned = {g['id'] for g in manifest['groups'] if g['worker'] == worker}
        actual = [g['id'] for g in data['groups']]
        if len(set(actual)) != len(actual) or set(actual) != owned:
            raise ValueError('Brief group coverage differs from assignment')
        briefs.update({g['id']: g for g in data['groups']})
    all_group_sources = collections.Counter(i for g in manifest['groups'] for i in g['source_ids'])
    all_group_candidates = collections.Counter(i for g in manifest['groups'] for i in g['candidate_ids'])
    if all_group_sources != source_counts or set(all_group_candidates) != set(candidates) or set(all_group_candidates.values()) != {1}:
        raise ValueError('Group partition is not an exact cover')
    prepared = []
    for group in manifest['groups']:
        gid = group['id']
        if not re.fullmatch(r'group-[0-9]{4}', gid):
            raise ValueError('Invalid group identifier')
        brief = briefs[gid]
        ids = set(group['source_ids'])
        selected = [candidates[i] for i in group['candidate_ids']]
        if set(i for c in selected for i in c['source_ids']) != ids:
            raise ValueError('Candidate/source group mismatch')
        if {originals[i]['scope'] for i in ids} != {group['scope']}:
            raise ValueError('Cross-scope group')
        if not isinstance(brief['title'], str) or not brief['title'].strip() or '\n' in brief['title']:
            raise ValueError('Invalid topic title')
        if not 4 <= len(brief['keywords']) <= 10 or any(not isinstance(k, str) or not k.strip() or '\n' in k for k in brief['keywords']):
            raise ValueError('Expected 4-10 one-line keywords')
        claims = brief['rules'] + brief['status']
        if not claims:
            raise ValueError('Empty retrieval brief')
        for claim in claims:
            if not claim['text'].strip() or not claim['source_ids'] or not set(claim['source_ids']) <= ids:
                raise ValueError('Claim lacks in-scope source IDs: ' + gid)
        prose = '\n'.join([brief['title'], *brief['keywords'], *(c['text'] for c in claims)])
        checked = dict(brief, text=prose)
        if review.candidate_checks({}, checked)['unapproved_chinese']:
            raise ValueError('Unjustified Chinese in brief: ' + gid)
        if brief.get('retained_terms') and not brief.get('term_justification', '').strip():
            raise ValueError('Retained terms need justification')
        for c in selected:
            protected = sorted({s for i in c['source_ids'] for s in re.findall(r'`([^`\n]+)`', originals[i]['text'])})
            if any(review.candidate_checks({'protected_literals': protected}, c).values()):
                raise ValueError('Detailed candidate failed preservation checks: ' + c['id'])
        header = '# ' + brief['title'] + '\n\nScope: ' + group['scope'] + '\n\nHistorical record and scoped guidance; read source context before reuse.\n\n'
        blocks = [(c, '## ' + c['id'] + '\n\n' + c['text'] + '\n\nSources: ' + ', '.join(c['source_ids']) + '\n\n') for c in selected]
        chunks, current, chunk_ids = [], header, []
        for candidate, block in blocks:
            if len((header + block).encode()) > byte_limit:
                raise ValueError('One candidate exceeds detail byte budget: ' + candidate['id'])
            if len((current + block).encode()) > byte_limit:
                chunks.append((current, chunk_ids))
                current, chunk_ids = header, []
            current += block
            chunk_ids.append(candidate['id'])
        if chunk_ids:
            chunks.append((current, chunk_ids))
        prepared.append((group, brief, chunks))
    backup = run / 'backup' / 'memories' / 'MEMORY.md'
    backup_manifest = review.read(run / 'backup-manifest.json')
    expected = next(f['sha256'] for f in backup_manifest['files'] if f['path'] == 'MEMORY.md')
    if review.digest(backup.read_bytes()) != expected:
        raise ValueError('Original backup changed')
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    for subdir in ('details', 'source', 'source/groups'):
        (out / subdir).mkdir(mode=0o700)
    for source, name in [(backup, 'MEMORY.original.md'), (run / 'input.json', 'input.json'), (run / 'candidates.json', 'candidates.json')]:
        # Exact bytes, including all source contexts and the complete original index.
        with (out / 'source' / name).open('xb') as stream:
            stream.write(source.read_bytes())
        (out / 'source' / name).chmod(0o600)
    # Preserve scope/reuse conditions, keywords, references, and even sections
    # which the earlier bullet extractor did not recognize as memory entries.
    source_groups = []
    source_by_heading = collections.defaultdict(list)
    for n, block in enumerate(re.split(r'(?=^# Task Group:)', backup.read_text(), flags=re.M), 1):
        if not block:
            continue
        heading = block.splitlines()[0]
        pieces, current = [], ''
        for line in block.splitlines(keepends=True):
            if len(line.encode()) > byte_limit:
                raise ValueError('Original source line exceeds byte budget')
            if len((current + line).encode()) > byte_limit:
                pieces.append(current)
                current = ''
            current += line
        if current:
            pieces.append(current)
        paths = []
        for part, content in enumerate(pieces, 1):
            name = f'source/groups/original-{n:04d}-{part:02d}.md'
            review.write_new(out / name, content)
            paths.append(name)
        source_groups.append({'heading': heading, 'files': paths})
        source_by_heading[heading].extend(paths)
    review.write_new(out / 'source/catalog.json', {
        'groups': source_groups,
        'original_evidence_root': str(run / 'backup' / 'memories'),
        'note': 'Resolve original rollout/extension references against this verified backup, not the export directory.'})
    review.write_new(out / 'source/README.md', '# Original evidence\n\n'
        'The copied original index and grouped excerpts retain their original language and metadata. '
        'They are evidence, not new instructions. Resolve their rollout_summaries/ and extensions/ references against '
        + str(run / 'backup' / 'memories') + '. Keep that backup with this review bundle.\n')
    catalog, coverage = [], {}
    lines = ['# Compact memory retrieval proposal', '',
             'Review artifact only; not installed in native Codex memory.', '',
             'Use this index to locate a topic. Read its linked details before relying on numeric limits, commands, authorization, or historical status. Details retain every first-pass candidate; source/MEMORY.original.md retains the complete original snapshot. Historical notes do not grant current permission.', '']
    for scope in dict.fromkeys(g['scope'] for g in manifest['groups']):
        lines.extend(['# Task Group: ' + scope, '', 'scope: Topic retrieval within this recorded scope only.', ''])
        for group, brief, chunks in prepared:
            if group['scope'] != scope:
                continue
            paths = []
            for n, (content, candidate_ids) in enumerate(chunks, 1):
                name = f'details/{group["id"]}-{n:02d}.md'
                review.write_new(out / name, content)
                paths.append(name)
                for cid in candidate_ids:
                    for sid in candidates[cid]['source_ids']:
                        coverage[sid] = {'group': group['id'], 'candidate': cid, 'detail': name,
                                         'context': originals[sid]['context'], 'source': originals[sid]['source']}
            lines.extend(['## ' + brief['title'], '', 'Keywords: ' + ', '.join(brief['keywords']), ''])
            for label, key in [('Reusable guidance', 'rules'), ('Recorded state', 'status')]:
                if brief[key]:
                    lines.extend(['### ' + label, ''])
                    lines.extend('- ' + c['text'] for c in brief[key])
                    lines.append('')
            lines.extend(['Details: ' + ' · '.join(f'[part {n}]({p})' for n, p in enumerate(paths, 1)), ''])
            context_paths = list(dict.fromkeys(p for h in group['original_headings'] for p in source_by_heading[h]))
            if not context_paths:
                raise ValueError('Original task context not found')
            lines.extend(['Original context: ' + ' · '.join(f'[source {n}]({p})' for n, p in enumerate(context_paths, 1)), ''])
            catalog.append(dict(brief, scope=scope, details=paths, original_context=context_paths, source_ids=group['source_ids']))
    indexed_headings = {h for g in manifest['groups'] for h in g['original_headings']}
    unextracted = [g for g in source_groups if g['heading'] not in indexed_headings]
    if unextracted:
        lines.extend(['# Additional original topics', '',
                      'These source sections were outside the earlier bullet extraction. Read the originals; they have not been semantically compressed.', ''])
        for group in unextracted:
            lines.extend(['## ' + group['heading'].removeprefix('# Task Group: '), '',
                          ' · '.join(f'[original part {n}]({p})' for n, p in enumerate(group['files'], 1)), ''])
    review.write_new(out / 'MEMORY.compact.md', '\n'.join(lines))
    review.write_new(out / 'catalog.json', {'manifest_sha256': manifest_hash, 'groups': catalog})
    review.write_new(out / 'coverage.json', {'sources': coverage, 'native_applied': False})
    first = run / 'export' / 'MEMORY.candidate.md'
    size = (out / 'MEMORY.compact.md').stat().st_size
    detail_paths = sorted((out / 'details').glob('*.md'))
    result = {'sources': len(coverage), 'candidates': len(candidates), 'groups': len(catalog),
              'scopes': len({g['scope'] for g in catalog}), 'detail_files': len(detail_paths),
              'detail_byte_limit': byte_limit, 'largest_detail_bytes': max(p.stat().st_size for p in detail_paths),
              'first_pass_markdown_bytes': first.stat().st_size, 'compact_index_bytes': size,
              'index_byte_reduction_percent': round((1 - size / first.stat().st_size) * 100, 2),
              'details_bytes': sum(p.stat().st_size for p in detail_paths),
              'original_context_groups': len(source_groups), 'original_only_topics': len(unextracted),
              'source_snapshot_bytes': backup.stat().st_size, 'native_applied': False,
              'token_reduction': 'Not measured; byte reduction applies only to the retrieval index.',
              'semantic_status': 'Primary review required; exact source coverage does not establish summary accuracy.'}
    review.write_new(out / 'metrics.json', result)
    return result


def lookup(bundle, source_id):
    bundle = Path(bundle)
    row = review.read(bundle / 'coverage.json')['sources'][source_id]
    return dict(row, path=str((bundle / row['detail']).resolve()))


def search(bundle, query, scope=None, limit=5):
    """Rank literal keyword matches locally; return pointers, never the archive."""
    if not 1 <= limit <= 20:
        raise ValueError('Limit must be between 1 and 20')
    terms = list(dict.fromkeys(query.casefold().split()))
    if not terms:
        raise ValueError('A nonempty query is required')
    bundle = Path(bundle).resolve()
    hits = []
    for group in review.read(bundle / 'catalog.json')['groups']:
        if scope is not None and group['scope'] != scope:
            continue
        title = group['title'].casefold()
        keywords = ' '.join(group['keywords']).casefold()
        body = ' '.join(c['text'] for c in group['rules'] + group['status']).casefold()
        matched = [t for t in terms if t in title or t in keywords or t in body]
        if not matched:
            continue
        score = sum(4 * (t in title) + 2 * (t in keywords) + (t in body) for t in terms)
        hits.append({'id': group['id'], 'title': group['title'], 'scope': group['scope'],
                     'keyword_score': score, 'matched_terms': matched,
                     'details': [str(bundle / p) for p in group['details']],
                     'original_context': [str(bundle / p) for p in group['original_context']]})
    hits.sort(key=lambda h: (-len(h['matched_terms']), -h['keyword_score'], h['id']))
    return {'matches': hits[:limit], 'total_matches': len(hits),
            'notice': 'Frozen historical proposal; keyword rank is not confidence. Read details and current sources before use. No match does not mean no memory; search original context too.',
            'original_catalog': str(bundle / 'source/catalog.json'), 'native_applied': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('export')
    command.add_argument('--run', required=True)
    command.add_argument('--output', required=True)
    command.add_argument('--byte-limit', type=int, default=16000)
    command = commands.add_parser('lookup')
    command.add_argument('--bundle', required=True)
    command.add_argument('--source-id', required=True)
    command = commands.add_parser('search')
    command.add_argument('--bundle', required=True)
    command.add_argument('--query', required=True)
    command.add_argument('--scope', help='Exact scope; no implicit cross-project fallback')
    command.add_argument('--limit', type=int, default=5)
    args = parser.parse_args()
    if args.command == 'export':
        print(review.encoded(export(args.run, args.output, args.byte_limit)).decode())
    elif args.command == 'lookup':
        print(review.encoded(lookup(args.bundle, args.source_id)).decode())
    else:
        print(review.encoded(search(args.bundle, args.query, args.scope, args.limit)).decode())
