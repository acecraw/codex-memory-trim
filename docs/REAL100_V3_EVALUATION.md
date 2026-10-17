# V3 real-memory evaluation — 2026-09-25

## Outcome

The annotation → candidate retrieval → four-way relation → bounded agent packet
→ English proposal flow completed on **100 real entries**. This deliberately
reuses the previous frozen sample for comparison; it is not 100 additional records.
The sample contains 20 entries each from five projects and mostly already curated
knowledge. It does not represent the full raw conversation corpus.

- 100 annotation requests and 223 relation requests completed in the final flow.
- 45 agent packets covered all 100 source IDs, with no exclusions. Each packet
  stayed within 16,000 bytes and eight entries.
- Agent and primary review produced **89 English proposals through 11 merges**.
  All 100 source IDs are covered exactly once; original backtick literals remain.
  Chinese terms are retained only with recorded precision justifications.
- Normalized body size: **27,698 → 23,677 UTF-8 bytes, down 14.52%**.
  The exported file including headings and source-ID comments is 26,217 bytes.
  These are byte measurements, not token counts or proof of live context savings.
- Native MEMORY.md matched its start-of-run hash. Nothing was applied to Codex.
- 30 local unit tests passed, including queue reuse, coverage, literal guards,
  bounded grouping, scope separation and incomplete-response rejection.

## What Jev decided

| Dimension | Final labels |
| --- | --- |
| Time | 85 persistent, 11 uncertain, 4 open obligations |
| Usefulness | 86 durable, 14 temporary |
| Pair relations | 32 overlap, 1 progression/conflict, 190 distinct/uncertain |
| Complete duplicates | 0 among the retrieved real pairs |

There were no confirmed abandoned ideas or unambiguously expired one-off items
in this curated real sample. Zero such labels does not establish detection recall.

The initial 100-item annotation pass confused imperative reusable rules with
pending work and marked only two entries temporary. A second frozen pass added
memory-kind classification and clarified guidance, observations, one-off tasks
and tentative ideas. It marked 14 temporary. This is a prompt revision observation,
not a claim that every changed label became correct.

## Primary review findings

- A reusable CSS diagnosis/fix still received open-obligation/temporary labels.
  It remains in the proposal as reusable knowledge.
- Some mixed entries combine durable rules with pending work. Their persistent
  label alone loses that distinction; separate follow-up judgments and original
  pending qualifiers remain in the agent packet and final text.
- Jev called an incomplete payment integration and an earlier empty-workspace
  observation overlapping. Primary review kept them separate.
- Top-three lexical retrieval missed a pair sharing an old routing threshold.
  Agent review recovered the pair. The proposal preserves its historical status
  separately from the newer simplified optional-Jev routing policy.
- Merge review retained unique details in domain due diligence, incremental
  releases, report views/search, credential gates and tenant isolation.

**The flow is suitable for assisted review, not unattended deletion.** Source-ID
coverage is a structural check; it does not by itself prove semantic preservation.
The exporter explicitly keeps that distinction. The previous V2 semantic gate
that rejected all positive drafts was not reused as a V3 acceptance gate.

## Independent reference and synthetic controls

Before Jev output was read, another agent labeled all 100 entries and 39 selected
pairs. Only 23 of those pairs occurred in the retrieved set; 16 labels matched.
The reference includes ambiguous or unsupported distinctions between overlap and
progression. These **16/23 matches are not accuracy**, are not representative of
all 223 pairs, and cannot be compared directly with the prior 116/226 result.

Nine separately labeled synthetic temporal controls matched their expected time
labels: overdue-but-undelivered stayed open; an explicitly expired promotion was
closed; an undecided idea was temporary rather than abandoned; an explicitly
rejected idea was abandoned; a historical reusable lesson stayed durable. An exact
duplicate control was recognized. A cancelled report and an abandoned dashboard
were incorrectly called overlapping, confirming that distinct-object checks
still need review. Synthetic cases are not counted among the 100 real memories.

## Calls, capacity and costs

- Final real flow: **323/323 calls**, 431,816 input and 43,591 output tokens.
- Including the first annotation iteration and all synthetic controls:
  **453/453 calls**, 543,358 input and 60,318 output tokens.
- Actual model: `jev-1.13.0`. Currency charges were not returned and remain unknown.
- Configured concurrency: 500; observed maximum in-flight calls: **223**.
  This run does not establish 500 simultaneous live-call capacity.
- Re-running the 223-pair batch reused all 223 responses, with zero new calls.
- No uncertain call was retried. No native memory edits, commit, push or deployment.

Private source snapshots, raw responses, reference labels, primary review,
candidate texts and coverage ledgers are under ignored `.local/real100-v3/`.
Only this aggregate report is suitable for version control.
