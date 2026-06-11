from __future__ import annotations

from app.state.session_state import SessionState


class ResponseAgent:
    name = "ResponseAgent"

    def generate(self, action_result: dict, state: SessionState) -> str:
        return action_result.get("message", "好的。")

    def smalltalk(self) -> dict:
        return {
            "agent": self.name,
            "handler": "smalltalk",
            "message": "这个问题挺有意思，不过我这边主要帮你点餐。想看看菜单或来点推荐吗？",
            "patch": {},
        }

    def fallback(self) -> dict:
        return {
            "agent": "FallbackAgent",
            "handler": "fallback",
            "message": "这句我没太理解，可以换成点菜、看菜单、问配送费或问送达时间。",
            "patch": {},
        }

