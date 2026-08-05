# Lawyer Confirmation Gate

本文件是律师确认状态、字段、导入规则和完整示例的唯一来源。确认记录只说明
用户指定律师作出了哪些决定，不核验其执业身份。全部事项数据留在当前事项目录，
不得写入 Skill、长期偏好或跨事项缓存。

## 两阶段流程与触发

第一阶段完成全文、条款族、事实依赖、法律依据和跨文件初审，形成不可变基础
清单及 Word《审阅关注点确认单》。第二阶段导入律师返回件，确定性生成 approved
content package、四类投影、report model 和最终 Word；未通过确认时只能生成草稿。

| 请求或交付 | 处理 |
|---|---|
| 供律师或客户使用的最终完整报告 | `applicability=required`，最终 Word 前完成确认 |
| 首次实质红线或根据意见改协议 | 实施前确认；实施后做变异扫描，变化时重新确认 |
| 初步问题清单、Major Issue List 或确认包 | 可先交付并标记初步/草稿，不称最终 |
| 后续比较或响应矩阵 | 可先诊断；新增或改变实质立场后，最终交付前确认 |
| 中性文件地图、可读性、纯信息提取 | 有证据地记录 `not_applicable` |
| 单条款一般知识分析，不形成项目最终意见 | 有证据地记录 `not_applicable` |
| 没有指定人类律师 | 仍可初审和生成确认包/草稿，不得称完成律师确认 |

第14步 `deliverables` 生成确认包并 autosave，等待时保持 `in_progress`；导入确认
并形成投影后才能完成。第16步 `validation` 核验全部证据。不得增加第17阶段。

## 两个用户可见维度

| 维度 | 内容 | 边界 |
|---|---|---|
| 项目事实问题 | 已有证据、最小问题、影响、未回答时处理 | 只问会改变机制、主体、审批、履约或结论的事实 |
| 法律与处理分析 | 初步判断、方案、同步范围和判断类型 | 标明法律约束、交易选择或文本执行；交易选择不是法律强制 |

同一 Issue 用一张卡，子项 ID 后缀为 `F`（事实）、`L`（法律）、`C`（交易选择）
或 `D`（文本执行）。每个子项保存 `lawyer_decision`、`lawyer_comment`、
`required_for_final` 和 `completion_impact`；整卡保存动作和四个投影。

## 决定表

| `lawyer_decision` | 含义 | 必要条件 |
|---|---|---|
| `agree` | 同意已展示分析和方案 | 动作与投影必须等于预填值 |
| `revise` | 调整分析、方案、动作或投影 | 必须说明理由；完整替代内容或完成回读 |
| `reject` | 不采纳建议 | 必须说明理由；只可保留原文或不改合同 |
| `defer_client` | 待客户/公司确认 | 不实施修改，只进入客户待决投影 |
| `defer_research` | 待法律研究/当地律师 | 不作为已批准结论，只进入法律待决投影 |
| `not_applicable` | 本项目不适用 | 必须说明理由；不修改、不对外投影 |

逐项决定优先于批量决定；例外 ID 必须列入批量卡。逐项与总体意见冲突时阻断，
不得猜测。确认导入不改变 Major Issue 谈判状态或 Response Matrix 回应等级。

## 动作表

| `drafting_action` | 结果 |
|---|---|
| `keep_current` | 保留当前合同文本 |
| `modify` | 使用已确认的完整修改文本 |
| `delete_clause` | 删除条款，但保留内部 Issue 并扫描定义、引用和关联文件 |
| `no_contract_change` | 记录结论但不改合同 |
| `not_applicable` | 不实施、不投影 |

`agree` 不得暗改动作；`defer_*` 不得实施修改；`not_applicable` 不得进入任何
对外交付物。方向性 `revise` 不产生已批准文本，直至律师回读。

## 四类投影表

| 字段 | 允许值 | 控制对象 |
|---|---|---|
| `client_report_disposition` | `include/client_pending/legal_pending/internal_only` | 客户报告 |
| `include_in_major_issue_list` | `true/false` | Major Issue List |
| `include_in_counterparty_comment` | `true/false` | 对方批注 |
| `include_in_redline` | `true/false` | 红线建议 |

四个投影独立。`internal_only` 只关闭客户报告；其他投影仍按各自字段决定。仅当
四个投影全部关闭时，Issue 才只保留在内部记录。

## Word 字段与导入合同

