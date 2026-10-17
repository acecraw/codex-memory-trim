# Real 100-memory evaluation — 2026-09-25

The complete V2 review/export flow was exercised with 100 real memory bullets
from five projects, not synthetic source memories. Native memory was not changed.
Private source text, drafts and per-item audit files remain under ignored
`.local/real100/`; no private source material is included in this document.

- 100 score + 226 pair + 100 draft verification + 8 negative-control + 10 diagnostic
  requests: **444/444 completed**, resolved model `jev-1.13.0`, no automatic retry.
- Configured concurrency 500; actual peak 326. This is not a live 500-concurrent proof.
- Input/output usage: 2,289,773 / 60,308 tokens; actual currency billing unknown.
- Re-running the first batch reused 326 completed results with zero new attempts.
- Raw blind relation agreement: 116/226 (51.3%), not accuracy. Most differences
  were unrelated versus related-distinct; primary review found both model errors
  and questionable blind labels. No equivalent auto-merge candidate passed.
- All 100 scores and all 100 positive draft candidates required review under the
  existing gates. All 8 intentionally wrong candidates were rejected too. An
  always-reject outcome does not establish a useful or reliable acceptance gate.
- Removing full policy context in 10 diagnostic requests did not resolve the
  positive-candidate rejection. Thresholds were not lowered.
- Candidate prose shrank 27,698 → 24,353 UTF-8 bytes (12.08%). The actual compact
  Markdown artifact is 25,770 bytes. These are byte measurements, not token savings.
- Coverage: all 100 factual bullets and 200 structural/provenance units accounted for.

The sample used bounded-length knowledge/preference bullets selected evenly
within five scopes. It is not random, lacks confirmed exact-duplicate positives,
and cannot establish corpus-wide accuracy or duplicate recall. Independent blind
review was AI-assisted, not authoritative human ground truth. Current facts in
historical memories were not revalidated against production systems.

The run found and fixed a provenance/body distinction: explicitly reviewed
structural units can be retained as context-only with a justification while factual
units cannot be excluded from draft coverage. Regression suite: 25 offline tests.

**Current readiness:** usable as an assisted review, provenance and draft-export
pipeline; not validated for autonomous retention, merging, deletion or native
memory replacement. Next work should calibrate separate value/current-validity
judgments and fact-level coverage checks against held-out data.
