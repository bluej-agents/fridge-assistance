# 冰箱有招 · fridge-assistance

**把现有食材，变成下一顿饭。**

基于 [Hugging Face smolagents](https://github.com/huggingface/smolagents) 的本地厨房小工具。选择家里已有的食材，设置人数、时间和饮食偏好，安排两道家常菜，查看做法、用量和食材清单。

- 本地运行，无需注册；示例体验无需模型 Key，不调用大模型。
- Agent 模式使用你自行配置的模型服务，会产生相应 API 费用。
- 成功结果固定两道，支持 1–6 人，人数影响份量。
- 可以单独更换一道菜，另一道保持不变。
- 通过执行图解和开发者记录，查看实际工具调用、校验结果与执行代码。

当前为 **0.1 本地预览版**。它提供菜单建议，目前不提供公网托管服务。

## 快速开始

需要 Python 3.12 和 Git。Node.js 仅用于前端测试，日常运行不需要。先下载源码：

```text
git clone https://github.com/crediblezengfei-stack/fridge-assistance.git
cd fridge-assistance
```

以下命令在项目根目录执行。

Windows PowerShell：

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m fridge
```

打开 [http://127.0.0.1:7860/](http://127.0.0.1:7860/)，选择「示例体验」即可开始。退出时在终端按 `Ctrl+C`。

macOS／Linux 参考命令如下；这些平台尚待实际安装验收，`python3` 应指向 Python 3.12：

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m fridge
```

`requirements-lock.txt` 记录 Windows／Python 3.12 的依赖版本，供复现和排查使用；它不是跨平台安装已验证的承诺。需要复现该组版本时，可在新环境安装 `-r requirements-lock.txt`。

## 先体验，再连接模型

1. 点击「选择食材」，按分类勾选；支持分类全选、取消全选，也可以手动编辑或清空。
2. 设置人数、时间和「这顿不吃肉」。这里的不吃肉可以包含蛋奶。
3. 选择「示例体验」或「Agent 模式」，点击安排菜单。
4. 查看两道菜的完整做法，在清单页核对食材数量和基础调味；可复制或下载清单。
5. 不喜欢某一道，点击该菜的「重新搭配」。它会保留另一道及其位置；改变人数或食材后应重新安排整份菜单。

示例模式使用内置菜谱和确定规则，适合熟悉页面；食材组合覆盖有限。可先试「鸡蛋、番茄、白菜／2人／30分钟／不吃肉」，对应请求见 [examples/dinner.json](examples/dinner.json)。Agent 模式可以围绕输入食材拟定新菜谱，失败时不会伪装成示例结果。

两种模式成功时都恰好返回两道菜。食材或时间不足时会提示调整条件，不自动减少为一道；输入更多食材也不意味着全部都会使用。菜单会列出未用食材。主要食材必须来自本次输入，基础调味单独列出；名称匹配不能判断家里的实际库存量。

## 配置 Agent 模式

模型运行在你选择的服务商处。应用通过 smolagents 的 OpenAI 兼容客户端连接模型，并未在电脑上下载或运行本地大模型。

先停止服务，把空白模板复制为本机配置：

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

用本机编辑器填写 `.env` 中的三个字段：`MODEL_API_KEY`、`MODEL_BASE_URL`、`MODEL_ID`，然后重新启动服务。不要将 Key 写进源码、截图、公开问题或 Git 提交。

例如使用 DeepSeek 时，地址填 `https://api.deepseek.com`，模型名可填 `deepseek-flash`；Key 请使用你自己的真实配置。地址及模型示例来自 [DeepSeek 官方文档](https://api-docs.deepseek.com/api/responses)，可用模型与计费以服务商当前说明为准。更换其他兼容服务时，需要自行验证其模型和接口行为。

页面显示「配置已填写」只说明字段完整；实际连接会在生成菜单时验证。Agent 请求可能因网络、额度、模型输出或条件限制失败，页面会显示安全错误编号。可以调整食材、时间或重试。

## smolagents 在这里做了什么

模型通过 `CodeAgent` 编写受限的 Python 代码来调用项目提供的工具，而不只是返回一段聊天文本：

```text
食材与偏好
    ↓
find_recipes：查询可参考的菜谱
    ↓
compose_menu / draft_recipe：组合或拟定菜谱
    ↓
evaluate_menu：核对组合、人数用量与整餐预计时间
    ↓
应用独立复核 → 两道菜、做法和清单
```

实际执行可能重复查询或评估，工具顺序也可能不同。「这次 Agent 实际做了什么？」根据本次发生的事件整理图解；「开发者记录 · 代码与工具数据」展开查看执行代码和工具反馈。这些记录帮助理解框架的工作过程，不代表模型完整的内部思考，也不代表菜谱经过专业烹饪验证。

## 数据与运行边界

- Key 由本机 Python 服务读取；Agent 模式会把食材、偏好、任务指令和相关工具反馈发送给你配置的模型服务商，请同时了解其隐私政策。
- 应用没有账号、库存数据库、照片识别或跨设备历史同步；关闭页面前请自行保存所需清单。食材输入没有数量信息，清单数量需对照实际库存核实。
- 默认只监听 `127.0.0.1:7860`，用于本机访问。手机尺寸的页面布局不等于手机可以直接访问电脑服务，也不等于已完成手机真机验收。
- 同时只运行一个 Agent 任务，最多 6 步，总任务等待上限约 90 秒。受限解释器、独立子进程和超时控制不构成操作系统级安全沙箱；当前版本不适合直接开放到公网或接收不受信任的远程用户任务。
- 时间按顺序烹饪估算，份量和生成步骤需要结合锅具、食材状态及个人情况调整。请自行确认过敏原、保存状态和充分熟制要求，建议不能替代专业营养或食品安全判断。

## 测试与二次开发

在 Git 克隆得到的项目根目录运行离线测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/frontend.test.cjs
```

macOS／Linux 将 Python 路径换为 `.venv/bin/python`。测试使用固定模型或合成数据，不会自动调用付费模型；有一项测试通过 Git 验证忽略规则，因此运行完整套件需要 Git 工作区。

可选的浏览器排版检查为 `node tests/menu-layout.check.cjs`，需要单独安装 Playwright 和 Chromium。它使用本地页面与模拟响应，不调用模型。可在独立工具目录安装这些测试工具，通过 `NODE_PATH` 指定其模块目录，并用 `LAYOUT_BROWSER_EXECUTABLE` 指定本机 Chromium／Chrome；用 `LAYOUT_ARTIFACT_DIR` 指定截图和报告输出目录。

主要代码入口：

| 文件 | 职责 |
| --- | --- |
| [fridge/agent.py](fridge/agent.py) | CodeAgent、工具、模型配置和执行记录 |
| [fridge/planner.py](fridge/planner.py) | 请求、菜单、份量、时间和换菜校验 |
| [fridge/drafts.py](fridge/drafts.py)、[fridge/recipe_schema.py](fridge/recipe_schema.py) | 生成菜谱的结构与食材约束 |
| [fridge/server.py](fridge/server.py) | 本机 HTTP 服务与任务进程 |
| [fridge/recipes.json](fridge/recipes.json) | 示例菜谱 |
| [index.html](fridge/static/index.html)、[style.css](fridge/static/style.css)、[app.js](fridge/static/app.js) | 页面、样式与交互 |

扩展菜谱、工具或页面时，请同步维护相关测试。真实模型联调需要自行配置服务和额度，并由开发者明确启动；离线测试通过不能替代真实模型、其他平台或手机真机验证。

## 许可

项目采用 [MIT License](LICENSE)，版权署名为 `2026 冰箱有招 contributors`。依赖保留各自许可，版本、来源及特殊许可说明见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)。
