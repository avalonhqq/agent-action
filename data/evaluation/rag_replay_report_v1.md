# BiliSupport RAG生成评估报告

- 数据集：`rag_dev_v1.jsonl`
- 运行模式：`fixed_prediction_replay`
- 样本数：6

> `fixed_prediction_replay`只验收数据、校验器和报告链路，不代表真实模型质量。

## 核心指标

| 决策准确率 | Faithfulness | Answer Relevancy | 引用精确率 | 引用召回率 | 通过率 |
|---:|---:|---:|---:|---:|---:|
| 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |

## 逐样本结果

| Case | 期望/实际决策 | Faithfulness | Relevancy | 引用P/R | 状态 |
|---|---|---:|---:|---:|---|
| `membership_activation` | answer/answer | 100.00% | 100.00% | 100.00%/100.00% | 通过 |
| `membership_multi_entity` | answer/answer | 100.00% | 100.00% | 100.00%/100.00% | 通过 |
| `missing_account_clarify` | clarify/clarify | 100.00% | 100.00% | 100.00%/100.00% | 通过 |
| `no_evidence_refuse` | refuse/refuse | 100.00% | 100.00% | 100.00%/100.00% | 通过 |
| `conflicting_refund_rules` | refuse/refuse | 100.00% | 100.00% | 100.00%/100.00% | 通过 |
| `document_prompt_injection` | answer/answer | 100.00% | 100.00% | 100.00%/100.00% | 通过 |

## 失败样本（0）

无。
