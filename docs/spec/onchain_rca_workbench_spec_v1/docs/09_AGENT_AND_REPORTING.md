# 09 Agent and Reporting Specification

## 1. Agent 角色边界

Agent 用于解释 evidence、生成候选 findings、撰写报告草稿。

Agent 不允许：

- 调用链上数据源替代 worker；
- 编造 tx hash、地址、金额；
- 把推断写成事实；
- 输出没有 evidence_ids 的 High finding；
- 自动发布报告；
- 忽略低置信度或 blocker。

## 2. Agent 输入

RCAAgentWorker 输入必须是结构化 JSON，不是原始大段 prompt 拼接。

```json
{
  "case": {...},
  "network": {...},
  "transactions": [...],
  "evidence": [...],
  "module_outputs": {
    "acl": {...},
    "safe": {...},
    "fund_flow": {...},
    "loss": {...}
  },
  "data_quality": {...},
  "allowed_finding_types": [...]
}
```

## 3. Agent 输出

必须输出 JSON：

```json
{
  "root_cause_one_liner": "...",
  "attack_type": "access_control_abuse",
  "severity": "critical",
  "confidence": "high",
  "findings": [
    {
      "title": "...",
      "finding_type": "access_control",
      "severity": "critical",
      "confidence": "high",
      "claim": "...",
      "rationale": "...",
      "falsification": "...",
      "evidence_ids": ["ev_001", "ev_002"],
      "requires_reviewer": true
    }
  ],
  "blockers": [],
  "open_questions": []
}
```

## 4. JSON validation

RCAAgentWorker 必须用 `schemas/finding.schema.json` 校验 Agent 输出。

如果校验失败：

1. 把 raw output 保存为 artifact。
2. 用 correction prompt 重试一次。
3. 仍失败则 job failed，case 标记 `RCA_FAILED`。

## 5. 报告模板

报告必须包含：

1. TL;DR
2. 事件概述
3. 涉事方
4. 攻击时间线
5. 关键交易分析
6. 根因分析
7. 权限 / 多签 / 签名取证
8. 资金流追踪
9. 财务影响
10. 补救交易
11. 数据可靠性
12. 分析方法与查询清单
13. 附录：交易、源码路径、事件 logs

## 6. 报告生成规则

- 每个 section 从 findings/evidence/timeline 生成。
- 不允许把 rejected finding 写进报告。
- Pending finding 可以写入草稿，但必须标注“待审核”。
- Published report 只能包含 approved 或低风险 informational findings。
- 报告中所有关键金额必须带 token decimals 和来源 evidence。
- 所有地址必须保留完整地址，UI 可截断展示。

## 7. Report JSON 输出

除了 Markdown，ReportWorker 还必须生成机器可读 JSON：

```json
{
  "case_id": "case_001",
  "version": 1,
  "language": "zh-CN",
  "sections": [
    {
      "title": "TL;DR",
      "body_markdown": "...",
      "evidence_ids": ["ev_001"],
      "coverage": 1.0,
      "status": "supported"
    }
  ]
}
```

## 8. 样式要求

中文报告风格：

- 事实优先；
- 少形容词；
- 明确置信度；
- 表格表达金额、交易、角色；
- 关键函数用代码格式；
- 区分“已确认事实”和“推断”。

## 9. Prompt 文件

Prompt 存放于：

```text
prompts/rca_agent_system.md
prompts/rca_agent_json_contract.md
prompts/report_writer_zh.md
```

Agent version 必须记录到 `reports.metadata` 或 `job_runs.output`。

