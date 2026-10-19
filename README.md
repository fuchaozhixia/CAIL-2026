# CAIL 2026 智能合同审查

读取带段落编号（PID）的完整合同，定位错别字、上下文不一致、要素缺失，并输出段落修订及赛道要求的双 JSONL 和 ZIP 文件。

支持离线规则、大模型 API、本地 OpenAI 兼容模型服务、已有预测结果查看，以及 LegalKit 模拟评测。

**目前已验证工具链和公开示例，尚未验证官方 15 份合同、真实模型成绩或超过 25.09 基线。** 未实现官方修改分 R 和总分 S。本地参考标注不是官方标准答案，公开示例参与过开发，分数不能代表泛化能力。详见[验收范围](docs/ACCEPTANCE.md)和[验证记录](docs/VALIDATION.md)。

## 快速开始

需要 Python 3.10 或以上版本。核心功能无需安装第三方依赖。LegalKit 通过固定提交的 Git 子模块提供。

```bash
git clone --recurse-submodules https://github.com/fuchaozhixia/CAIL-2026.git
cd CAIL-2026
python view_sample_effect.py
```

脚本默认依次查找以下输入：

1. `data/raw/contracts.jsonl`：用户提供的实际合同数据。
2. `data/public_example/contracts.jsonl`：赛题网页中的 C001、C002 公开示例。
3. `data/demo/contracts.jsonl`：本项目自编的合成数据。

运行后自动打开 HTML 报告，展示每段原文、预测修订、本地参考、命中、误报和漏检。使用 `--no-open` 可以只保存报告，不打开浏览器。结果保存在 `outputs/effect_view/`。

### 完整运行与测试

```bash
python scripts/run_demo.py --require-legalkit
```

该命令依次执行数据探索、规则预测、本地评估、段落回填、HTML 报告、ZIP 打包、LegalKit 往返校验和自动测试。

如果克隆时没有获取子模块，请先执行：

```bash
git submodule update --init third_party/LegalKit
```

可选参数：

- `--dataset demo`：切换到自编合成数据。
- `--skip-tests`：跳过自动测试。
- `--output outputs/my_run`：指定新的空输出目录。

未初始化 LegalKit 时，省略 `--require-legalkit` 仍可运行核心流程，程序会明确跳过可选的适配检查。

本机已经创建 Conda 环境时，可以先执行 `conda activate legalkit`。Python 脚本支持跨平台运行，无需填写本机绝对路径。

## 数据与效果说明

- [公开说明示例](data/public_example/README.md)：从保存的项目介绍网页逐字提取 C001、C002。本项目补齐了本地参考标注，包括网页格式示例未完整列出的金额计算链问题。
- [合成演示数据](data/demo/README.md)：3 份自编合同，包含金额计算链、账户信息缺失、无错误负例和非连续 PID。
- LegalKit 含 CAIL2025 客观题训练数据 21,072 条及其他基准，不能替代本赛题的合同审查数据。详见[数据核对清单](docs/LEGALKIT_DATASETS.md)。

离线规则只覆盖固定错字、完整公司名称冲突、受限的单价乘数量及分期计算链，以及固定交付句式的期限缺失。它会根据输入数字重算并同步关联条款，但不能处理大部分真实合同问题，也不能替代完整参赛模型。

## 使用真实合同和大模型

将官方当前阶段的 `contracts.jsonl` 放入 `data/raw/`。使用前应确认具体模型符合赛事要求，即自研模型或已通过国家网信办登记备案的大模型。

模型服务需要支持 `/chat/completions` 接口，可以是本机部署的模型，也可以是远程 API。

PowerShell 配置示例：

```powershell
$env:CAIL_BASE_URL = 'http://127.0.0.1:8000/v1'
$env:CAIL_MODEL = '替换为符合赛事要求的模型ID'
$env:CAIL_API_KEY = ''

python -m cail_review run --input data/raw/contracts.jsonl --backend llm --output outputs/prelim_v1
python -m cail_review validate --input data/raw/contracts.jsonl --predictions outputs/prelim_v1
python -m cail_review package --input data/raw/contracts.jsonl --predictions outputs/prelim_v1 --output outputs/prelim_v1/submission.zip
```

密钥通过环境变量传入。远程携带密钥的接口必须使用 HTTPS。`.env.example` 仅说明变量含义，程序不会自动加载该文件。

模型模式默认每份合同调用 5 次：三类问题分别进行全文检测，再联合修订和全文复核。`--no-verify` 用于关闭复核的消融实验。超时、429 和 5xx 会重试；格式错误最多重新生成一次，失败不会被伪装为无错误。

