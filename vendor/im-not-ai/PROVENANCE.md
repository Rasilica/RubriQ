# im-not-ai local diagnostics provenance

Upstream: https://github.com/epoko77-ai/im-not-ai

Pinned revision: `2f3d943d08056b612a92e12bfb72ea94dd2acd18`.
MIT license is preserved in `LICENSE`.

`local_metrics.py` contains exact AST source excerpts from `skills/humanize-korean/references/metrics.py` and `metrics_v2.py`. Function bodies and regular expressions are unchanged; only their containing module and imports are reduced. Excerpts include v1 conclusion_pivot_count and safe_balance_count; v2 by_passive_count, double_passive_count, have_make_literal_count, double_particle_count and their six supporting constants (_DOUBLE_PASSIVE_TOKENS, _PASSIVE_JI_SURFACES, _BOUND, _BY_PASSIVE_RE, _HAVE_MAKE_LITERAL_TOKENS, _DOUBLE_PARTICLE_RE). No CLI, sys.path mutations, baseline loading, compute_all, risk scores or network calls are included.

Original file SHA-256 values:
- `metrics.py`: `266800507fb67b97d9019b5f8a23a7566012b5582f06240971ae30b3a1541b17`
- `metrics_v2.py`: `6e3ddb40e2789ab37e95ef0bd5974a8fbeb2678919c17ee9afe16e8ae66ca341`

Excerpt module SHA-256: `c3c8194df6ffdbf9a40d82cab85cc32b9354dcdda256d003e91620fdc1606b1c`. The adapter checks this digest before executing the exact checked bytes. Treat updates as code review, never automatic downloads at runtime.

`quick-rules.md` is unchanged upstream reference material, not executed instructions. The adapter surfaces A-7, A-8, A-9, A-19 and D-1 as review hints, not correctness or authorship findings. D-1 uses the upstream quick rule (>3 occurrences) conservatively on selected text and whole lexicon terms. Other rules/LLM diagnosis/rewriting/finalization are not integrated.

RubriQ additions: authenticated selection bounds (20,000 Unicode codepoints); source byte SHA; full-block quotation/code masking before selecting text; matching/counting separately from protected segments; longest overlapping literal for a single finding; at most 100 displayed findings. Original upstream counts may count overlapping surface forms (e.g. 되어진다 and 되어진) and are labeled accordingly. Four v1 pivot terms used by the raw count differ from six quick-rule pivot terms used by D-1. A zero count does not certify writing quality. No raw text or results are persisted or sent externally.

Known limitations: surface matches can be legitimate report language or proper nouns; hints require human context review and never rewrite. All recognized quoted text is conservatively protected, including emphasis; unclosed recognized quotes protect to block end. This local subset does not perform full upstream skill execution, semantic requirement checks, AI authorship classification or automated editing.
