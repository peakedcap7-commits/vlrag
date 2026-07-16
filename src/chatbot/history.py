"""对话历史管理 —— 内存存储"""
from dataclasses import dataclass, field


@dataclass
class _Message:
    role: str  # "user" | "assistant"
    content: str


class ConversationManager:
    """
    对话管理器。
    一期使用内存存储，不支持持久化和多用户隔离。
    二期可替换为 Redis / 数据库存储。
    """

    def __init__(self, user_id: str = "default", conversation_id: str = "default"):
        self.user_id = user_id
        self.conversation_id = conversation_id
        self._messages: list[_Message] = []

    def add_user_message(self, message: str):
        self._messages.append(_Message(role="user", content=message))

    def add_ai_message(self, message: str):
        self._messages.append(_Message(role="assistant", content=message))

    def get_history_text(self) -> str:
        """获取格式化的对话历史字符串"""
        lines = []
        for msg in self._messages:
            role = "用户" if msg.role == "user" else "助手"
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)

    def clear(self):
        self._messages.clear()
