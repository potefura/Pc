import json
import time
from pathlib import Path

from . import config

DATA_DIR = Path(config.ROOT) / "data"
USERS_DIR = Path(config.ROOT) / "users"
STATE_PATH = DATA_DIR / "state.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    ensure_dirs()
    if not STATE_PATH.exists():
        return {"bots": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"bots": {}}


def save(state: dict) -> None:
    ensure_dirs()
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def user_dir(owner_id: str) -> Path:
    path = USERS_DIR / str(owner_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_files_dir(owner_id: str) -> Path:
    path = user_dir(owner_id) / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_bots_dir(owner_id: str) -> Path:
    path = user_dir(owner_id) / "bots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_user_profile(owner_id: str, username: str | None = None) -> Path:
    """ユーザーごとの個人フォルダとプロフィールを自動作成する。"""
    base = user_dir(owner_id)
    profile_path = base / "profile.json"
    if not profile_path.exists():
        profile = {
            "owner_id": str(owner_id),
            "username": username or "",
            "created_at": int(__import__("time").time() * 1000),
        }
        profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    elif username:
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            if profile.get("username") != username:
                profile["username"] = username
                profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
        except (json.JSONDecodeError, OSError):
            pass
    user_files_dir(owner_id)
    user_bots_dir(owner_id)
    return base


def sync_discord_profile(user: dict) -> dict:
    """Discord OAuth ログイン時にプロフィールとフォルダを同期する。"""
    owner_id = str(user["id"])
    base = user_dir(owner_id)
    profile_path = base / "profile.json"
    now = int(time.time() * 1000)
    display_name = user.get("global_name") or user.get("username") or ""
    profile = {
        "owner_id": owner_id,
        "username": user.get("username", ""),
        "global_name": display_name,
        "avatar": user.get("avatar"),
        "discriminator": user.get("discriminator", "0"),
        "last_sync_at": now,
        "sync_source": "discord_oauth",
    }
    if profile_path.exists():
        try:
            existing = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["created_at"] = existing.get("created_at", now)
        except (json.JSONDecodeError, OSError):
            profile["created_at"] = now
    else:
        profile["created_at"] = now
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    user_files_dir(owner_id)
    user_bots_dir(owner_id)
    return profile


def load_user_profile(owner_id: str) -> dict | None:
    profile_path = user_dir(owner_id) / "profile.json"
    if not profile_path.exists():
        return None
    try:
        return json.loads(profile_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def bot_dir(bot_id: str, owner_id: str | None = None) -> Path:
    if owner_id:
        return user_bots_dir(owner_id) / bot_id
    state = load()
    for bot in state.get("bots", {}).values():
        if bot.get("id") == bot_id:
            return user_bots_dir(bot["ownerId"]) / bot_id
    return USERS_DIR / "_unknown" / "bots" / bot_id


def bot_data_dir(bot_id: str, owner_id: str) -> Path:
    path = bot_dir(bot_id, owner_id) / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_dotenv(file_path: Path) -> dict[str, str]:
    if not file_path.exists():
        return {}
    env: dict[str, str] = {}
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        env[key] = value
    return env


def write_dotenv(file_path: Path, env: dict[str, str]) -> None:
    lines = [f"{k}={v}" for k, v in env.items()]
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