确认单至少含封面、说明及完成度、项目事实、法律与处理分析、常规实质批量确认、
纯文本批量确认、律师新增关注点、未确认/冲突/缺材料摘要、总体意见和签名日期。
每个可编辑字段使用 SDT，tag 固定为
`confirmation_batch_id/confirmation_id/field`。可编辑字段限于决定、律师原始
意见、动作、四个投影、批量例外、总体意见和指定新增区；原生批注不能替代决定。

导入必须同时匹配 `matter_id`、`review_round`、批次、基础清单、源文件摘要、
原生成件摘要、不可变可见内容摘要和 SDT manifest。返回 Word 完整哈希可以变化，
但风险摘要、依据、建议、可见编号和非白名单 OOXML 不得变化。语义相同的重存件
是幂等重放；同批次不同响应必须显式 supersede 当前 active import。

| 错误 | 修复 |
|---|---|
| tag 缺失、重复、未知或可见编号不符 | 从原生成件重填；不得复制/删除决定控件 |
| 响应单元格合并或结构损坏 | 恢复原卡片结构后重填 |
| 相关 Track Changes 未接受 | 接受或拒绝相关修订，再导入完整返回件 |
| 事项、轮次、批次或源摘要不符 | 使用当前事项和当前源文件重新生成确认包 |
| 同批次存在不同响应 | 指定当前 active import 的幂等键为 `--supersedes` |
| 源文件或已批准文本变化 | 将受影响确认标记 stale，重做确认和 Word QA |

## LAWYER-NEW 与回读

律师只能在指定新增区写新问题。导入器分配 `LAWYER-NEW-###`，它先是
`reread_required` 占位，不直接进入 approved content。Skill 补做事实、法律/
交易、文本和同步分析，生成新卡并由律师回读。`revise` 只有方向时也走同一回读：
保存 `reread_approved_analysis`、`reread_approved_text` 和
`reread_confirmed=true` 后才可形成最终内容。

## 完成状态

| 用户可见状态 | 条件 | 机器状态 |
|---|---|---|
| 草稿——律师确认未完成 | 必需决定空白、待回读或只生成中间稿 | `blocked` |
| 最终版 | 全部适用必需项有效确认，证据当前 | `passed` |
| 最终版（附保留事项） | 仅局部暂缓且在首页显著披露 | `passed_with_limitations` |
| 暂不能形成最终版 | 基础项待决、导入冲突、源或证据失效 | `blocked` |

`completion_impact=foundational` 的待决项永远阻断；`local` 的明确暂缓可在排除
其结论并显著披露后形成有限状态；`informational` 不计入确认分母。零适用项必须
提供负触发证据，不得把全空白当作 `not_applicable`。有限状态不得声称可签署。

## 本地命令

从 Skill 根目录运行；路径替换为当前事项本地路径，不联网安装依赖。

```bash
python3 scripts/runtime_self_check.py --confirmation-word-mode --format json
python3 scripts/validate_lawyer_confirmation.py --input path/to/base-manifest.json --json
python3 scripts/make_lawyer_confirmation_pack.py --input path/to/base-manifest.json --output-dir path/to/confirmation-pack
python3 scripts/import_lawyer_confirmation_pack.py --base-manifest path/to/base-manifest.json --pack-manifest path/to/confirmation.pack-manifest.json --returned-docx path/to/returned-confirmation.docx --output-dir path/to/import-store
python3 scripts/build_approved_content_package.py --base-manifest path/to/base-manifest.json --import-record path/to/import-current.json --import-store path/to/import-store --output path/to/approved-content.json
python3 scripts/build_report_model.py --approved-content path/to/approved-content.json --output path/to/report-model.json
python3 scripts/make_legal_review_report.py --report-model path/to/report-model.json --approved-content path/to/approved-content.json --output path/to/legal-review-report.docx
python3 scripts/validate_word_qa.py --qa path/to/final-word-qa.json --docx path/to/legal-review-report.docx --render-dir path/to/rendered --report-model path/to/report-model.json --approved-content path/to/approved-content.json
python3 scripts/validate_review_completion.py path/to/review-completion-v2.json --output path/to/completion-result.json
```

## Synthetic example

合成事项 `MATTER-SYNTHETIC` 的 `PEVC-SYNTHETIC-001` 有一个事实子项和一个
交易选择子项。律师对事实选择 `agree`，对交易选择选择 `revise` 并提供完整替代
文本；动作改为 `modify`，客户报告和红线为 true，对方批注为 false。导入器保留
律师原文，approved content 只采用已展示或完整替代文本，report model 分别生成
客户报告、Major Issue List、对方批注和红线 ID 集合。若律师只写“适当收窄”，
该 Issue 保持 `reread_required`，报告只能显示“草稿——律师确认未完成”。