可通过 `--max-tokens`、`--timeout` 和 `--retries` 调整参数。程序不会自动截断合同，请确保模型上下文容量足够。

### 查看真实数据的预测或效果

```bash
# 查看已有预测，不再次调用模型
python view_sample_effect.py --input data/raw/contracts.jsonl --predictions outputs/prelim_v1

# 调用模型，并与本地标准答案对照
python view_sample_effect.py --input data/raw/contracts.jsonl --gold data/raw/gold --backend llm
```

`--gold` 指向包含标准定位和修订两份 JSONL 的目录。没有标准答案时可以省略，此时只展示预测，不计算分数。

## 输出格式、校验和评估

输入每行只包含 `contract_id` 和 `context`。后者包含 `<p id="PID">正文</p>` 标记。程序保留解码后的原文字符，支持非连续整数 PID；异常格式会明确报错。

正式输出文件名固定：

- `localization_predictions.jsonl`：合同编号、升序不重叠的段落闭区间和错误类型。跨段冲突包含全部相关证据；无错误时输出空位置和 null 类型。
- `revision_predictions.jsonl`：每个 PID 一条完整最终正文。原文由程序从输入生成，类型自动取自身定位的并集。只作为证据且无需修改的段落可以省略。

校验器拒绝未知 PID、额外字段、原文不匹配、重复修订、类型不符、非空段改空以及段落标签。ZIP 根目录只放上述两份文件。格式校验通过不能证明修订语义正确。

```bash
python -m cail_review analyze --input data/raw/contracts.jsonl --output outputs/analysis.json
python -m cail_review render --input data/raw/contracts.jsonl --predictions outputs/prelim_v1 --output outputs/final_contracts.json
python -m cail_review evaluate --input data/raw/contracts.jsonl --predictions outputs/prelim_v1 --gold data/raw/gold --output outputs/metrics.json
```

定位以 `(contract_id, PID, error_type)` 为单位去重匹配：

```text
L = 10 × F_typo + 30 × F_inconsistency + 60 × F_missing_element
```

预测和标准答案都没有某类问题时，本地约定该类 F1 为 0，官方边界口径仍需确认。修订仅进行逐字一致性诊断，不能替代官方 ChERRANT、多参考冲突复核或缺失项编辑距离评分，不计算官方 R 和 S。

大模型运行还会保存输入 SHA256、模型名称、调用数、用量、耗时和审查证据简述。输出可能包含合同内容，仅保留在本地，并已被 Git 忽略。

## LegalKit

固定版本、安装情况和模拟评测命令见 [LegalKit 说明](docs/LEGALKIT.md)。轻量适配直接使用上游 `Task`、`BaseEvaluator` 和 `StorageManager`，无需安装 GPU 后端。

如需使用上游完整入口，可在独立环境中执行：

```bash
conda create -n legalkit python=3.10 -y
conda activate legalkit
cd third_party/LegalKit
pip install -e .
python -m legalkit.main --help
```

GPU 推理和 Web 服务需要按平台与硬件单独验收。本机安装成功不表示其他平台一定支持所有推理后端。

## 服务、安装与测试

```bash
# 启动本机离线服务
python -m cail_review serve --backend rules --host 127.0.0.1 --port 8080

# 安装命令行入口
python -m pip install .
cail-review --help

# 执行测试
python -m unittest discover -s tests -v
```

- `POST /review`：接收一份输入合同，返回 `contract_id`、`localization` 和 `revisions`。
- `GET /health`：检查服务是否存活。

模型服务使用相同的模型环境变量。无错误时定位为空数组；忙时返回 429，模型失败返回 503，输入不合法返回 400。服务不写请求日志、不保存合同，也不使用持久缓存。

对外监听需设置 `CAIL_SERVICE_TOKEN`，使用 `Authorization: Bearer <token>` 鉴权，并通过 HTTPS 反向代理发布。

封测仍需公网地址、符合正式公告的超时和并发配置、持续在线及真实模型确定性测试，不能保存或利用封测合同。`temperature=0` 不能保证所有模型后端逐字确定。本项目不自动部署公网服务或提交赛事平台。

GitHub Actions 配置了 Windows、Linux 和 Python 3.10、3.12 的测试及完整离线流程。私有数据、密钥、生成输出、课程 PDF 和浏览器快照不纳入仓库。

课程要求中的组队、官方提交、真实榜单成绩和独立报告仍需小组完成。参见[需求记录](docs/REQUIREMENTS.md)和[实验与报告建议](docs/EXPERIMENTS.md)。
