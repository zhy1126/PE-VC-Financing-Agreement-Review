# PE/VC Financing Agreement Review

面向未上市公司股权融资交易文件的 Codex Skill，支持公司/创始人方、投资人及其他交易立场。可用于增资协议、股东协议、SPA、SHA、章程、Term Sheet、Side Letter 等文件的首轮审阅、后续红线比较和跨文件一致性检查。

## v0.1.16 重点

- 先初审、再由律师确认，确认前不得生成无保留最终报告或实施实质红线。
- Word《审阅关注点确认单》分为“项目事实问题”和“法律与处理分析”。
- 支持重大事项逐项确认、常规事项和纯文本清理批量确认。
- 合同动作与客户报告、Major Issue List、对方批注、红线四类投影相互独立。
- 律师新增关注点会进入重新分析和回读，不直接成为已批准结论。
- 确认记录、来源文件、Word 内容控件和最终报告均有本地版本及完整性校验。
- 最终 Word 报告只从已批准内容包和确定性报告模型生成。
- 保留 legacy completion schema v1 读取能力；新事项使用 fail-closed schema v2。

## 仓库结构

实际 Skill 位于 [`pe-vc-transaction-docs-review/`](./pe-vc-transaction-docs-review/)：

- `SKILL.md`：入口和流程路由
- `references/`：审阅方法、条款清单和律师确认闸门
- `scripts/`：本地提取、确认单、导入、报告模型、Word 和质量校验工具
- `assets/`：问题清单、响应矩阵和完成闸门模板
- `agents/`：Codex Skill 元数据

## 安装

将 `pe-vc-transaction-docs-review` 文件夹复制到个人 Codex Skills 目录，并确保文件夹名称保持不变。安装后可运行：

```bash
python3 scripts/validate_skill_frontmatter.py SKILL.md
python3 scripts/validate_skill_consistency.py
python3 scripts/runtime_self_check.py --format json
```

如需生成和校验 Word 确认单/最终报告，请使用带 `python-docx`、OOXML 解析能力、中文字体和 LibreOffice 渲染后端的本地 Python 环境，再运行：

```bash
python3 scripts/runtime_self_check.py --confirmation-word-mode --format json
```

具体命令和状态规则见 [`references/lawyer-confirmation-gate.md`](./pe-vc-transaction-docs-review/references/lawyer-confirmation-gate.md)。

## 使用边界

本 Skill 是律师工作辅助工具，不替代负责律师的事实核验、法律判断或签署决定。任何供客户或交易对方使用的最终结论、红线、批注和报告，均应完成适用的律师确认及质量闸门。

仓库不包含客户文件、律师返回确认件、项目测试对话或事项专属决定。

