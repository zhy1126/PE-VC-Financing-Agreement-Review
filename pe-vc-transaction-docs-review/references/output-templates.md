# Output Templates

The eight CSV templates under `assets/` contain one clearly marked synthetic row
so a first-time user can see the expected level of detail. Replace or delete
that row before using a template for an actual matter; never deliver the
synthetic row as project work product.

## Delivery Map

The user does not need to choose files or run scripts. The Agent maps the
requested result to the following template and check automatically:

| User request | Plain-language result | Template or asset | Generation / final check |
|---|---|---|---|
| “审一下” / full review | All material issues, proposed wording and negotiation context | `Full Report` below + `assets/issue-log-template-zh.csv` or English equivalent, using the material-recommendation field mapping below | `scripts/validate_issue_log.py` |
| “列出重大问题” | Decision-level negotiation points only | `Major Issue List` below + `assets/major-issue-list-template-zh.csv` or English equivalent | `scripts/make_major_issue_list.py` + `scripts/validate_major_issue_list.py` |
| “加批注” | A separate Word copy with comments; visible text unchanged | `Comment Text` below with a stable Issue ID + `assets/comment-plan-template-zh.csv` or English equivalent; every material recommendation also needs a delivered companion Issue Entry/issue-log row | `scripts/make_comment_plan.py` + `scripts/apply_comment_plan.py`; validate the companion issue log when used |
| “审本轮红线稿” | Negotiation-state update; response grading when a prior issue/position baseline exists; independent post-edit scan whenever edits are identifiable | `Counterparty Markup Review` below | `scripts/compare_contract_versions.py` + `scripts/update_major_issue_list.py`; run the response validator only when a baseline-supported matrix is produced |
| “比较Skill问题与律师修改稿” / compare issues with a lawyer or counterparty revised draft | Response grading requires a prior issue/position baseline; post-edit scan separately requires identifiable edits or version comparison and still applies without an issue log | Include `Response Matrix` only with its baseline; include `Post-Edit Scan` whenever edits are identifiable | `scripts/validate_response_matrix.py path/to/response-matrix.csv` only for the baseline-supported matrix |
| “给律师确认” | One Word decision card per Issue, split into fact and legal/transaction/drafting subitems | Confirmation Word generated from the immutable base manifest | `scripts/make_lawyer_confirmation_pack.py` + import validation |
| “生成最终 Word 报告” | Report-model projection with final/draft status, approved analysis, pending and unreviewed sections | Final Word generated only from approved content and report model | `scripts/make_legal_review_report.py` + `scripts/validate_word_qa.py` |

If the user says only “审一下”, default to the first row and recommend a Major
Issue List when decision-level points exist. Do not ask the user to select a
CSV or script.

For either later-round row, assess two prerequisites independently:

- Include the Response Matrix only when a prior issue log or other documented
  position exists; otherwise disclose the missing baseline and do not assign a
  response grade.
- Include the Post-Edit Scan whenever Track Changes, another identifiable edit,
  or a prior/current version comparison exists, even if there is no prior issue
  log. If edits cannot be identified, state that limitation and perform only the
  available current-text risk review.

The confirmation form shape and final Word section contract are defined only in
`references/lawyer-confirmation-gate.md`; do not add those fields to the CSV
templates or collapse the four audience projections into one disposition.

## Full Report

Localize the whole template to the output language before using it. Chinese agreements should receive Chinese headings and table headers; English agreements should receive English headings and table headers by default.

```markdown
# VC/PE Transaction Agreement Review Report

## Assumptions
- Client side:
- Review scope: full text / Track Changes only
- Output mode:
- Structure: RMB onshore / offshore USD direct / offshore USD VIE
- Governing law:
- Documents reviewed:
- Missing documents:
- External data/legal research status:
- Authority registry checked on:
- Major Issue List: requested / recommended / not requested
- Output language:
- Files not substantively reviewed and why:

## Executive Summary
- Top negotiation points:
- High-risk legal/enforcement issues:
- Market outliers:
- Client decisions needed:
- Major issues to track:

## Coverage Matrix
| Clause family | Status: reviewed / not applicable / missing document / deferred | Notes |
|---|---|---|

## Cross-Document Candidate Conflicts
| Conflict ID | Family | Documents/locations | Candidate inconsistency | Resolution status |
|---|---|---|---|---|

## Issue Log
| Issue ID / No. | File/Clause | Issue | Our position | Market context | Legal basis | Authority / verification status | Risk | Proposed Revised Wording | Alternative Wording | Fallback | Needs Client Input | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
```

### Material Recommendation Field Mapping

For every material recommendation delivered through the Full Report or
issue-log CSV route, use the existing schema as follows; do not add columns:

