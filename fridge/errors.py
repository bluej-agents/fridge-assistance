"""Allowlisted failures shared across the worker boundary; no provider text escapes."""
from openai import APIConnectionError, APITimeoutError, APIStatusError


FAILURES = {
    "model_timeout": (504, "模型响应超时，请稍后重试；不需要重新填写 Key。"),
    "model_connection": (503, "暂时连接不到模型服务，请检查网络和服务地址后重试。"),
    "model_auth": (502, "模型服务拒绝了认证，请检查本机 Key 是否有效、是否有调用权限。"),
    "model_balance": (502, "模型服务提示余额或额度不足，请到服务商账户检查后重试。"),
    "model_rate_limit": (503, "模型服务暂时限流，请稍等一会儿再试。"),
    "model_config": (502, "模型服务不接受当前模型名称或请求参数，请检查模型配置。"),
    "model_unavailable": (503, "模型服务暂时不可用，请稍后重试。"),
    "menu_incomplete": (502, "这次菜单没能在尝试次数内完成检查，请重试，或增加时间、调整食材后再试。"),
    "menu_unavailable": (422, "这次没能搭出符合条件的两道菜。可以增加时间、补充食材，或重新安排以清除换菜限制。"),
    "worker_stopped": (502, "菜单任务意外停止，请重试；如果反复出现，请重启本地服务。"),
    "unknown": (502, "本次菜单任务出现异常，请重试；如果反复出现，请联系维护者并提供下方错误编号。"),
}


class AgentFailure(RuntimeError):
    def __init__(self, code="unknown", *, diagnostics=None):
        self.code = code if isinstance(code, str) and code in FAILURES else "unknown"
        self.status_code, self.message = FAILURES[self.code]
        self.diagnostics = {
            key: value for key, value in (diagnostics.items() if isinstance(diagnostics, dict) else [])
            if key in ("steps", "drafts", "pairs", "rejected", "evaluated")
            and type(value) is int and 0 <= value <= 100
        }
        # Keep only the allowlisted code in exception arguments (including pickling).
        super().__init__(self.code)

    def __str__(self):
        return self.message


def classify_failure(error):
    """Unwrap SDK/framework errors by type and status, never parse or return raw text."""
    seen = set()
    pending = [error]
    connection = False
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, AgentFailure):
            return AgentFailure(current.code, diagnostics=current.diagnostics)
        if isinstance(current, APITimeoutError):
            return AgentFailure("model_timeout")
        if isinstance(current, APIConnectionError):
            connection = True
        if isinstance(current, APIStatusError):
            status = current.status_code
            if status in (401, 403):
                return AgentFailure("model_auth")
            if status == 402:
                return AgentFailure("model_balance")
            if status == 429:
                return AgentFailure("model_rate_limit")
            if status in (400, 404, 422):
                return AgentFailure("model_config")
            if status >= 500:
                return AgentFailure("model_unavailable")
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
    return AgentFailure("model_connection" if connection else "unknown")
