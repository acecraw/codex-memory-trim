# Memory pipeline V2

This project now includes a disk-backed review and draft-export pipeline. It never
writes native Codex memory or its database. The original automatic trim workflow
is separate and does not invoke this pipeline. Run these commands from the
repository using Python 3.9+; no new packages are needed.

See [the real 100-memory evaluation](REAL100_EVALUATION.md) before using model
gates for decisions: the flow completed, but the current gates rejected every
positive candidate and are not validated for automatic replacement.

## Limits and semantics

- **500 concurrent requests by default and maximum**, local to this project.
  Each frozen batch has **at most 1,000 requests**. Multiple batches run sequentially.
  The shared TypeSafe Skill remains at 100 concurrent requests.
- 500 concurrent mock requests have been exercised locally. This is not a live
  Jev capacity result; only the previously documented 100-request burst was live.
- Each request has a default 16,000 UTF-8 byte ceiling, configurable up to 32,000.
  This is a conservative payload-size guard, not an exact tokenizer measurement.
  Requests include questions and selected rules. Oversized work is recorded,
  never silently truncated. Agent packets default to 32,000 serialized bytes.
- Sources are frozen on disk and indexed in a separate SQLite database. Python
  streams source files; no agent receives the full memory corpus.
- Markdown is partitioned losslessly at headings and top-level bullets. Nested
  lists and fenced code stay intact. Structural content and references remain
  in the index, provenance and work packets. Unsupported prose remains structural
  content; it is not independently scored.
- Project scope must come from explicit source/group configuration. Unknown scope
  stays in review. Task-group headings determine topics. Historical task context
  and source references accompany scored entries. Large context becomes an explicit
  oversized exclusion and needs a more narrowly reviewed source snapshot.
- Duplicate candidates come from bounded, same-scope inverted postings, with up
  to three neighbours per entry. Common terms with over 200 postings are skipped.
  This is incomplete lexical retrieval, especially for bilingual paraphrases and
  cross-project duplicates. Missing pairs are not evidence of uniqueness.
- Every entry starts protected. The 80/60/40 value bands are advisory; low scores
  do not delete anything. Rule conflict and current/historical/uncertain status
  are judged separately. Rule packets are selected explicitly, not inferred from
  arbitrary historical memory. README is evidence, not authorization.
- English drafts must cover all source IDs. Merges retain all distinct facts,
  exceptions, conflicting states and citations. Backtick literals are checked
  mechanically; semantic preservation, new claims and English prose are checked
  by Jev with a 0.95 acceptance threshold. Chinese terms need a justification.
  A model gate pass still requires human review, and never applies an edit.

## 1. Index local sources and rules

Create an ignored `.local/pipeline-config.json` using real local paths:

```json
{
  "sources": [{
    "path": "/absolute/path/MEMORY.md",
    "scope": "unknown",
    "groups": {
      "Task Group: Example project": "example-project"
    }
  }],
  "rules": [
    {"path": "/absolute/path/global/AGENTS.md", "kind": "global_agents", "scope": "*"},
    {"path": "/absolute/path/project/AGENTS.md", "kind": "project_agents", "scope": "example-project"},
    {"path": "/absolute/path/project/README.md", "kind": "readme", "scope": "example-project", "lines": [1, 20]}
  ]
}
```

`groups` keys must match the complete first-level Markdown heading without `# `.
For a source belonging entirely to one project, set its `scope` directly.
Use separate scopes for directory-specific rules. `user` is also an accepted rule
kind for a file containing current task instructions. Rule source paths, hashes
and selected line ranges remain in the local index/config. Outbound rule packets
contain selected text, kind and source hash. Review them before executing.

```bash
python3 skill/scripts/memory_pipeline.py index \
  --config .local/pipeline-config.json --output .local/index-v2
```

The output directory must be new. It contains frozen snapshots, lossless source
line spans, stable content IDs, postings and a summary. Stable IDs survive edits
to unrelated entries; changes to relevant context or rules invalidate requests.

## 2. Prepare and inspect batches

Set `JEV_CLIENT` to the absolute path of the existing TypeSafe `typesafe_jev.py`.
Use an explicit cache epoch identifying the reviewed model/policy period; start a
new epoch when the `jev-latest` alias changes. Alias model versions are not
predictable offline, so the operator must manage this boundary.

```bash
python3 skill/scripts/memory_pipeline.py plan \
  --index .local/index-v2 --output .local/plan-v2 \
  --client "$JEV_CLIENT" --cache-epoch jev-1.13.0-review-20260925

python3 skill/scripts/memory_queue.py \
  --batch .local/plan-v2/batch-00000.json \
  --state .local/plan-v2/queue.sqlite --client "$JEV_CLIENT"
```

