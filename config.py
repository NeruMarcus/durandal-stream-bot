import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    COMMENT_INTERVAL: int = int(os.getenv("COMMENT_INTERVAL", "45"))
    MONITOR_INDEX: int = int(os.getenv("MONITOR_INDEX", "1"))
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    TEMP_DIR: str = os.path.join(os.path.dirname(__file__), "temp")
    USE_RVC: bool = os.getenv("USE_RVC", "true").lower() == "true"

    TWITCH_TOKEN: str = os.getenv("TWITCH_TOKEN", "")
    TWITCH_CLIENT_ID: str = os.getenv("TWITCH_CLIENT_ID", "")
    TWITCH_CHANNEL: str = os.getenv("TWITCH_CHANNEL", "")
    TWITCH_NICK: str = os.getenv("TWITCH_NICK", "durandal_bot")
    CHAT_COOLDOWN: float = float(os.getenv("CHAT_COOLDOWN", "3.0"))
