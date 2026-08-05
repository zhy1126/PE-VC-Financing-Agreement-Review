# Multi-Round Review and Major Issue List

Use this reference when a matter involves first-draft review, counterparty markup review, or repeated negotiation rounds.

## Review Modes

First-draft full review:

- Review the whole package and produce the selected full report/comment output.
- Ask whether the user wants a Major Issue List. If the user does not answer and the review finds material issues, recommend creating one.
- Seed the Major Issue List only with major negotiation points, not every drafting comment.

Counterparty markup review:

- Use when reviewing a second or later draft returned by counterparty counsel.
- Inputs should include the current markup/redline draft and, where available, the prior issue log, prior Major Issue List, and prior version of the agreement.
- Treat the later-round intake gate as mandatory. Confirm the current round, review scope, baseline documents, whether key deal assumptions remain unchanged, output mode, and Major Issue List handling before substantive review.
- If prior baseline materials are missing, proceed only if the user authorizes a limited review and state that acceptance/rejection status cannot be reliably determined.
- A missing prior issue/position baseline prevents response grading, but does
  not prevent a post-edit scan when Track Changes or a prior/current version
  comparison identifies edits. Record these two prerequisites separately.
- For `.docx`, extract Track Changes and compare each changed paragraph's reconstructed `before_text` and `after_text`; use author/date metadata only as supporting provenance. If revision markers exist without text-bearing changes, say that no substantive visible change was isolated and compare versions or perform a full review. For PDFs, inspect redline pages manually or use OCR where needed. If the current file is clean with no redlines and both versions are available, run `scripts/compare_contract_versions.py <prior> <current>` and review `clause_alignment`, `clause_changes`, and the backward-compatible paragraph `change_blocks`. Otherwise explain that changed text cannot be isolated reliably.
- Treat clean-version clause alignment as a routing aid. The comparator recognizes
  common Chinese/English clause labels and distinguishes renumbered, moved,
  split, merged, modified, added, and deleted candidates, but tables, malformed
  numbering, formatting-only changes, and low-confidence alignments still need
  manual verification. Do not infer accepted/rejected status without the prior
  issue or position even when the textual change is clear.
- If the `.docx` markup contains high-volume Track Changes, do not dump all changes into the answer. Ask whether to run a full redline review, a core-clause-focused review, or a Major Issue List-focused review, and state that full review may need batching.
- Focus on what changed, but read nearby definitions, cross-references, schedules, articles/MAA, and side letters where the changed text depends on them.
- When comparing a prior Skill issue log with a lawyer or counterparty revised
  draft, apply `references/redline-closure-loop.md` and produce the seven-column
  Response Matrix in `references/output-templates.md`. Do not rely on textual
  similarity alone.
- Whenever edits are identifiable, perform the Post-Edit Scan in
  `references/redline-closure-loop.md` even if no prior issue log exists. If no
  edit can be isolated, disclose that limitation and do not claim a post-edit
  scan was completed.

## Major Issue Criteria

Include an issue in the Major Issue List if it is likely to affect economics, control, exit, liability, enforceability, or closing certainty, or if it is a key benchmarked VC/PE clause. Common examples:

- Valuation mechanics, investment amount, closing conditions, deliverables, and default consequences.
- Redemption, put rights, repurchase, investor exit rights, and founder/company liability.
- Liquidation preference, anti-dilution, pay-to-play, down-round protection, and conversion mechanics.
- Board composition, veto/reserved matters, information rights, inspection rights, and budget/business-plan controls.
- Transfer restrictions, ROFR, co-sale, drag-along, lock-up, founder vesting, non-compete/non-solicit, and founder departure.
- MFN, side-letter priority, strategic investor rights, exclusivity, confidentiality, publicity, and competitor restrictions.
- Governing law, arbitration/forum, service of process, remedies, specific performance, and PRC law enforceability issues.
- Cross-document inconsistencies among investment agreement, shareholders agreement, articles/章程/M&A/MAA/M&AA, disclosure letter, and side letters.

Do not include routine typos, numbering cleanup, simple formatting, or minor wording adjustments unless they create legal ambiguity or a negotiation position.

## Major Issue List Columns

Use `assets/major-issue-list-template.csv` as the default table shape:

- Issue ID
- Major Issue / Clause
- Our Position
- Counterparty Position / Status
- Next Step / Fallback

Do not exceed these five columns. Compress location, disputed point, risk level, latest status, and fallback into the relevant cell instead of adding extra columns.

Allowed status values:

- Open
- Partially Accepted
- Accepted
- Rejected
- New Counterparty Issue
- Reopened
- Deferred
- Closed

Use exactly one status per row. A status describes the negotiation state of the
issue, not merely whether the text changed. Preserve the same Issue ID and merge
approved updates with `scripts/update_major_issue_list.py`; never regenerate the
whole list if doing so would renumber existing issues.

The default merge updates existing Issue IDs only. Use `--allow-new` only after
a newly promoted major issue is approved for insertion and its update row is
fully populated; do not use it merely because the current draft contains an
untracked text change.

