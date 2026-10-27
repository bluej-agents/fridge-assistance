"""Explicit, paid live smoke check; never run as part of the offline test suite."""
import time

from . import server  # Loads the local .env, like the web server.
from .agent import model_ready
from .planner import DinnerRequest


def main():
    if not model_ready():
        print("未开始：请在本地 .env 填写 MODEL_API_KEY、MODEL_BASE_URL、MODEL_ID。")
        return 1
    start = time.monotonic()
    request = DinnerRequest(ingredients=["鸡蛋", "番茄", "白菜"], people=2,
                            minutes=30, vegetarian=True, mode="agent")
    try:
        result = server.isolated_agent(request.model_dump())
        assert result["mode"] == "agent"
        assert len(result["plan"]["dishes"]) == 2
        assert {t.get("tool") for t in result["trace"]} >= {"find_recipes", "evaluate_menu"}
    except Exception:
        # Never print raw provider exceptions: they can contain headers or credentials.
        print("未通过：请检查 Key、API 额度、模型名称和网络；本次未用示例结果代替。")
        return 1
    print(f"真实 Agent 检查通过，用时 {time.monotonic() - start:.1f} 秒。")
    print("菜单：" + "、".join(d["name"] for d in result["plan"]["dishes"]))
    print("已执行菜谱查询、菜单评估和最终校验。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
