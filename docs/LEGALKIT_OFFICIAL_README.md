​为便于选手针对CAIL的一系列评测任务在本地进行测试，本次CAIL组委会提供了**评测工具包LegalKit**作为辅助，选手可以自行安装/拉取，在本地部署并通过模型本地推理、调用API、直接上传json文件等方式进行评测。需要注意的是，本工具包主要为了帮助选手理解任务设计及评测流程，**仅含有本次赛题的数据样例或训练集，不含有测试集**，选手可以根据实际需要修改评测逻辑或用于评测的基准数据，达到模拟评测的效果。



## 安装方式

​	工具包可以通过从github拉取安装：

```bash
conda create -n legalkit python=3.10 -y
conda activate legalkit
git clone https://github.com/DavidMiao1127/LegalKit.git
cd LegalKit
pip install -e .
```



## 使用方式

​	从操作方式上，本工具包支持通过命令行、配置文件与交互网页三种方式进行评测；从评测的提交方式上，支持调用本地模型（需要提供本地路径）、huggingface模型（需要提供huggingface模型标签）、API模型（需要提供API url、key以及模型名称）生成后评测，以及直接提供json文件进行评测；从评测方法上，支持本次CAIL涵盖的正确率、Rouge、Bertscore等传统指标以及LLM-as-a-Judge评测。

### 命令行评测

​	命令行支持的参数包括：

| 参数 | 类型 / 取值 | 默认值 | 功能说明 |
|------|-------------|----------------|----------|
| `--models` | 列表[str] | None（JSON 模式可省） | 模型规格：本地目录 / `hf:Org/Repo` / `api:名称` / 含多个子模型的目录。 |
| `--datasets` | 列表[str] | None（必填） | 评测数据集名称（对应 `legalkit/datasets/` 子目录）。 |
| `--accelerator` / `-a` | `vllm` / `lmdeploy` | None | 主模型生成加速后端。 |
| `--num_workers` | int | 1 | 数据并行进程数。 |
| `--tensor_parallel` | int | 1 | 张量/模型并行度（放大 GPU 需求）。 |
| `--task` | infer / eval / all | all | 阶段选择：仅生成 / 仅评估 / 二者。JSON 模式强制为 eval。 |
| `--resume` / `-r` | 路径 | – | 恢复既有运行目录（跳过已完成记录）。 |
| `--output_dir` | 路径 | ./run_output | 新运行根目录（内含时间戳子目录）。 |
| `--temperature` | float | 1.0 | 主模型采样温度。 |
| `--top_p` | float | 1.0 | 主模型 nucleus top-p。 |
| `--max_tokens` | int | 8192 | 主模型最大生成 token 数。 |
| `--sub_tasks` | 列表[str] | None | 只运行特定子任务（视数据集定义）。 |
| `--batch_size` | int | 1 | 主模型生成批大小（单 worker）。 |
| `--repetition_penalty` | float | 1.0 | 主模型重复惩罚。 |
| `--api_url` | str | None | `api:` 模型基础 URL。 |
| `--api_key` | str | None | `api:` 模型认证 Key。 |
| `--json_eval` | flag | False | 启用离线 JSON 评测模式。 |
| `--json_paths` | 列表[str] | –（需配合 json_eval） | 预测文件：单一路径或多条 `Dataset=/abs/path.json`。 |
| `--json_model_label` | str | json_eval | JSON 模式虚拟模型名（未提供 --models 时）。 |
| `--judge` | str | None | Judge 模型规格（与 --models 同格式）。 |
| `--judge_accelerator` | `vllm` / `lmdeploy` | None | Judge 模型加速后端。 |
| `--judge_tensor_parallel` | int | 1 | Judge 张量并行度。 |
| `--judge_batch_size` | int | JSON 模式=4，否则 batch_size 或 1 | Judge 生成批大小。 |
| `--judge_temperature` | float | temperature 或 0.0 | Judge 温度。 |
| `--judge_top_p` | float | top_p 或 1.0 | Judge top-p。 |
| `--judge_max_tokens` | int | max_tokens 或 512 | Judge 最大生成 tokens。 |
| `--judge_repetition_penalty` | float | repetition_penalty 或 1.0 | Judge 重复惩罚。 |
| `--judge_api_url` | str | api_url | 覆盖 Judge API URL。 |
| `--judge_api_key` | str | api_key | 覆盖 Judge API Key。 |