Negotiation statuses are separate from response grades. `Accepted / 已接受` and
`Rejected / 已拒绝` describe negotiation state. `Complete / 完全回应`,
`Substantial / 实质回应`, `Partial / 部分回应`,
`Alternative Solution / 替代方案回应`, `Unaddressed / 未回应`,
`Reopened / 重新开启`, and `New Issue / 新增问题`
diagnose how a revision addresses an original concern. A row may therefore have
a negotiation status in the Major Issue List and a separate response grade in
the Response Matrix. Neither classification proves legal correctness or
signature readiness.

Apply the following status rules consistently:

- Follow any status taxonomy or classification rule expressly requested by the user.
- Use `Rejected` when the counterparty expressly rejects our position or returns a later draft that deliberately keeps the disputed text after receiving our prior comment or proposal.
- Use `Open` only when no reliable counterparty response is available, the relevant document has not yet been returned, or the issue remains pending without a basis to infer acceptance or rejection.
- Use `Partially Accepted` when the counterparty adopts only part of the requested protection and a material residual issue remains.
- Use `Reopened` when an issue previously accepted or closed returns in a later draft or connected document.
- Do not label an unchanged clause `Rejected` merely because no text changed if the baseline does not show that the counterparty had received our position.

## First-Draft Output

When preparing a first-draft review:

- Produce the full issue log or comments requested by the user.
- Separately identify which issues are major enough for negotiation tracking.
- If creating the Major Issue List, summarize why each item is major and preserve the complete proposed revised wording or a concise cross-reference to the full issue entry.
- Keep simple drafting fixes as ordinary comments only, not major issues.

## Later-Round Output

For each tracked major issue, update:

- Counterparty Position / Status: quote or summarize the counterparty markup or response and state accepted, partially accepted, rejected, new, reopened, deferred, or closed.
- Next Step / Fallback: state hold position, accept, propose compromise, escalate to client, ask counterparty question, local-counsel check, and the commercial fallback if relevant.

Also flag untracked new issues introduced by counterparty revisions and decide whether they should be added to the Major Issue List.

When a lawyer or counterparty draft is being tested against a prior issue log,
also produce one Response Matrix row for every original issue and one `NEW-`
row for each newly identified issue. Each row must contain:

- the stable Issue ID and original concern;
- locatable revision or reply evidence;
- exactly one supported response grade;
- the residual or new risk;
- synchronized clauses/documents; and
- the next step.

Recognize a materially responsive different mechanism as `Alternative Solution
/ 替代方案回应`; then evaluate its feasibility, dependencies and residual risk
instead of downgrading it only because it differs from the preferred text. If
no residual/new risk or synchronized clause applies, write `not applicable /
不适用` rather than leaving a cell blank.

Independently of response grading, whenever edits are identifiable, re-scan the
modified full text and connected documents. With a response baseline, if a
previously resolved concern returns, use `Reopened / 重新开启`; if the modification
creates a distinct risk, create a `New Issue / 新增问题` row. Without a response
baseline, record the same risks in the limited current-text review without
assigning those response grades.
After revisions are accepted into a clean or signature version, perform the
definitions, transaction-amount/date and other numeric-consistency, numbering,
cross-reference, residue and signature-page checks in
`references/redline-closure-loop.md` before stating that the round is complete.

## Delta Review Memo

For later rounds, prefer a short delta memo over a fresh full report unless the user asks for a full re-review:

```markdown
# Counterparty Markup Review

## Assumptions
- Round:
- Review scope:
- Files reviewed:
- Prior issue log / Major Issue List used:
- Prior issue/position baseline exists: yes / no
- Identifiable edits or prior/current version comparison exists: yes / no

## Executive Summary
- Accepted points:
- Points still open:
- New counterparty issues:
- Client decisions needed:

## Major Issue List Updates
| Issue ID | Major Issue / Clause | Our Position | Counterparty Position / Status | Next Step / Fallback |
|---|---|---|---|---|

## Response Matrix
<!-- Include only when a prior issue log or documented position exists. -->
| Issue ID | Original Concern | Revision Evidence | Response Status | Residual / New Risk | Synchronized Clauses | Next Step |
|---|---|---|---|---|---|---|

## Post-Edit Scan
<!-- Include whenever edits are identifiable, with or without a prior issue/position baseline. -->
- Edit/version evidence used:
- Reopened issues:
- New issues:
- Alternative solutions and residual risks:
- Clean/signature-version definitions, amounts, dates, numeric consistency,
  cross-references and signature-page check, if applicable:

## Baseline-Limited Current-Text Review
<!-- Use instead of Response Matrix when no prior issue/position baseline exists; retain Post-Edit Scan when edits are identifiable. -->
- Missing baseline and limitation:
- Current-text risks identified:
- Response grades omitted: yes

## Other Markup Comments
| File/Clause | Change | Issue | Recommendation | Proposed wording / fallback |
|---|---|---|---|---|
```

Use either Response Matrix or the baseline-limited current-text section, never
both. Post-Edit Scan is independent and must accompany either path whenever
edits/version differences are identifiable. Without a prior issue/position
baseline, do not assign a response grade; without identifiable edits, do not
claim a post-edit scan.