| Required judgment evidence | Existing issue-log field |
|---|---|
| Fact dependencies, minimum questions and unresolved-variable treatment | `Needs Client Input` / `需客户确认` |
| Preferred drafting | `Proposed Revised Wording` / `建议修改` |
| Balanced drafting | `Alternative Wording` / `替代方案` |
| Minimum Acceptable drafting | `Fallback` |
| Synchronized clauses/documents | An explicit `[Synchronized changes]` / `[同步修改]` block inside `Proposed Revised Wording` / `建议修改`, or a mandatory companion Issue Entry bearing the same stable Issue ID |

For a standalone CSV, place the complete preferred text and the synchronized
block in the same Proposed Revised Wording cell, for example:

```text
[Preferred drafting] [complete wording]
[Synchronized changes] [definitions, related clauses/documents, or not applicable]
```

If cell length or formatting makes that impractical, the CSV must cross-reference
a companion Issue Entry with the same stable Issue ID; that entry must contain
the complete synchronized block. Structural validators check field presence and
shape only. They cannot prove that a fact question is decision-relevant, the
three tiers are substantively distinct, or synchronized changes are complete.

## Major Issue List

Use this table for material negotiation points only. Ordinary drafting cleanups should stay in the issue log or comments.
For Chinese agreements, translate the column headers into Chinese; keep the table to five columns.

```markdown
| Issue ID | Major Issue / Clause | Our Position | Counterparty Position / Status | Next Step / Fallback |
|---|---|---|---|---|
```

Status values: Open, Partially Accepted, Accepted, Rejected, New Counterparty Issue, Reopened, Deferred, Closed.
Chinese status values: 待处理、部分接受、已接受、已拒绝、对方新增问题、重新开启、暂缓、已关闭。
Do not add more than five columns; compress details into the five cells.

## Issue Entry

```markdown
### Issue [stable Issue ID]: [short title]

- Agreement location:
- Current text:
- Issue:
- Our position:
- Market data: Based on historical statistics for comparable VC/PE projects, [data].
- Legal basis: [include only if legal/enforcement issue; omit for purely commercial issues]
- Authority / verification status: [effective and verified / effective guidance / draft-nonbinding / pending legal research / practicing lawyer consultation required]
- Legal notice: [涉及中国法律相关事项，请咨询执业中国律师；涉及非中国法管辖事项，请咨询相应法域的执业律师。]
- Risk level:
- Fact dependencies / minimum questions / unanswered-variable treatment: [mirrors `Needs Client Input` / `需客户确认`]
- Preferred revised wording: [mirrors `Proposed Revised Wording` / `建议修改`]

> [Complete preferred clause wording.]
>
> [Synchronized changes] / [同步修改]: [definitions, related clauses/documents, or explicit not applicable]

- Balanced revised wording: [mirrors `Alternative Wording` / `替代方案`; complete wording when a genuine negotiation range exists]
- Minimum Acceptable revised wording: [mirrors `Fallback`; complete wording when a genuine negotiation range exists]
- Three-tier drafting not applicable because: [reason, if applicable]
```

## Comment Text

Use Chinese labels for Chinese agreements and English labels for English agreements.

```text
Issue ID: [stable Issue ID; see companion Issue Entry/issue log for a material recommendation]
Issue: [one sentence]
Our position: [client side]
Market context: Based on historical statistics for comparable VC/PE projects, [data].
Legal basis: [omit if not legal]
Authority / verification status: [required if legal]
Proposed revised wording: [complete preferred wording including its `[Synchronized changes]` / `[同步修改]` block, or cross-reference the stable Issue ID]
Alternative wording: [balanced wording, or cross-reference the stable Issue ID]
Fallback: [Minimum Acceptable wording, or cross-reference the stable Issue ID]
Client/counterparty question: [fact dependencies/minimum questions, or cross-reference the stable Issue ID]
```

For comment-only delivery, every material recommendation must have a companion
Issue Entry or issue-log row using the field mapping above, and its Comment Text
must contain the same stable Issue ID. `scripts/make_comment_plan.py`
deterministically adds localized Issue ID and Alternative Wording / 替代方案 lines
when those source fields are populated, preserves the nine-column comment-plan
shape, and carries any `[Synchronized changes]` / `[同步修改]` block already inside
Proposed Revised Wording / 建议修改. The native comment may stay concise by
cross-referencing its stable Issue ID. Generator success and a comment alone do
not prove Gate 5's fact, drafting-tier or synchronization judgments; the
companion Issue Entry/log must be delivered with the comments.

For native Word insertion, `Anchor Text` / `锚定文本` is an additional delivery
field. It must be a unique verbatim excerpt from the current visible document,
not the clause label or current-text summary unless that exact string is unique.
Deliver the separate commented `.docx` together with its apply report containing:

- source and output paths plus SHA-256 hashes;
- source and output visible-text hashes;
- requested, inserted, missing, and ambiguous anchor counts;
- inserted comment IDs;
- OOXML structure verification status.

Record render inspection separately, including source/reviewed page counts,
visual differences and any rendering limitation.

