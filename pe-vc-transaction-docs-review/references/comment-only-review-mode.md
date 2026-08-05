# Comment-Only Review Mode

Use for first-pass review unless the user expressly asks for redline.

## Principles

- Do not alter original contract text.
- Anchor each comment to a unique verbatim excerpt from the current visible
  `.docx` text. A paraphrase, clause summary, or repeated generic phrase is not
  a valid native-comment anchor.
- Keep comments lawyer-ready: concise issue, risk, proposed wording, fallback.
- Give each material recommendation a stable Issue ID, require that ID to appear
  in Comment Text, and deliver a companion Issue Entry or issue-log row. The
  comment may cross-reference that Issue ID instead of repeating the full
  fact-dependency, three-tier and synchronized-change analysis.
- Write every comment in the primary transaction-document language: Chinese for Chinese agreements, English for English agreements by default.
- Insert native Word comments only into a separate output file with
  `scripts/apply_comment_plan.py apply`; never modify the source in place.
- If native comments cannot be inserted during the current run, produce a
  comment plan table and state that insertion and DOCX verification remain
  pending.
- For major negotiation points, also add or update the Major Issue List so the same point can be tracked across later drafts.

## Comment Fields

Each comment should contain:

```text
Issue ID: [stable Issue ID; cross-reference the companion Issue Entry/issue log]
Issue:
Our position:
Market context:
Legal basis: [omit if purely commercial/non-legal]
Authority / verification status: [required if legal]
Proposed revised wording: [preferred wording with its `[Synchronized changes]` / `[同步修改]` block, or stable-Issue-ID cross-reference]
Alternative wording: [balanced wording or stable-Issue-ID cross-reference]
Fallback: [Minimum Acceptable wording or stable-Issue-ID cross-reference]
Client/counterparty question: [fact dependencies/minimum questions or stable-Issue-ID cross-reference]
```

For a material recommendation, the companion issue-log row must map fact
dependencies to `Needs Client Input / 需客户确认`, Preferred drafting to `Proposed
Revised Wording / 建议修改`, Balanced drafting to `Alternative Wording / 替代方案`,
Minimum Acceptable drafting to `Fallback`, and synchronized clauses/documents to
the `[Synchronized changes] / [同步修改]` block required by
`references/output-templates.md`. Comment-plan validation cannot prove those
substantive judgments.

`scripts/make_comment_plan.py` keeps the existing nine-column CSV shape. When
the issue-log fields are populated, it deterministically adds `Issue ID` and
`Alternative wording` in English Comment Text or `问题编号` and `替代方案` in Chinese
Comment Text; it preserves the `[Synchronized changes] / [同步修改]` block carried
inside Proposed Revised Wording / 建议修改. Generator success proves only this
structural rendering, not that the companion mapping is substantively adequate.

## Risk Labels

- High: legal invalidity/enforcement obstacle, economics materially adverse, governance deadlock, uncapped founder liability, missing core investor protection.
- Medium: negotiable market deviation, ambiguity, incomplete procedure, unfavorable but not fatal position.
- Low: drafting clarity, cross-reference, consistency, formatting, or optional cleanup.

## Comment Plan CSV Columns

Use these columns when preparing comments without inserting them into Word:

Use `assets/comment-plan-template.csv` for English output and
`assets/comment-plan-template-zh.csv` for Chinese output. Keep the nine semantic
columns stable so `scripts/make_comment_plan.py` can generate either language.
Before applying the plan, confirm that every `Anchor Text` / `锚定文本` value
occurs exactly once in the visible main-document text. `apply_comment_plan.py`
fails atomically on a missing or ambiguous anchor by default.

## Native Word Comment Workflow

1. Generate and validate the comment-plan CSV.
2. Apply comments to a new file and save the JSON apply report:

   ```bash
   python3 scripts/apply_comment_plan.py apply source.docx comments.csv \
     --output reviewed-comments.docx --report reviewed-comments.apply.json
   ```

3. Require the report to show an unchanged visible-text hash, all requested
   comments inserted, valid comment relationships/content types, and no missing
   or ambiguous anchors.
4. Render both source and reviewed files and inspect every page. A native comment
   must not alter visible agreement text or page layout.
5. Keep the source and apply report. To reverse the operation, run the `rollback`
   subcommand with that report; rollback removes only the inserted comment IDs.

Current insertion scope is the main document story and the anchor is the whole
matched paragraph. Header, footer, footnote, endnote, text-box, and exact
substring-range comments require manual Word tooling or a future extension.

## Redline Transition

Only after user approval:

- Convert accepted proposed wording into tracked changes or direct redline.
- Preserve the issue log for negotiation context.
- For multi-option wording, ask the user which version to use or choose the balanced version and explain.

## Later-Round Comments

When reviewing counterparty Track Changes:

- Anchor comments to the changed text, not only the original clause.
- State whether the change accepts, partially accepts, rejects, or reopens our prior position.
- Include the stable Issue ID in the Comment Text for every material
  recommendation; for a tracked major issue, use the same Major Issue ID.
- Do not re-argue closed points unless the new draft changes the deal economics, control position, enforceability, or cross-document consistency.
