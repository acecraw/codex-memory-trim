# Compact retrieval proposals

After V3 annotation and conservative merging, a second editorial pass produces
short topic briefs. The main index groups them by their original project scope.
Each brief links to bounded English detail files and the original task context.
This is a review bundle, not an installed Codex memory format or a replacement
for native consolidation.

## What is compressed

- Long request quotations become concise, scoped guidance.
- Related guidance is summarized within the same project and topic.
- Historical outcomes are explicitly separated from reusable guidance.
- Full candidate text, identifiers, limits, authorization conditions, original
  metadata, keywords, and evidence references remain available behind links.
- Topics missed by the earlier bullet extractor receive original-source links;
  they are not silently omitted.

The smaller index reduces text needed to locate a topic. It does **not** imply
that the complete archive shrank, that all details fit in the index, or that a
Codex session currently loads the whole original file. Do not report index byte
reduction as measured token savings or runtime performance improvement.

## Inputs and editorial contract

The exporter consumes the frozen full-run `input.json`, `candidates.json`, verified
`backup/memories/MEMORY.md`, and a `compression-v2/manifest.json`. The manifest
pins both JSON hashes and partitions candidate/source IDs into same-scope groups.
Each group names its worker, original headings, source IDs, and candidate IDs.

Worker `briefs.json` files pin the manifest hash and contain exactly their assigned
groups. Each brief has an English `title`, 4–10 `keywords`, `rules` and `status`
lists, and optional `retained_terms` with `term_justification`. Each rule/status
item has `text` and supporting `source_ids` from its own group. Briefs need not
repeat every source: complete coverage is enforced in the detail layer.

Use concise human/agent synthesis, not sentence truncation. Do not infer current
permission from old approvals, turn a single request into a standing preference,
or promote a historical observation to current fact. Conflicting versions require
source inspection; a later timestamp alone does not settle them.

## Export and source lookup

```sh
python3 skill/scripts/memory_compact.py export \
  --run .local/full-memory/RUN \
  --output .local/full-memory/RUN/compression-v2/export

python3 skill/scripts/memory_compact.py lookup \
  --bundle .local/full-memory/RUN/compression-v2/export \
  --source-id mem-0001
```

The output directory must be new. The exporter performs no network calls and
never applies memory changes. It rejects the native memory directory as a target.
All real memory artifacts belong under ignored `.local/`.

Outputs:

- `MEMORY.compact.md`: project/topic retrieval index.
- `details/*.md`: complete first-pass English candidates, at most 16,000 bytes
  per file by default. Entries are not cut mid-record.
- `source/groups/*.md`: exact original task-group text in bounded pieces.
- `source/MEMORY.original.md`: complete original snapshot, including metadata.
- `source/input.json` and `source/candidates.json`: exact frozen input copies.
- `catalog.json`: briefs, claim sources, and links.
- `coverage.json`: every source ID mapped to one candidate and detail file.
- `metrics.json`: index/detail sizes and coverage, with explicit limitations.

Primary review must address unsupported claims, scope, permission and temporal
changes. Mechanical coverage and literal checks establish traceability, not
semantic accuracy. Native adoption is a separate compatibility and authorization
decision; do not copy the index over native memory without its dependencies.

## Read-only retrieval entrypoint

```sh
python3 skill/scripts/memory_compact.py search \
  --bundle .local/full-memory/RUN/compression-v2/export \
  --query 'Jev router' --limit 5
```

Use `--scope` with the exact project scope to restrict results. Output contains
ranked topic titles and absolute detail/source paths, not the entire index.
Ranking is literal, case-insensitive keyword matching, not semantic confidence;
English query terms work best with the English briefs. No automatic translation
or API calls occur. No-match queries must fall back to original context, including
the topic missed by the initial extractor. Read details one bounded file at a time.
The snapshot does not include later native memory updates.

## Native compatibility decision (2026-09-25)

The official [Memories documentation](https://learn.chatgpt.com/docs/customization/memories)
describes local memory files as generated state and advises against relying on
manual edits as the primary control surface. It recommends AGENTS.md or checked-in
documentation for required guidance. The documented configuration options do not
establish a supported importer for this bundle.

Therefore this tool is an explicitly invoked, read-only supplementary archive.
It does not replace MEMORY.md, change memory configuration, edit SQLite, or
install a global routing rule. The current session's supplied memory instructions
already use summary -> search -> evidence retrieval; archive size alone does not
establish per-session context consumption. Future automatic discovery requires a
separately reviewed routing instruction and verification in a fresh task. Do not
claim native adoption or measured token savings from this command.