​	特别说明：
* 需要 GPU = `num_workers * tensor_parallel`（主模型），Judge 目前只在 worker 0 初始化。
* JSON 模式未显式提供 models 时注入 `json::<LABEL>` 伪模型。
* 目录传给 `--models` 会自动发现含 `config.json` 的子目录作为多个模型。
* `--resume` 读取原 `config.yaml` 并跳过已存在记录 ID，进行断点续评。
* Judge 参数缺省时回退到主模型对应值，但默认更偏向确定性（温度 0）。

​	使用时可直接运行`legalkit/main.py`并输入对应参数，示例如下：

```bash
# 直接调用本地模型输出选择题答案，进行task1评测
python legalkit/main.py \
  --models /path/to/model \
  --datasets CAIL2025_task1 \
  --accelerator lmdeploy \
  --num_workers 1 --tensor_parallel 1 \
  --max_tokens 4096 --temperature 0.0
```

### 配置文件评测

​	在`example`目录下提供了一系列示例配置文件，可直接在配置文件中填写参数：

```yaml
# 使用API生成答案进行评测
args:
  models: ["api:Qwen/Qwen3-8B"]
  api_url: https://api.siliconflow.cn/v1/chat/completions
  api_key: YOUR-API-KEY
  datasets: ["CAIL2025_task2"]
  temperature: 0.6
  top_p: 0.9
  max_tokens: 8192
  batch_size: 8
  repetition_penalty: 1.2
  resume: /path/to/your/resume/file
```

​	填写好参数后可以在命令行中一键评测：

```bash
python legalkit/main.py --config example/config.yaml
```

### 网页评测

​	工具包的网页实现路径在`web/`（Flask）。提供如下功能：
- 提交任务（含 JSON & Judge 配置）
- 实时任务状态
- 指标按组展示（主 / classic / judge）

<img src="web1.png" alt="web1"/>

​	![web2](web2.png)

​

​	选手可以通过以下方式在本地运行网页：

```bash
cd web
./start.sh
```
​	随后登陆浏览器访问：http://localhost:5000，便可根据网页UI提示输入评测配置，调用本地CPU、GPU一键进行评测。



## 支持任务

​	本工具包已逐步支持并开放CAIL2025全部评测任务，具体如下：

| 任务                          | 子任务                   | 支持的评测提交方式        | 支持的评测方法（指标）    |
| ----------------------------- | ------------------------ | ------------------------- | ------------------------- |
| Task1：司法考试客观题         | /                        | 模型现场生成/提交json文件 | 准确率                    |
| Task2：司法考试主观题         | /                        | 模型现场生成/提交json文件 | LLM评测                   |
| Task3：智能体法庭模拟         | 诉状生成、法庭判决       | 提交json文件              | 准确率等传统指标、LLM评测 |
| Task4：智能体模拟调解         | /                        | 提交json文件              | 准确率等传统指标、LLM评测 |
| Task5：法律数值计算           | /                        | 模型现场生成/提交json文件 | 准确率                    |
| Task6：量刑情节识别与刑期预测 | 量刑情节提取、宣告刑计算 | 提交json文件              | F1值、Winkler Score       |



## 未来路线图

​	后续该工具包还将继续完善扩充更多模块、功能，敬请关注：

- 添加更多的国内外法律领域基准数据集，以及过往年份的CAIL赛题
- 添加更多后端加速器支持
- 优化交互网页功能
- 开放评测排行榜

​	使用过程中如有任何疑问、意见或建议，欢迎在GitHub提交Issue，或直接联系CAIL2025组委会苗硕（[miaos22@mails.tsinghua.edu.cn](https://mailto:miaos22@mails.tsinghua.edu.cn/)）。
