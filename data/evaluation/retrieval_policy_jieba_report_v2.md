# BiliSupport 检索策略评估报告

- 数据集：`retrieval_dev_v1.jsonl`
- 样本数：10
- 检索通道：`hybrid`
- BM25分词器：`jieba`

## 核心指标

| 决策准确率 | 回答精确率 | 错误回答率 | 负例拒答召回 | 实体覆盖率 | 补检索率 | 执行失败率 | P50 | P95 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100.00% | 100.00% | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 15.20 ms | 68.57 ms |

## 逐样本决策

| Case ID | 期望 | 实际 | 策略 | 原因 | 分数 | 证据数 | 状态 |
|---|---|---|---|---|---:|---:|---|
| `membership_activation_001` | answer | answer | `membership-query-v2` | `quality_accepted` | 0.032522 | 5 | 通过 |
| `membership_price_001` | answer | answer | `membership-query-v2` | `quality_accepted` | 0.032522 | 5 | 通过 |
| `membership_cancel_001` | answer | answer | `membership-query-v2` | `quality_accepted` | 0.032787 | 5 | 通过 |
| `membership_uninstall_001` | answer | answer | `membership-query-v2` | `quality_accepted` | 0.032266 | 5 | 通过 |
| `membership_wrong_account_001` | answer | answer | `membership-query-v2` | `quality_accepted` | 0.032787 | 5 | 通过 |
| `membership_refund_001` | answer | answer | `membership-query-v2` | `quality_accepted` | 0.032522 | 5 | 通过 |
| `membership_missing_001` | answer | answer | `membership-query-v2` | `quality_accepted` | 0.032787 | 5 | 通过 |
| `membership_video_001` | answer | answer | `membership-query-v2` | `quality_accepted` | 0.032787 | 5 | 通过 |
| `technical_no_index_001` | refuse | refuse | `global-conservative-v2` | `no_evidence` | - | 0 | 通过 |
| `membership_unknown_ticket_001` | refuse | refuse | `membership-query-v2` | `low_quality` | 0.029116 | 5 | 通过 |