The second command is a **dry run**. It validates the frozen client, request
hashes, budgets and schemas without loading credentials or sending memory.
Inspect `plan.json`, `exclusions.jsonl` and the actual batch state/rules.
Do not execute a full private corpus merely to benchmark concurrency.

After authorizing the selected outbound batch, add `--execute --max-calls N`,
where `N` exactly matches its request count. Concurrency defaults to 500; use
`--concurrency 100` to lower it. Reuse the same `queue.sqlite` for every batch in
this plan. Do not start parallel dispatchers: a project-wide file lock rejects
another dispatcher while one is running.

### Resume and failure handling

Queue writes are committed before transmission. Completed requests are reused
using payload + metadata + client + policy + epoch hashes. Run the same command
to resume a clean interruption before any request was submitted, or reuse completed
results. For a new plan, pass `--reuse-state /absolute/path/prior-plan/queue.sqlite`
to import matching attempts. This imports unknown attempts too, so an interrupted
request cannot silently turn into a fresh paid request. Changed payloads, rules,
client or epoch get new keys. A running request left after interruption becomes `unknown`. Any transport,
HTTP or response-validation error stops new dispatch; in-flight work is drained.
No uncertain request is retried automatically, even if it may not have reached
Jev. Batches containing unresolved attempts refuse to run. Raw responses, where
received, remain in the sidecar database for investigation. Reconciliation of
unknown attempts is manual; do not delete queue state or change epochs to force
a retry without checking provider billing/outcome. Actual currency cost is reported
as unknown; provider token usage and resolved model are retained. Report token
totals include reused results and must not be interpreted as newly billed usage.

## 3. Report and produce bounded agent work packets

```bash
python3 skill/scripts/memory_output.py report \
  --plan .local/plan-v2 --output .local/review-v2 --client "$JEV_CLIENT"

python3 skill/scripts/memory_pipeline.py packets \
  --index .local/index-v2 --report .local/review-v2/report.json \
  --output .local/packets-v2
```

Packets contain originals, scoped rules, provenance, scoring and relation evidence.
They are grouped by scope/topic and bounded by serialized byte count. `coverage.json`
lists oversized entries requiring separate treatment. With no `--report`, packets
are available offline but have no Jev evidence. The agent rewrites one packet at a
time; the pipeline does not automatically spawn agents or call a text-generation
provider. All produced memory prose must be English except justified terms.

## 4. Verify an English draft and export

Supply a JSON file with this shape, using exact IDs from the packets:

```json
{
  "candidates": [{
    "id": "project-recovery",
    "source_ids": ["source-id-from-packet"],
    "text": "Preserve the original recovery conditions and verification evidence.",
    "retained_terms": [],
    "term_justification": ""
  }]
}
```

A candidate may cover several sources in one scope. Sources cannot appear in
multiple candidates, and unknown IDs or cross-scope merges are rejected. Missing
sources and oversized verification jobs are explicitly recorded.

For reviewed headings and provenance only, a candidate may specify
`context_only_source_ids` (a subset of its structural source IDs) and a nonempty
`context_only_justification`. These units stay in the coverage ledger and semantic
context, but are not mandatory prose in the draft. Factual memory bullets cannot
be marked context-only, and every draft must retain at least one content source.
Do not use this option to hide substantive prose that the parser classified as structural.

```bash
python3 skill/scripts/memory_output.py draft \
  --index .local/index-v2 --candidates .local/candidates.json \
  --output .local/draft-plan-v2 --client "$JEV_CLIENT" \
  --cache-epoch jev-1.13.0-review-20260925
```

Dry-run and execute the reviewed verification batches with `memory_queue.py` as
above, using `.local/draft-plan-v2/queue.sqlite`. Then:

```bash
python3 skill/scripts/memory_output.py report \
  --plan .local/draft-plan-v2 --output .local/draft-export-v2 \
  --client "$JEV_CLIENT"
```

The export contains `MEMORY.candidate.md`, a per-source coverage ledger and raw
advisory judgments. Pending, uncertain and failed gates are prominently labelled.
It has no apply/delete command. Batch files and draft coverage are hash checked
before reporting so later edits cannot silently inherit an earlier model verdict.

## Offline verification

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Tests cover lossless parsing, stable IDs, reference context, unknown scope,
500 overlapping mock requests, 1,000-request batch boundaries, cache reuse,
interrupted/failed requests, altered payloads, oversize exclusions and the
index → plan → mock evaluation → packet → merged English draft → export flow.
No credentials, paid inference or native memory writes are involved.
