from __future__ import annotations

import asyncio
import contextlib
import os
import random
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import aiohttp

from . import config, runtime, store
from .urls import bot_site_url

WIN = sys.platform == "win32"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "simple-py"


def new_id() -> str:
    return f"b{int(time.time() * 1000):x}{random.randint(0, 0xFFFFF):05x}"


def sanitize_name(name: str) -> str:
    n = re.sub(r"[^\w\-ぁ-んァ-ン一-龥]", "", str(name or "").strip())[:32]
    return n or "bot"


def resolve_entry(directory: Path, preferred: str | None = None, hint: str | None = None) -> tuple[str, str]:
    return runtime.resolve_entry(directory, preferred, hint)


def _flatten_single_root(dest: Path) -> None:
    items = [p for p in dest.iterdir() if p.name != "__MACOSX"]
    if len(items) != 1 or not items[0].is_dir():
        return
    only = items[0]
    tmp = dest.with_name(dest.name + "_flat")
    only.rename(tmp)
    for child in dest.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    for child in tmp.iterdir():
        child.rename(dest / child.name)
    shutil.rmtree(tmp, ignore_errors=True)


def extract_zip_safe(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if len(names) > config.MAX_ZIP_ENTRIES:
            raise ValueError("zip のファイル数が多すぎます")
        total = 0
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if ".." in name or name.startswith("/"):
                raise ValueError("不正なパスを含む zip です")
            total += info.file_size
            if total > config.MAX_UNZIPPED_BYTES:
                raise ValueError("展開後サイズが大きすぎます")
        zf.extractall(dest)
    if zip_path.parent == dest:
        zip_path.unlink(missing_ok=True)
    _flatten_single_root(dest)


async def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession(headers={"User-Agent": "SouCloud/2.0"}) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                raise RuntimeError(f"download {resp.status}")
            with dest.open("wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)


class Cloud:
    def __init__(self) -> None:
        self.state = store.load()
        self.procs: dict[str, asyncio.subprocess.Process] = {}
        self.log_tasks: dict[str, asyncio.Task] = {}
        self.logs: dict[str, list[str]] = {}
        self._bot_locks: dict[str, asyncio.Lock] = {}
        store.ensure_dirs()

    def _bot_lock(self, bot_id: str) -> asyncio.Lock:
        """Return the lock which serializes every mutation of one bot."""
        return self._bot_locks.setdefault(bot_id, asyncio.Lock())

    def subscribe(self, owner_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to events for exactly one Discord user."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(str(owner_id), set()).add(queue)
        return queue

    def unsubscribe(self, owner_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(str(owner_id))
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(str(owner_id), None)

    def notify(self, event_type: str, *, owner_id: str, bot_id: str | None = None, state: dict | None = None) -> None:
        """Publish a deliberately small, JSON-safe event to an owner's connections."""
        event: dict[str, Any] = {
            "type": event_type,
            "ownerId": str(owner_id),
            "botId": bot_id,
            "time": int(time.time() * 1000),
            "state": state or {},
        }
        for queue in tuple(self._subscribers.get(str(owner_id), ())):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    @staticmethod
    def _public_bot(bot: dict) -> dict:
        keys = ("id", "name", "runtime", "entry", "status", "autoRestart", "createdAt", "restarts", "siteEnabled")
        return {key: bot.get(key) for key in keys}

    def _bot_event(self, event_type: str, bot: dict) -> None:
        self.notify(event_type, owner_id=bot["ownerId"], bot_id=bot["id"], state={"bot": self._public_bot(bot)})

    def notify_file_change(self, event_type: str, bot: dict, path: str) -> None:
        if event_type not in {"file.created", "file.updated", "file.deleted"}:
            raise ValueError("unknown file event")
        # Never reveal dotenv/dependency internals through the event stream.
        clean = Path(path).as_posix().lstrip("/")
        if not clean or any(part.startswith(".") for part in Path(clean).parts):
            return
        self.notify(event_type, owner_id=bot["ownerId"], bot_id=bot["id"], state={"path": clean})

    def write_file(self, bot_id: str, owner_id: str, path: str, content: str) -> None:
        bot = self.get(bot_id, owner_id)
        if not bot:
            raise ValueError("BOTが見つかりません")
        root = store.bot_dir(bot_id, owner_id).resolve()
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError as err:
            raise ValueError("不正なパスです") from err
        if any(part.startswith(".") for part in target.relative_to(root).parts):
            raise ValueError("隠しファイルは編集できません")
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.notify_file_change("file.updated" if existed else "file.created", bot, path)

    def delete_file(self, bot_id: str, owner_id: str, path: str) -> None:
        bot = self.get(bot_id, owner_id)
        if not bot:
            raise ValueError("BOTが見つかりません")
        root = store.bot_dir(bot_id, owner_id).resolve()
        target = (root / path).resolve()
        try:
            rel = target.relative_to(root)
        except ValueError as err:
            raise ValueError("不正なパスです") from err
        if not target.is_file() or any(part.startswith(".") for part in rel.parts):
            raise ValueError("ファイルが見つかりません")
        target.unlink()
        self.notify_file_change("file.deleted", bot, rel.as_posix())

    def persist(self) -> None:
        clone = {"bots": {}}
        for bot_id, bot in self.state["bots"].items():
            clone["bots"][bot_id] = {**bot, "pid": None}
        store.save(clone)

    def list(self, owner_id: str | None = None) -> list[dict]:
        bots = list(self.state["bots"].values())
        if owner_id:
            bots = [b for b in bots if b["ownerId"] == str(owner_id)]
        return bots

    def get(self, id_or_name: str, owner_id: str | None = None) -> dict | None:
        bots = self.list(owner_id)
        key = str(id_or_name).lower()
        for bot in bots:
            if bot["id"] == id_or_name:
                return bot
        for bot in bots:
            if bot["name"].lower() == key:
                return bot
        if not owner_id:
            for bot in self.state["bots"].values():
                if bot["id"] == id_or_name or bot["name"].lower() == key:
                    return bot
        return None

    def site_url(self, bot: dict) -> str:
        return bot_site_url(bot["id"], bot["name"])

    def user_storage_path(self, owner_id: str) -> Path:
        return store.ensure_user_profile(owner_id)

    def push_log(self, bot_id: str, line: str) -> None:
        buf = self.logs.setdefault(bot_id, [])
        text = str(line).replace("\r", "").rstrip()
        if not text:
            return
        for part in text.split("\n"):
            rendered = f"[{time.strftime('%H:%M:%S')}] {part}"
            buf.append(rendered)
            bot = self.state["bots"].get(bot_id)
            if bot:
                redacted = part
                for secret in self.get_env(bot_id, bot["ownerId"]).values():
                    if secret:
                        redacted = redacted.replace(secret, "[REDACTED]")
                self.notify("log.appended", owner_id=bot["ownerId"], bot_id=bot_id, state={"line": f"[{time.strftime('%H:%M:%S')}] {redacted}"})
        while len(buf) > config.LOG_BUFFER_SIZE:
            buf.pop(0)
        bot = self.state["bots"].get(bot_id)
        if bot:
            log_file = store.bot_dir(bot_id, bot["ownerId"]) / "cloud.log"
            try:
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(text + "\n")
            except OSError:
                pass

    def get_logs(self, bot_id: str, n: int = 30) -> str:
        buf = self.logs.get(bot_id, [])
        return "\n".join(buf[-n:]) or "(ログなし)"

    async def create(
        self,
        *,
        owner_id: str,
        name: str,
        username: str | None = None,
        source_url: str | None = None,
        filename: str | None = None,
        template: bool = True,
        language: str | None = None,
    ) -> dict:
        store.ensure_user_profile(owner_id, username)
        owned = self.list(owner_id)
        if len(owned) >= config.MAX_BOTS_PER_USER:
            raise ValueError(f"1人あたり {config.MAX_BOTS_PER_USER} 個までです")

        name = sanitize_name(name)
        if any(b["name"].lower() == name.lower() for b in owned):
            raise ValueError("同じ名前のBOTが既にあります")

        bot_id = new_id()
        async with self._bot_lock(bot_id):
            return await self._create_locked(
                bot_id, owner_id=str(owner_id), name=name, source_url=source_url,
                filename=filename, template=template, language=language,
            )

    async def _create_locked(
        self, bot_id: str, *, owner_id: str, name: str, source_url: str | None,
        filename: str | None, template: bool, language: str | None,
    ) -> dict:
        parent = store.user_bots_dir(owner_id)
        directory = parent / bot_id
        staging = Path(tempfile.mkdtemp(prefix=f".{bot_id}.create-", dir=parent))
        (staging / "data").mkdir()
        (staging / "public").mkdir()

        try:
            await self._populate_source(staging, source_url, filename, template, language)
            rt, entry = resolve_entry(staging, hint=language)
            staging.replace(directory)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        bot = {
            "id": bot_id,
            "name": name,
            "ownerId": str(owner_id),
            "runtime": rt,
            "entry": entry,
            "status": "stopped",
            "autoRestart": True,
            "createdAt": int(time.time() * 1000),
            "restarts": 0,
            "lastError": None,
            "siteEnabled": True,
        }
        self.state["bots"][bot_id] = bot
        try:
            self.persist()
        except BaseException:
            self.state["bots"].pop(bot_id, None)
            shutil.rmtree(directory, ignore_errors=True)
            raise
        await self.install(bot)
        return bot

    async def _populate_source(self, directory: Path, source_url: str | None,
                               filename: str | None, template: bool,
                               language: str | None) -> None:
        if source_url:
            safe_name = Path(filename or "source.bin").name
            dest = directory / safe_name
            await download(source_url, dest)
            if safe_name.lower().endswith(".zip"):
                extract_zip_safe(dest, directory)
                dest.unlink(missing_ok=True)
        elif template:
            lang = runtime.normalize_runtime(language)
            if lang and lang != "python":
                raise ValueError("Python 以外はテンプレートがありません。ソースファイルまたは zip を添付してください")
            shutil.copy2(TEMPLATES_DIR / "bot.py", directory / "bot.py")
            shutil.copy2(TEMPLATES_DIR / "requirements.txt", directory / "requirements.txt")
            if (TEMPLATES_DIR / "public").exists():
                shutil.copytree(TEMPLATES_DIR / "public", directory / "public", dirs_exist_ok=True)

    async def deploy(self, bot_id: str, *, source_url: str, filename: str | None = None,
                     language: str | None = None) -> dict:
        """Atomically replace a bot's source after fully extracting and validating it."""
        async with self._bot_lock(bot_id):
            bot = self.state["bots"].get(bot_id)
            if not bot:
                raise ValueError("BOTが見つかりません")
            target = store.bot_dir(bot_id, bot["ownerId"])
            staging = Path(tempfile.mkdtemp(prefix=f".{bot_id}.deploy-", dir=target.parent))
            backup = target.with_name(f".{target.name}.backup")
            try:
                # Runtime data and secrets survive a source deployment.
                for name in ("data", ".env", "cloud.log"):
                    old = target / name
                    if old.is_dir(): shutil.copytree(old, staging / name)
                    elif old.exists(): shutil.copy2(old, staging / name)
                (staging / "public").mkdir(exist_ok=True)
                await self._populate_source(staging, source_url, filename, False, language)
                rt, entry = resolve_entry(staging, hint=language)
                backup.unlink(missing_ok=True) if backup.is_file() else shutil.rmtree(backup, ignore_errors=True)
                target.replace(backup)
                try:
                    staging.replace(target)
                except BaseException:
                    backup.replace(target)
                    raise
                old_runtime, old_entry = bot.get("runtime"), bot.get("entry")
                bot["runtime"], bot["entry"] = rt, entry
                try:
                    self.persist()
                except BaseException:
                    bot["runtime"], bot["entry"] = old_runtime, old_entry
                    shutil.rmtree(target, ignore_errors=True)
                    backup.replace(target)
                    raise
                shutil.rmtree(backup, ignore_errors=True)
                return bot
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    async def update_web(self, bot_id: str, *, source_url: str, filename: str | None = None) -> dict:
        """Atomically update public files without exposing a partial extraction."""
        async with self._bot_lock(bot_id):
            bot = self.state["bots"].get(bot_id)
            if not bot:
                raise ValueError("BOTが見つかりません")
            root = store.bot_dir(bot_id, bot["ownerId"])
            public = root / "public"
            staging = Path(tempfile.mkdtemp(prefix=".public.update-", dir=root))
            try:
                await self._populate_source(staging, source_url, filename, False, None)
                backup = root / ".public.backup"
                shutil.rmtree(backup, ignore_errors=True)
                if public.exists(): public.replace(backup)
                try: staging.replace(public)
                except BaseException:
                    if backup.exists(): backup.replace(public)
                    raise
                shutil.rmtree(backup, ignore_errors=True)
                return bot
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    async def run_cmd(self, args: list[str], cwd: Path) -> str:
        return await runtime.run_cmd(args, cwd)

    async def install(self, bot: dict) -> None:
        directory = store.bot_dir(bot["id"], bot["ownerId"])
        rt = bot.get("runtime") or "python"

        def log(line: str) -> None:
            self.push_log(bot["id"], line)

        self._bot_event("bot.deploying", bot)
        log(f"ランタイム `{rt}` を準備しています...")
        try:
            await runtime.ensure_runtime(rt, log)
            await runtime.install_dependencies(directory, rt, log)
        except Exception as err:
            log(str(err))
            bot["lastError"] = str(err)[:500]
            self.persist()
            self._bot_event("bot.deploy_failed", bot)
            return
        log("準備完了")
        self._bot_event("bot.deployed", bot)

    def env_path(self, bot_id: str, owner_id: str) -> Path:
        return store.bot_dir(bot_id, owner_id) / ".env"

    def get_env(self, bot_id: str, owner_id: str) -> dict[str, str]:
        return store.read_dotenv(self.env_path(bot_id, owner_id))

    def set_env(self, bot_id: str, owner_id: str, key: str, value: str | None) -> None:
        env = self.get_env(bot_id, owner_id)
        if not value:
            env.pop(key, None)
        else:
            env[key] = value
        path = self.env_path(bot_id, owner_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        store.write_dotenv(path, env)
        bot = self.state["bots"].get(bot_id)
        if bot and bot["ownerId"] == str(owner_id):
            self._bot_event("bot.updated", bot)

    def has_token(self, bot_id: str, owner_id: str) -> bool:
        env = self.get_env(bot_id, owner_id)
        return bool(env.get("DISCORD_TOKEN") or env.get("TOKEN") or env.get("BOT_TOKEN"))

    async def _read_stream(self, bot_id: str, stream: asyncio.StreamReader | None) -> None:
        if not stream:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            self.push_log(bot_id, line.decode("utf-8", errors="replace"))

    async def start(self, bot_id: str) -> dict:
        async with self._bot_lock(bot_id):
            return await self._start_locked(bot_id)

    async def _start_locked(self, bot_id: str) -> dict:
        bot = self.state["bots"].get(bot_id)
        if not bot:
            raise ValueError("BOTが見つかりません")
        if bot_id in self.procs:
            raise ValueError("すでに起動しています")
        if not self.has_token(bot_id, bot["ownerId"]):
            raise ValueError("トークン未設定です。/cloud token で設定してください")

        directory = store.bot_dir(bot_id, bot["ownerId"])
        stored_entry = bot.get("entry")
        if stored_entry and (directory / stored_entry).exists() and bot.get("runtime"):
            rt, entry = bot["runtime"], stored_entry
        else:
            rt, entry = resolve_entry(directory, stored_entry, bot.get("runtime"))
            bot["runtime"] = rt
            bot["entry"] = entry

        def log(line: str) -> None:
            self.push_log(bot_id, line)

        await runtime.ensure_runtime(rt, log)
        await runtime.install_dependencies(directory, rt, log)
        argv = await runtime.prepare_build(directory, rt, entry, log)
        if sys.platform != "win32":
            entry_path = directory / entry
            if entry_path.exists() and rt in ("bash", "generic"):
                entry_path.chmod(entry_path.stat().st_mode | 0o111)

        file_env = self.get_env(bot_id, bot["ownerId"])
        env = runtime.process_env(file_env)
        token = file_env.get("DISCORD_TOKEN") or file_env.get("TOKEN") or file_env.get("BOT_TOKEN")
        env["DISCORD_TOKEN"] = token or ""
        env["BOT_DATA_DIR"] = str(store.bot_data_dir(bot_id, bot["ownerId"]))
        env["BOT_PUBLIC_DIR"] = str(directory / "public")
        pip_target = directory / ".pip"
        if pip_target.exists():
            sep = ";" if WIN else ":"
            env["PYTHONPATH"] = str(pip_target) + (sep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(directory),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self.procs[bot_id] = proc
        bot["status"] = "running"
        bot["pid"] = proc.pid
        bot["lastError"] = None
        self.persist()
        self._bot_event("bot.started", bot)
        self.push_log(bot_id, f"プロセス起動 pid={proc.pid} runtime={rt} entry={entry} cmd={' '.join(argv)}")

        if proc.stdout:
            self.log_tasks[f"{bot_id}:out"] = asyncio.create_task(self._read_stream(bot_id, proc.stdout))
        if proc.stderr:
            self.log_tasks[f"{bot_id}:err"] = asyncio.create_task(self._read_stream(bot_id, proc.stderr))

        asyncio.create_task(self._watch_process(bot_id, proc))
        return bot

    async def _watch_process(self, bot_id: str, proc: asyncio.subprocess.Process) -> None:
        code = await proc.wait()
        # A delayed watcher for an old process must never discard its replacement.
        if self.procs.get(bot_id) is not proc:
            return
        self.procs.pop(bot_id, None)
        for key in (f"{bot_id}:out", f"{bot_id}:err"):
            task = self.log_tasks.pop(key, None)
            if task:
                task.cancel()

        bot = self.state["bots"].get(bot_id)
        if not bot:
            return
        bot["pid"] = None
        wanted = bot["status"] == "running"
        bot["status"] = "stopped"
        self.push_log(bot_id, f"終了 code={code}")
        self.persist()
        self._bot_event("bot.stopped", bot)

        if wanted and bot.get("autoRestart"):
            bot["restarts"] = bot.get("restarts", 0) + 1
            delay = min(15, 2 ** min(bot["restarts"], 4))
            self.push_log(bot_id, f"{delay}s 後に再起動します")
            await asyncio.sleep(delay)
            if bot_id in self.state["bots"] and bot_id not in self.procs:
                try:
                    await self.start(bot_id)
                except Exception as err:
                    self.push_log(bot_id, f"再起動失敗: {err}")

    async def stop(self, bot_id: str, *, restart_later: bool = False) -> dict:
        async with self._bot_lock(bot_id):
            return await self._stop_locked(bot_id, restart_later=restart_later)

    async def _stop_locked(self, bot_id: str, *, restart_later: bool = False) -> dict:
        bot = self.state["bots"].get(bot_id)
        if not bot:
            raise ValueError("BOTが見つかりません")
        proc = self.procs.get(bot_id)
        bot["status"] = "running" if restart_later else "stopped"
        self.persist()
        if not restart_later and not proc:
            self._bot_event("bot.stopped", bot)
        if not proc:
            return bot
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=4)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        if self.procs.get(bot_id) is proc:
            self.procs.pop(bot_id, None)
        if restart_later:
            bot["status"] = "running"
        return bot

    async def restart(self, bot_id: str) -> dict:
        async with self._bot_lock(bot_id):
            await self._stop_locked(bot_id, restart_later=True)
            return await self._start_locked(bot_id)

    async def remove(self, bot_id: str) -> None:
        async with self._bot_lock(bot_id):
            await self._remove_locked(bot_id)

    async def _remove_locked(self, bot_id: str) -> None:
        bot = self.state["bots"].get(bot_id)
        if not bot:
            return
        await self._stop_locked(bot_id)
        self.state["bots"].pop(bot_id, None)
        self.logs.pop(bot_id, None)
        self.persist()
        directory = store.bot_dir(bot_id, bot["ownerId"])
        shutil.rmtree(directory, ignore_errors=True)
        self._bot_event("bot.deleted", bot)

    async def stop_all(self) -> None:
        for bot_id in list(self.procs.keys()):
            await self.stop(bot_id)