## Counterparty Markup Review

```markdown
# Counterparty Markup Review

## Assumptions and Version Chain
- Current round and file:
- Prior draft / issue log / Major Issue List used:
- Prior issue/position baseline exists: yes / no
- Identifiable edits or prior/current version comparison exists: yes / no
- Missing baseline materials and resulting limitations:
- Files not substantively reviewed:

## Executive Summary
- Accepted / closed issues:
- Still-open major issues:
- New counterparty issues:
- Points requiring client decision:

## Major Issue List Updates
| Issue ID | Major Issue / Clause | Our Position | Counterparty Position / Status | Next Step / Fallback |
|---|---|---|---|---|

## Response Matrix
<!-- Include only when a prior issue log or documented position exists. -->
| Issue ID | Original Concern | Revision Evidence | Response Status | Residual / New Risk | Synchronized Clauses | Next Step |
|---|---|---|---|---|---|---|

## Post-Edit Scan
<!-- Include whenever edits are identifiable, whether or not a prior issue/position baseline exists. -->
- Edit/version evidence used:
- Full modified text and connected documents scanned:
- Reopened issues:
- New issues:
- Alternative solutions and residual risks:
- Issues returned to fact questions / drafting tiers / synchronized changes:

## Baseline-Limited Current-Text Review
<!-- Use instead of Response Matrix when no prior issue/position baseline exists; retain Post-Edit Scan if edits are identifiable. -->
- Missing baseline and limitation:
- Current-text risks identified:
- Response grades omitted: yes

## Other Track-Change Comments
| File/Clause | Change reviewed | Issue | Recommendation | Proposed wording / fallback |
|---|---|---|---|---|
```

Do not include both Response Matrix and Baseline-Limited Current-Text Review.
Without a prior issue/position baseline, omit only Response Matrix, use the
limited current-text section, and do not infer Complete, Partial, Reopened or
any other response grade from text changes alone. Post-Edit Scan is independent:
include it whenever edits/version differences are identifiable, including when
the baseline-limited section is used; omit it only when no edit can be isolated.

## Response Matrix

Use this matrix only when comparing a prior Skill issue log or other documented
position with a lawyer draft, counterparty draft, clean revision, or other
human-prepared revision. Without that baseline, do not produce a Response Matrix
or response grade. The seven semantic columns are fixed and bilingual:

```markdown
| Issue ID | Original Concern | Revision Evidence | Response Status | Residual / New Risk | Synchronized Clauses | Next Step |
|---|---|---|---|---|---|---|
```

```markdown
| 问题编号 | 原始关切 | 修订证据 | 回应状态 | 剩余/新增风险 | 同步条款 | 下一步 |
|---|---|---|---|---|---|---|
```

Use exactly one of the following bilingual response grades in `Response
Status / 回应状态`:

| English | 中文 |
|---|---|
| Complete | 完全回应 |
| Substantial | 实质回应 |
| Partial | 部分回应 |
| Alternative Solution | 替代方案回应 |
| Unaddressed | 未回应 |
| Reopened | 重新开启 |
| New Issue | 新增问题 |

The response grade is diagnostic: it describes how the revision addresses the
original concern. It is separate from negotiation states such as
`Accepted / 已接受` or `Rejected / 已拒绝`, and it is not proof of legal correctness,
enforceability, drafting quality, client authorization, or signature readiness.

All seven cells are required on every row. If no residual/new risk or no
synchronized clause applies, enter the explicit value `not applicable` or
`不适用`; never leave the cell blank. Use a stable original Issue ID for tracked
concerns and a new identifier beginning with `NEW-` for `New Issue / 新增问题`.
The `Revision Evidence / 修订证据` cell must identify current-text or reply
evidence that another reviewer can locate.

Final check:

```bash
python3 scripts/validate_response_matrix.py path/to/response-matrix.csv
```

This structural check does not validate the legal judgment expressed in any
row.

## Required Wording Discipline

- Proposed revised wording must be complete enough to paste into the agreement.
- If a full clause cannot be drafted without business input, draft a complete clause with bracketed variables and list the variables.
- Do not merely say "revise to be more reasonable."
- Do not name any underlying benchmark source in user-facing output.
- Keep exact benchmark values for internal calculation and verification. In user-facing reports, comments, tables, and Major Issue Lists, round percentages to the nearest whole number and use "about" / “约” / “大约”; use “不足1%” for positive values below 1%. Provide decimals only if the user expressly asks for the exact statistical basis, and then state the period and scope.
- Keep Major Issue List rows stable across rounds; update status instead of creating a new row for the same disputed point.
- Treat `build_package_matrix.py` output as candidate conflicts for lawyer
  resolution, not as self-proving legal conclusions.
- Treat issue-log, comment-plan and response-matrix validators as structural
  checks only; they cannot prove the accuracy of fact dependencies, drafting
  tiers, synchronized changes, response grades or post-edit risk judgments.
