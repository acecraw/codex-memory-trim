# Jev memory review design

For the scalable implementation with 500 concurrent requests, see [Memory pipeline V2](MEMORY_PIPELINE_V2.md). The curated prototype below remains available for small experiments.

Status: local prototype. Native memory and its database are read-only inputs.
The prototype prepares bounded requests and renders results; it cannot delete,
apply, install, schedule, or commit memory changes.

## Output language

Generated memory must be English. Retain a Chinese term only when translation
would lose precision; list each retained term and its justification explicitly.
Source quotations stay verbatim in local provenance records. Reports and request
questions are English. Translation must preserve conditions, exceptions, scope,
authorization and historical/current status.

## Units and provenance

One unit is a complete knowledge point, preference, or operational lesson, with
its task/project context. Do not split an exception, nested list or code block
away from its governing condition. The initial prototype uses a curated JSON
snapshot; automatic Markdown parsing is a later feature.

Each entry requires `id`, `text`, `scope`, `context`, `source`, and a reviewed
boolean `protected`. Optional `protected_literals` are exact source spans that
must survive candidate rewriting. Source locations and expected test answers
remain local; the provider receives only text, scope and necessary context.
Review the entire outbound state before using real memory. Do not include secrets
or unrelated customer data. Protection must be reviewed, not inferred solely
from a keyword detector or from the model's value score.

## Scoring contract

Four independent Score questions use five concrete levels each. The API's 0..4
score is normalized to 0..100. Value = 0.4 reuse + 0.4 loss impact + 0.2
actionability. Compression potential is separate. All distributions are retained.

| Value | Advisory band |
| --- | --- |
| 80..100 | Core memory |
| 60..<80 | Retain and consider concise wording |
| 40..<60 | Reference material; assess summary placement |
| 0..<40 | Low-value candidate for review |

Use the unrounded value for bands. Protected preferences, authorization limits,
critical exceptions and unresolved obligations remain protected at any score.
Insufficient context is not low value. A context Noul below 0.8 or a value
dimension's confidence below 0.6 routes to review. These are provisional review
thresholds, not calibrated correctness probabilities or deletion permissions.
Age and usage statistics do not independently establish current validity or
obsolescence. Scores based on a snapshot are judgments about supplied evidence.
A concrete but harmful or contradictory rule can still score highly on reuse
and actionability. A detected conflict always requires separate review, even
for protected entries. Retention does not endorse a rule or authorize its use.

## Candidate retrieval and relationship judgment

The prototype ranks character-trigram overlap and takes each entry's top K
neighbors, including candidates from other scopes. Explicit evaluation pairs
can supplement retrieval; use `--top-k 0` for a fixed labeled experiment.
Every entry is scored even if it has no shortlisted neighbors. A missing match
means no candidate was found, not that uniqueness was proved.

The lexical shortlist has limited cross-language/paraphrase recall. Before
full-corpus use, add project aliases and better lexical retrieval, then measure
candidate recall separately from Jev classification. Any embedding provider is
a separate dependency and disclosure/cost decision.

Per pair: one Choice for equivalent, directional containment, overlap,
directional supersession, conflict, related-but-distinct, unrelated, or
insufficient evidence. Three companion Nouls assess scope and unique information
in each direction. A date alone does not establish supersession. Same topic does
not imply same authorization or completion state.

Only equivalent pairs with equivalent probability >=0.95, scope Noul >=0.95,
and both unique-information Nouls <=0.05 are marked merge candidates. This
label is advisory. Containment and supersession require review. Never merge a
connected component transitively: verify every original against the final
representative and retain all source references.

## English compression and verification

Codex authors candidate text; Jev does not generate prose. The prototype accepts
one candidate per source entry. It checks protected literals and unapproved
Chinese characters locally, then asks Jev whether the candidate preserves all
meaning, introduces no unsupported claims, and follows the English policy.
All three Nouls must reach 0.95 for a provisional pass. Literal checks are only
as complete as their reviewed input list; a passing result is not a losslessness
guarantee. Final editorial acceptance remains necessary.

Multi-entry merging, automatic entity extraction, token-budget optimization,
and native-memory application are not implemented. Any future application path
must obey the host's memory-write policy, detect a changed source snapshot and
active consolidation, preserve new edits, and avoid relying on undocumented
database schema or committing unrelated memory files.

## Execution and storage

