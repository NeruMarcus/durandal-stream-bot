from collections import deque


class DialogueMemory:
    def __init__(self, maxlen: int = 50):
        self._messages: deque = deque(maxlen=maxlen)

    def add(self, role: str, content: str):
        self._messages.append({"role": role, "content": content})

    def add_user(self, content: str):
        self.add("user", content)

    def add_assistant(self, content: str):
        self.add("assistant", content)

    def get_context(self, window: int = 20) -> list:
        msgs = list(self._messages)
        return msgs[-window:]
