# 重新克隆后的数据核对

从 `https://github.com/DavidMiao1127/LegalKit.git` 完整克隆，而非使用之前下载的zip归档。当前分支main，提交 `7db1cfd97ba47011fa169c55a2437cfde548dffa`；与此前归档的提交一致。

仓库确实包含数据样例和训练数据。实际核对结果如下：

| 数据目录 | 文件数 | 内容 |
|---|---:|---|
| `data/CAIL2025` | 1 | `task1/train.json`，21,072条司法考试客观题 |
| `data/CaseGen` | 9 | 案例生成数据、提示和评价模板 |
| `data/JEC-QA` | 2 | `0_test.json` 和 `1_test.json` |
| `data/lawbench` | 44 | 法律能力基准数据 |
| `data/lexeval` | 46 | 法律能力评测数据 |
| `data/LexRAG` | 6 | 检索、问答与法律条文库数据 |

文件数包含提示和模板等辅助文件，不等于数据条数。完整路径清单在 `outputs/legalkit_dataset_inventory.json`。

CAIL2025训练文件每条包含 `answer`、`id`、`option_list`、`statement`、`subject`、`type`，用于司法考试客观题。它不是本课程选择的CAIL2026智能合同审查输入格式 `contract_id/context`，也没有合同错误定位及段落修订标签。

本次重新克隆后，在 `legalkit/` 和 `data/CAIL2025/` 中检索 `contract_id`、`missing_element`、`智能合同`、`合同审查`、`contracts.jsonl` 未发现匹配。数据模块目录也未发现CAIL2026合同审查模块。因此“工具包有训练集”成立，但不能据此认定其中已有本赛题的合同审查训练集。

重新拉取记录见 `third_party/LEGALKIT_SOURCE.json`。本项目既有合同审查代码和合成demo均保留；没有把这些旧任务的数据转换为伪造的本赛题标注。