Use Python standard library tooling plus the user's shared native TypeSafe
client. No project API key or second HTTP implementation is needed. The model
alias is `jev-latest`; the actual returned model is stored in each result.
Use the shared bounded batch runner; it preflights all requests and stops new
dispatch after errors. Do not automatically retry uncertain requests.

Local datasets, requests and results belong in ignored `.local/`, with new
directories mode 0700 and files mode 0600. No private sample belongs in Git.
The manifest pins request and shared-client hashes; reporting verifies them
against batch attempts. Report missing results explicitly and preserve partial
successful work. Record input/output tokens; billing remains unknown unless
provider billing evidence is available.

The prototype does not automatically cache or resume inference. Preserve
completed runs. A future cache key must include input/context, question/policy
version, and actual model version. Changes to `jev-latest` must not silently mix
different model versions in evaluation.
Use prepare's `--only pair verify` with an explicitly narrowed dataset for a
new question-version experiment, rather than reissuing completed scoring calls.

## Commands

Set `JEV_CLIENT` and `JEV_BATCH` to the installed shared TypeSafe scripts.
The client must match the batch runner's client; pass `--client` explicitly.
For an offline synthetic example, replace `.local/sample.json` below with
`tests/fixtures/jev-review-example.json`. Create `.local/` before preparing.

```bash
python3 skill/scripts/jev_review.py prepare --input .local/sample.json \
  --client "$JEV_CLIENT" --output .local/plan --top-k 3

# Offline preflight, no credentials or inference:
python3 "$JEV_BATCH" --manifest .local/plan/manifest.json \
  --client "$JEV_CLIENT" --output .local/results

# Only after outbound state has been reviewed and inference is authorized:
# N must equal the manifest request count. Start with modest concurrency.
python3 "$JEV_BATCH" --manifest .local/plan/manifest.json \
  --client "$JEV_CLIENT" --output .local/results \
  --max-calls N --concurrency 4 --confirm-paid-call

python3 skill/scripts/jev_review.py report --plan .local/plan/plan.json \
  --results .local/results --client "$JEV_CLIENT" --output .local/report

python3 -m unittest discover -s tests -p 'test_jev_review.py'
```

## Evaluation before expansion

Start with a few actual, disclosure-reviewed memories and separately labeled
synthetic paraphrases, scope changes, contradictions, and state changes. Freeze
expected relations before inference. Include a deliberately bad compression.
Keep expected answers out of model state. Assess false merges, missed candidates,
meaning loss, and protection handling independently. A small development sample
demonstrates operation, not accuracy or calibration. Expand to a held-out labeled
set before choosing production thresholds or making automatic edits.

## Development pilot, 2026-09-25

Five actual memory excerpts and six synthetic controls were evaluated using
`jev-1.13.0`. Private inputs and raw responses remain in ignored `.local/`.
The first batch completed 21 requests: 11 scores, 7 pair judgments, 3 candidate
checks. Five of seven relation labels matched the frozen expectations. Two
unrelated pairs were labeled related-but-distinct. The deliberately incorrect
local-test-to-production rewrite was rejected, but both valid rewrites also
failed the conservative semantic gate. All value scores had at least one
uncertain component, so their ranking is advisory.

A targeted five-request v2 experiment clarified unrelated acknowledgements and
asked the English-language question independently of semantic preservation.
Both unrelated labels then matched; all three English checks returned 0.99.
The bad rewrite's preservation and support probabilities remained 0.02. The two
valid rewrites still failed the 0.95 semantic threshold (preservation 0.83 and
0.67). That threshold was not lowered to fit these examples. No pair qualified
for automatic-equivalence recommendation in the initial batch.

Across both batches: 26 completed calls, 21,124 input tokens and 2,714 output
tokens; actual money charged is unknown. The second experiment reused development
examples, so it is not a held-out accuracy result. It did not rerun the other five
pair cases under v2. Full v2 regression and calibration remain future work.

The experiment also exposed a design boundary: a deliberately conflicting rule
scored 69.5 because value measures usefulness and impact, not truth or policy
validity. Reporting now surfaces detected conflicts independently of score.
The prototype is suitable for assisted review, not unattended merging/deletion.

## References

- https://docs.typesafe.ai/primitives/score
- https://docs.typesafe.ai/primitives/noul
- https://docs.typesafe.ai/primitives/choice
- https://docs.typesafe.ai/patterns/composite-scoring
- https://docs.typesafe.ai/cookbooks/entity_alignment
- https://docs.typesafe.ai/confidence
