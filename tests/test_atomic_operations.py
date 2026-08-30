import asyncio
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from disscloud import cloud, store


class AtomicOperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = (
            mock.patch.object(store, "DATA_DIR", root / "data"),
            mock.patch.object(store, "USERS_DIR", root / "users"),
            mock.patch.object(store, "STATE_PATH", root / "data" / "state.json"),
        )
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def make_cloud(self):
        instance = cloud.Cloud()
        bot = {"id": "b1", "name": "one", "ownerId": "u1", "runtime": "python",
               "entry": "bot.py", "status": "stopped", "autoRestart": False}
        instance.state["bots"]["b1"] = bot
        directory = store.bot_dir("b1", "u1")
        directory.mkdir(parents=True)
        (directory / "bot.py").write_text("old", encoding="utf-8")
        (directory / "public").mkdir()
        instance.persist()
        return instance

    async def test_concurrent_start_is_serialized(self):
        instance = self.make_cloud()
        active = 0
        maximum = 0

        async def fake_start(_bot_id):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.02)
            active -= 1
            return instance.state["bots"]["b1"]

        with mock.patch.object(instance, "_start_locked", side_effect=fake_start):
            await asyncio.gather(instance.start("b1"), instance.start("b1"))
        self.assertEqual(maximum, 1)

    async def test_start_waits_for_deploy(self):
        instance = self.make_cloud()
        entered = asyncio.Event()
        release = asyncio.Event()
        order = []

        async def fake_download(_url, destination):
            order.append("deploy")
            entered.set()
            await release.wait()
            destination.write_text("new", encoding="utf-8")

        async def fake_start(_bot_id):
            order.append("start")
            return instance.state["bots"]["b1"]

        with mock.patch.object(cloud, "download", side_effect=fake_download), \
             mock.patch.object(instance, "_start_locked", side_effect=fake_start):
            deploying = asyncio.create_task(instance.deploy("b1", source_url="x", filename="bot.py"))
            await entered.wait()
            starting = asyncio.create_task(instance.start("b1"))
            await asyncio.sleep(0)
            self.assertEqual(order, ["deploy"])
            release.set()
            await asyncio.gather(deploying, starting)
        self.assertEqual(order, ["deploy", "start"])

    async def test_failed_deploy_preserves_files_and_state(self):
        instance = self.make_cloud()

        async def corrupt_zip(_url, destination):
            destination.write_bytes(b"not a zip")

        before = dict(instance.state["bots"]["b1"])
        with mock.patch.object(cloud, "download", side_effect=corrupt_zip):
            with self.assertRaises(zipfile.BadZipFile):
                await instance.deploy("b1", source_url="x", filename="source.zip")
        self.assertEqual((store.bot_dir("b1", "u1") / "bot.py").read_text(), "old")
        self.assertEqual(instance.state["bots"]["b1"], before)

    def test_interrupted_save_keeps_previous_json(self):
        store.save({"bots": {"old": {}}})
        original = store.STATE_PATH.read_text(encoding="utf-8")
        with mock.patch.object(Path, "replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                store.save({"bots": {"new": {}}})
        self.assertEqual(store.STATE_PATH.read_text(encoding="utf-8"), original)
        self.assertEqual(json.loads(original), {"bots": {"old": {}}})
        self.assertEqual(list(store.DATA_DIR.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
