# 开发约定

## 项目目标与边界

冰箱有招（fridge-assistance）是 Python 3.12、FastAPI、原生 HTML/CSS/JavaScript 与 smolagents CodeAgent 构成的本地厨房工具。先读 [README](README.md) 和相关代码，检查当前分支、工作区和测试环境，再开始修改。

- 示例与 Agent 的成功菜单均须恰好两道菜，支持 1–6 人；人数影响用量。条件不足时明确失败，不减少或增加菜数。
- 主要食材来自本次输入；基础调味使用允许清单。尊重不吃肉、排除菜谱和整餐时间限制；不得为成功返回而绕过最终校验。
- 单道换菜只替换目标位置，保留另一道的菜谱、用量与位置；人数或库存变化须重新验证。失败时保留原菜单，不展示部分更新。
- 示例模式不调用模型，不能把规则结果伪装为真实 Agent 成功。
- 执行图解只总结实际记录的工具事件；开发者记录展示执行代码与工具数据，不声称披露模型全部内部思考。

## 代码职责

- `fridge/agent.py`：模型连接、工具、CodeAgent 与最终校验。
- `fridge/planner.py`：请求归一、两道组合、份量、时间和保留菜校验。
- `fridge/drafts.py`、`fridge/recipe_schema.py`：生成菜谱、允许调味和数据约束。
- `fridge/server.py`：本机服务、同源边界、任务进程、超时和安全错误。
- `fridge/recipes.json`：示例菜谱；`examples/dinner.json`：示例请求。
- `fridge/static/`：页面、样式、交互；`tests/`：自动回归与可选浏览器检查。

## 配置、隐私与安全

- 不提交或展示真实 `.env`、Key、Token、认证头、用户数据或供应商原始错误。`.env.example` 中的 `MODEL_` 赋值保持空白。
- 日志与页面只显示经过分类的安全错误。新增网络工具时说明发送的数据、目标和费用，并补充相应边界测试。
- 默认监听本机回环地址；不得因调试方便移除现有主机／同源检查，或直接将服务开放到公网。
- 独立进程、6 步与约 90 秒任务限制是资源控制，不是操作系统级沙箱。修改执行权限或部署方式前先评估信任边界。
- 模型连接和付费联调必须由操作者明确启动；离线测试与默认检查不读取真实凭据发起付费请求。

## 验证与提交

完成修改后编写或更新相关测试，检查事实、文案与代码一致。Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/frontend.test.cjs
```

macOS／Linux 的 Python 路径为 `.venv/bin/python`。完整测试需要 Git 工作区；安装和平台差异请如实记录。可选浏览器检查为 `node tests/menu-layout.check.cjs`，单独配置 Playwright 和 Chromium；详见 README。

- 与改动相关的验证通过后创建对应 Git commit，以便追踪和回滚；遵守操作者明确的审阅、提交和推送范围。
- 修改行为或安装步骤时更新 README；不要留下失效的文件链接或未验证的兼容承诺。
- 报告实际执行的验证、结果、限制和未完成项。离线模型、模拟浏览器、真实模型与真机验证分别说明，不能互相替代。
- 不用 reset、清理或强推覆盖他人的改动；发现冲突先核实。推送、部署或发布按操作者授权执行。
