import uuid
from typing import Dict, List, Optional


class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, List[dict]] = {}

    def create_session(self, session_id: Optional[str] = None) -> str:
        sid = session_id or str(uuid.uuid4())
        self._sessions[sid] = []
        return sid

    def ensure_session(self, session_id: Optional[str] = None) -> str:
        if session_id and session_id in self._sessions:
            return session_id
        return self.create_session(session_id)

    def get_session(self, session_id: str) -> List[dict]:
        return self._sessions.get(session_id, [])

    def get_all_sessions(self) -> List[dict]:
        return [
            {"session_id": sid, "message_count": len(msgs)}
            for sid, msgs in self._sessions.items()
        ]

    def add_message(self, session_id: str, role: str, content: str):
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].append({"role": role, "content": content})

    def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False


session_mgr = SessionManager()
