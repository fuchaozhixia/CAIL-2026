# LegalKit 本地适配

已核实官网工具页实际加载的 [官方说明](http://cail.cipsc.org.cn/assets/tools/readme.md)，其安装地址就是 [DavidMiao1127/LegalKit](https://github.com/DavidMiao1127/LegalKit)。说明强调只有样例或训练集，没有测试集；支持任务表仍列CAIL2025。已拉取源码的 `legalkit/datasets/` 也没有本届合同审查数据集或对应官方修改评分器。

官网说明的本地原文备份为 `docs/LEGALKIT_OFFICIAL_README.md`，未改写其中的旧任务名或运行示例；项目当前命令请以本文件为准。

源码保存在 `third_party/LegalKit/`，没有修改上游文件。现已按要求删除原归档目录并通过git完整重新克隆，当前提交仍为 `7db1cfd97ba47011fa169c55a2437cfde548dffa`，来源在 `third_party/LEGALKIT_SOURCE.json`。仓库确有21,072条CAIL2025司法考试客观题训练数据及其他基准，具体见 [数据清单](LEGALKIT_DATASETS.md)。本项目添加的 `cail_review/legalkit_adapter.py` 是自编模块，不能称为官方合同审查评测器。

## 已运行的轻量离线方案

上游包入口会预加载模型和其他数据集依赖，`main.py` 还无条件导入torch，即使只用JSON也有较重依赖。本项目选择源码部署：通过 `importlib` 直接加载上游的 `datasets/base.py` 和 `storage.py`，实际使用其中的 `Task`、`BaseEvaluator` 和 `StorageManager`；不执行其GPU调度入口。无需pip安装vLLM、lmdeploy或模型权重。

```powershell
# 第一步先生成本项目的预测，运行方式见README；这里使用已生成的离线demo
python -m cail_review.legalkit_cli export --input data/demo/contracts.jsonl --gold data/demo/gold --predictions outputs/demo_rules --output outputs/legalkit_demo --label synthetic-demo
python -m cail_review.legalkit_cli evaluate --dataset outputs/legalkit_demo/dataset.json --predictions outputs/legalkit_demo/predictions.json --output outputs/legalkit_demo_eval
python -m cail_review.legalkit_cli import --dataset outputs/legalkit_demo/dataset.json --predictions outputs/legalkit_demo/predictions.json --output outputs/legalkit_demo_roundtrip
```

目录非空会拒绝覆盖；重复实验请换输出目录。结果在 `outputs/legalkit_demo_eval/json_eval/result.json`，预测分片使用上游存储模块写入并回读验证。这是本地模拟定位评价，当前规则demo定位分10.0；该分数与官方总分25.09不在同一口径，不能直接比较。

`dataset.json` 是一份可替换的本地基准：每条record含稳定整数id、完整contract及gold定位/修订；预测使用LegalKit常见的 `tasks -> task_id -> [{id,prediction}]`，其中prediction是包含比赛双输出的JSON字符串。导出保留contract_id校验，避免顺序错位后仍评分。导入可还原为比赛双JSONL，再用主CLI校验和打包。

模型/API路线仍用 `python -m cail_review run --backend llm ...`，生成后走同一导出/评测流程。样例gold自编且很小，不是正式测试；官方虚构提交示例也不能替代gold。替换为有授权且可信的人工标注开发集时，将 `--input`、`--gold`、`--predictions` 换为对应路径，`--label` 记录来源。

## 评分边界

实现定位 P/R/F1 与 `L=10Ft+30Fc+60Fm`，不按问题组全匹配，重复段落类型去重。缺类时双方均为空的F1本地约定为0。修订仅给出逐字一致性诊断，**未实现官方修改分R、总分S或封测Judge**，多参考合理修订不能用逐字匹配评价优劣。

评测集与上游存储输出包含原合同与gold，只用于初赛/开发阶段；**不得将封测请求接入此落盘流程**。封测使用单独的无持久化 `/review` 服务。

## 可选的上游完整环境

现已单独创建 `legalkit` Conda环境（Python3.10.20），并在 `third_party/LegalKit` 中成功执行完整的 `pip install -e .`。安装包含仓库声明的vLLM、lmdeploy等依赖，未采用 `--no-deps`。`import legalkit`、自带训练数据加载、`python -m legalkit.main --help` 以及 `pip check` 均已通过。GPU推理和Web服务尚未实际验证，安装成功不代表推理后端在当前硬件上可用。

```powershell
conda activate legalkit
python -m legalkit.main --help
```

解释器位置为 `E:/Python/Anaconda3/envs/legalkit/python.exe`。原有其他Conda环境未改动。在线创建曾因代理错误失败，随后使用Conda缓存离线创建成功；安装依赖使用在线pip完成。重新克隆和数据核对见 [数据清单](LEGALKIT_DATASETS.md)，安装记录在 `outputs/legalkit_installation.json`。

```powershell
git clone https://github.com/DavidMiao1127/LegalKit.git third_party/LegalKit
# 若源码已在当前目录，不需重复克隆；复现实验建议checkout上面的固定提交。
```

可将 `extensions/legalkit/CAIL2026ContractReview/` 拷入上游 `legalkit/datasets/`，将本项目根目录加入PYTHONPATH，设置 `CAIL_LEGALKIT_DATASET` 为导出的dataset绝对路径，再用上游的 `--datasets CAIL2026ContractReview --json_eval --json_paths ...`。插件导出load_tasks、Generator、Evaluator、load_json_predictions接口。已验证上游CLI可以启动，但该插件经完整入口的评测和Web功能仍未验收；当前合同审查项目使用已验证的轻量JSON命令。

若源码安装在其他位置，设置 `LEGALKIT_ROOT`；同一Python进程内不允许切换根目录。核心项目无此依赖，未拉取LegalKit时相关适配测试会跳过，其他功能仍可运行。
