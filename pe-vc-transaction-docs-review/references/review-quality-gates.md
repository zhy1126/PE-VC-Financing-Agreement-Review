# Review Quality Gates

Use these gates as the completion contract for every substantive review. A gate
may be marked `passed`, `passed with limitations`, or `blocked`. Do not silently
continue through a blocked gate.

Before delivery, aggregate the evidence through
`scripts/validate_review_completion.py`. New v0.1.16 matters use
`assets/review-completion-gate-template-v2.json`; the v1 template remains legacy
only. A machine check cannot establish
substantive legal quality, so the configured judgment gates must identify the
reviewing agent or designated reviewer and the evidence checked. They do not
require the user to complete a separate form. Only an aggregate `passed` result permits an
unqualified completion statement. `passed_with_limitations` requires prominent
limitation disclosure; `blocked` prohibits any completion statement.

The five stages in `references/redline-closure-loop.md` are conditional
subroutines inside existing workflow steps 7, 14 and 16, not five additional
quality gates or `review_checkpoint.py` stages.

When confirmation is required, schema v2 also requires current source and base
manifest fingerprints, the unique active import, approved content, report model,
confirmation-form Word QA and final-report Word QA. Map blank, conflicted, stale,
foundational-pending or draft evidence to `blocked`; map a disclosed local
deferral to `passed_with_limitations`; map all applicable current confirmations
to `passed`. Evidenced negative scope may use `not_applicable`. Full field and
state rules remain in `references/lawyer-confirmation-gate.md`.

## Gate 0: Matter and Authority

Pass only when the user instructions and file package establish, or the user
authorizes assumptions for:

- Current matter and client side.
- Review round and scope.
- Output mode and language.
- Structure and governing law, or permission to infer them.
- Confidentiality and cross-matter boundary.
- For later rounds, the available version-chain baseline and the limitations
  caused by anything missing.

Verifier: completed matter profile plus an explicit list of assumptions and gaps.

## Gate 1: File Readiness

For every in-scope file, record:

- File type and extraction method.
- Whether text was extracted.
- Page/paragraph or OOXML location quality.
- Whether OCR, manual review, or conversion is required.
- Whether Track Changes markers and text-bearing changes are present.

Block substantive review of a file when extraction is empty or failed. Do not
count successful extraction of other files as proof that the blocked file was
reviewed.

Verifier: `scripts/build_document_map.py` plus extraction results; use
`scripts/smoke_test_transactions.py --strict` for regression verification.

## Gate 2: Package and Version Chain

Confirm:

- Document families, versions, dates, and apparent clean/redline status.
- Primary operative agreement and controlling language.
- Missing common documents and whether review can proceed without them.
- Current markup, prior draft, prior issue log, prior Major Issue List, and
  counterparty response for later-round acceptance/rejection conclusions.
- When both versions are clean, clause-level alignment/change output, confidence
  or ambiguity flags, and any manual-alignment limitations.
- Candidate cross-document conflicts in definitions, amounts, cap-table facts,
  rights families and dispute mechanisms, including unreadable or omitted files.

Treat filename-based structure/language/version output as intake hints only.
Confirm against operative text before relying on it.

Verifier: document map and version-chain table; use
`scripts/compare_contract_versions.py` for clean prior/current files and
`scripts/build_package_matrix.py --strict` for multi-document packages.

## Gate 3: Research Provenance

For every material issue, separate and label:

- Agreement fact or user-provided fact.
- External entity/background fact and query time.
- Market benchmark and benchmark period.
- Legal authority, status, pinpoint, and verification date.
- Pending fact, pending legal research, or local-counsel question.

Verifier: issue-log fields `Market Context`, `Legal Basis`, and
`Authority / Verification Status`; run `scripts/validate_issue_log.py`, independently verify historical
benchmarks before updates or high-stakes reliance, and run
`python3 scripts/refresh_legal_authorities.py --data references/legal-authorities.json --check-urls --output path/to/legal-authority-refresh.json`
when the registry freshness or coverage gate is triggered.

## Gate 4: Substantive Coverage

Review every relevant checklist family, including definitions, economics,
closing, warranties/disclosure/indemnity, investor rights, founder restrictions,
governance, transfer/exit, regulatory and compliance covenants, dispute
resolution, boilerplate, schedules, and cross-document consistency.

Record `reviewed`, `not applicable`, `missing document`, or `deferred` for each
family. Absence of an issue is not proof that a family was reviewed.

Verifier: clause coverage matrix and cross-document conflict matrix.

## Gate 5: Recommendation Quality

Each recommendation must contain:

- Precise location and current text or concise excerpt.
- Issue and client-specific position.
- Market context or a reason it is not applicable.
- Legal basis and authority status when legally material.
- Risk level.
- The minimum unanswered fact questions that could change the drafting route,
  obligor, approval path, or feasibility; use bracketed variables, parallel
  options, or an express hold when the facts remain unresolved.
- Complete paste-ready wording, or a document/fact request when wording cannot
  responsibly be completed.
- For a major issue with a genuine negotiation range, complete Preferred,
  Balanced, and Minimum Acceptable drafting packages; when three tiers are not
  useful, state why rather than manufacturing artificial differences.
- A synchronized-clause and document check covering applicable definitions,
  operative provisions, remedies, articles, approvals, disclosure documents,
  schedules, and signature pages; use explicit `not applicable / 不适用` when
  there is no synchronized item.
- Fallback and any client decision required.

Use the existing issue-log fields and companion Issue Entry mapping in
`references/output-templates.md`; do not add ad hoc CSV columns. The structural
issue-log validator cannot prove that fact questions, drafting tiers or
synchronized changes are substantively adequate.

