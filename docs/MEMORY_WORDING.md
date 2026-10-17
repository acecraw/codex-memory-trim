# Compressing MEMORY.md in its existing layout

The target is the native MEMORY.md document, not the compact retrieval proposal.
Keep all original task headings, scope/reuse conditions, keyword sections and
source-reference metadata in place. Rewrite only the extracted memory bullets.
Each source ID retains its own location; no cross-project or cross-task relocation.

## Editorial contract

- Compress wording, not distinct facts or authorization conditions.
- Preserve paths, identifiers, commands, endpoints, quantity boundaries, dates,
  historical/current distinctions, incomplete outcomes and source markers.
- Use English prose; retain exact Chinese names, UI labels or authoritative quotes
  where translation would lose precision.
- Preserve ad-hoc-marked entries verbatim.
- Keep original facts when evidence files are missing; do not replace them with
  an unusable pointer.
- Retain short entries unchanged when rewriting offers no safe improvement.

Workers produce one replacement for each assigned source ID. The assembler checks
the frozen backup against both its manifest and the current native file before
using original line spans. Everything outside those spans remains byte-for-byte
unchanged. It emits a full candidate, original snapshot, unified diff and report.
Protected-literal and numeric findings require review; output existence is not
approval to adopt it. Literal preservation alone is not semantic validation.

```sh
python3 skill/scripts/memory_wording.py \
  --run .local/full-memory/RUN \
  --replacements .local/native-wording \
  --output .local/native-wording/review-1
```

The output directory must be new. This command performs no API calls, native
memory writes, database changes, configuration changes or Git commits. It refuses
an output inside native memory. A changed native file requires rebasing; never
overwrite newer memory using a frozen proposal.

## Adoption boundary

The current agent's memory-write instructions permit only explicit update notes
under `extensions/ad_hoc/notes/`, not direct editing of native generated memory.
Consequently this workflow delivers a reviewable full-document candidate rather
than silently installing it. No apply command is provided. Runtime compatibility,
background consolidation behavior and a permitted adoption mechanism remain
separate from wording quality and size reduction.

The 2026-09-25 read-only baseline found 122 missing rollout-summary references and
a consolidation job in `error`. These predate this pass. Keep these findings
separate from compression regressions; punctuation caused false positives for
ad-hoc note references, and all note references resolved after punctuation cleanup.
