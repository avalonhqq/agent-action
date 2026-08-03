# Claim Verifier v1真实评估报告

## 评估对象

- 模型：`MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`
- 数据集：`claim_verification_dev_v1.jsonl`
- 样本：18条大会员客服原子Claim
- 模式：本地GPU真实推理，无Mock、无固定预测重放
- 阈值：entailment `0.65`，contradiction `0.70`

## 结果

| 指标 | 结果 |
|---|---:|
| 正确数 | 17 / 18 |
| Accuracy | 94.4% |
| 热路径平均耗时 | 280.8 ms / Claim |
| 危险误接受 | 0 |
| 冲突召回率 | 100% |
| 应用冷启动模型加载与三Claim验收 | 约4.8 s |

唯一失败是保守误拒：证据“部分内容存在版权限制”对声明“某些视频可能因版权限制无法观看”被判为
`unknown`，未发生把冲突或无关事实错误发布为`supported`的情况。该结果暂时保留，不能为追求100%而降低阈值。

加入`document_title`前准确率为83.3%。原因是检索正文常省略“大会员”业务主语，模型会把带主语的Claim判为
neutral。生产实现把真实检索标题拼入premise，而不是修改Claim或虚构事实，准确率提升到94.4%。

## 模型选择对比

`IDEA-CCNL/Erlangshen-Roberta-110M-NLI`同一固定集为83.3%，本轮平均约3.3秒/Claim，并对退款、卸载续费
等同义表达产生更多unknown。最终保留mDeBERTa：固定集更好、GPU热路径更快、提供safetensors且许可证明确。

## 实际问题回归

对“大会员支付后多久生效”的三条声明执行真实本地校验：

1. 支付成功后会员状态立即生效：`supported / exact_match`；
2. 未显示时等待1～5分钟并刷新或登录：`supported / nli_entailment=0.9985`；
3. 超过30分钟未到账进入订单排查：`supported / exact_match`。

总决策为`pass`。应用启动后`/ready`同时报告数据库、Redis、Milvus、Elasticsearch和Claim Verifier为ready。

端到端API复测还观察到两种Verifier上游问题：一次检索策略因相关性不足提前拒答；一次意图模型返回
`MODEL_BAD_RESPONSE`后进入既有人工复核Mock。这两次都没有执行Claim Verifier，不能归因于本模块；应在后续
意图与检索模块生产化时分别处理。