Verifier: issue-log validation plus human spot-check of every high-risk item.
For an initial requested redline, apply stages one through three and, after
implementing the edit, immediately run stage five section 5.1. Do not apply
stage four unless a prior issue/position is being compared with a revision.

## Gate 6: Negotiation State and Revision Response

For later rounds:

- Preserve the same Issue ID for the same dispute.
- Use exactly one supported status per row.
- Distinguish accepted, partially accepted, rejected, new, reopened, deferred,
  and closed issues from mere text changes.
- Add new counterparty issues without renumbering existing issues.
- When comparing the issue log with a lawyer or counterparty revision, preserve
  separate response grades: Complete, Substantial, Partial, Alternative
  Solution, Unaddressed, Reopened, and New Issue (完全回应、实质回应、部分回应、
  替代方案回应、未回应、重新开启、新增问题).
- Support every response grade with locatable revision or reply evidence; record
  residual/new risk, synchronized clauses, and the next step even when the
  drafter used a substantively responsive alternative solution.
- Re-scan the modified text and connected documents for reopened and new risks.
  Do not close an issue merely because the original wording disappeared.
- With a prior issue/position baseline, apply stage four and return unresolved,
  reopened and new issues and alternative-solution residual risks to stages one
  through three. Without that baseline, perform only a limited current-text
  review and do not assign a response grade.
- Independently, whenever Track Changes, another identifiable edit, or a
  prior/current version comparison exists, run stage five section 5.1 even when
  there is no prior issue log. If no edit can be isolated, disclose that
  limitation and do not claim the post-edit scan.

Response grade is diagnostic and separate from negotiation state. Neither a
response grade nor an Accepted/Rejected label proves legal correctness,
enforceability, drafting quality, or authority to agree.

Verifier: `scripts/update_major_issue_list.py`, followed by
`scripts/validate_major_issue_list.py`; for the baseline-supported stage-four
branch, also produce the seven-column response matrix and run
`scripts/validate_response_matrix.py`. The independent stage-five section 5.1
post-edit scan does not require that matrix or its prior issue/position baseline.

Use the default form for existing Issue IDs only. Use `--allow-new` only when a
newly promoted major issue has been approved for insertion and its update row is
fully populated.

```bash
# Existing Issue IDs only.
python3 scripts/update_major_issue_list.py path/to/existing-major-issue-list.csv path/to/major-issue-updates.csv --output path/to/updated-major-issue-list.csv

# Existing IDs plus approved, fully populated newly promoted Issue IDs.
python3 scripts/update_major_issue_list.py path/to/existing-major-issue-list.csv path/to/major-issue-updates-with-approved-new.csv --allow-new --output path/to/updated-major-issue-list.csv
```

## Gate 7: Delivery and Confidentiality

Before delivery:

- Match the primary document language.
- Confirm requested output mode and that comments-only review did not modify the
  source document.
- For native comments, confirm unique anchors, separate output, unchanged visible
  text, valid OOXML comment wiring, inserted-count parity, clean render, and a
  tested rollback report.
- Keep the Major Issue List to exactly five semantic columns.
- After accepting revisions or producing a clean/signature version, re-read the
  resulting text and check definitions, numbering, cross-references, amendment
  residue, brackets/placeholders, linked documents, and signature pages. Confirm
  transaction amounts, currencies, price/share/registered-capital figures,
  percentages, valuation, caps, thresholds, formula inputs, dates, periods and
  schedule totals are numerically and chronologically consistent across the
  clean/signature package. Confirm that cleaning the redline introduced no
  unrecorded substantive mutation.
- Apply stage five section 5.2 only when the final clean/signature version is in
  the current review scope. Return any newly identified,
  reopened or incomplete issue to stages one through three; stage four remains
  conditional on a prior issue/position and locatable revision evidence.
- Remove accidental absolute paths, unrelated matter names, temporary files,
  and internal benchmark source names from user-facing outputs.
- State unreviewed files and material limitations prominently.

Verifier: final file list, validators, source/output hashes and native-comment
apply report where comments-only integrity matters, render inspection, rollback
test, the clean/signature-version record required by
`references/redline-closure-loop.md` only when stage five section 5.2 applies
and a final clean/signature version is in scope, and a targeted confidentiality
scan.

## Exact Command Examples

Run from the Skill root. Replace each placeholder with the described matter
path; the examples below include every required positional input.

```bash
# Inputs: one or more transaction files or folders.
python3 scripts/build_document_map.py path/to/transaction-files

# Input: a root containing transaction-project folders.
python3 scripts/smoke_test_transactions.py path/to/transaction-projects --strict

# Inputs: prior clean agreement, then current clean agreement.
python3 scripts/compare_contract_versions.py path/to/prior.docx path/to/current.docx

# Inputs: one or more transaction files or folders.
python3 scripts/build_package_matrix.py path/to/transaction-files --strict

# Input: completed bilingual issue-log CSV.
python3 scripts/validate_issue_log.py path/to/issue-log.csv

# Input: completed five-column Major Issue List CSV.
python3 scripts/validate_major_issue_list.py path/to/major-issue-list.csv

# Input: completed seven-column Response Matrix CSV.
python3 scripts/validate_response_matrix.py path/to/response-matrix.csv

# Input: canonical legal-authority registry; optionally checks official URLs.
python3 scripts/refresh_legal_authorities.py --data references/legal-authorities.json --check-urls --output path/to/legal-authority-refresh.json

# Input: matter-specific completion-gate JSON; output is the aggregate result.
python3 scripts/validate_review_completion.py path/to/review-completion-gate.json --output path/to/review-completion-result.json

# Skill-package release checks.
python3 scripts/validate_skill_frontmatter.py SKILL.md
python3 scripts/validate_skill_consistency.py
```

The build, smoke, and structural validators are evidence aids. They do not
replace the judgment checks in Gates 3 through 7.
