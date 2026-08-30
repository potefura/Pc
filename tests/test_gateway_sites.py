import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from disscloud import store
from disscloud.gateway import Gateway


class FakeCloud:
    def __init__(self, bots):
        self.bots = bots
        self.get_calls = []

    def get(self, bot_id):
        self.get_calls.append(bot_id)
        return next((bot for bot in self.bots if bot["id"] == bot_id), None)

    def list(self, owner_id=None):
        return list(self.bots)


def test_same_name_bots_are_served_only_by_id(tmp_path, monkeypatch):
    bots = [
        {"id": "bot-one", "ownerId": "owner-1", "name": "shared", "status": "running"},
        {"id": "bot-two", "ownerId": "owner-2", "name": "shared", "status": "running"},
    ]

    def bot_dir(bot_id, owner_id):
        return Path(tmp_path, owner_id, bot_id)

    monkeypatch.setattr(store, "bot_dir", bot_dir)
    for bot, content in zip(bots, ("owner one", "owner two")):
        public = bot_dir(bot["id"], bot["ownerId"]) / "public"
        public.mkdir(parents=True)
        (public / "index.html").write_text(content, encoding="utf-8")

    async def check():
        cloud = FakeCloud(bots)
        async with TestClient(TestServer(Gateway(cloud).create_app())) as client:
            first = await client.get("/s/bot-one/shared/")
            second = await client.get("/s/bot-two/shared/")
            ambiguous = await client.get("/s/shared/", allow_redirects=False)

            assert first.status == 200
            assert await first.text() == "owner one"
            assert second.status == 200
            assert await second.text() == "owner two"
            assert ambiguous.status == 404
            assert cloud.get_calls == ["bot-one", "bot-two"]

    asyncio.run(check())


def test_unique_legacy_name_redirects_to_canonical_url():
    bot = {"id": "bot-one", "ownerId": "owner-1", "name": "unique", "status": "running"}
    async def check():
        async with TestClient(TestServer(Gateway(FakeCloud([bot])).create_app())) as client:
            response = await client.get("/s/unique/", allow_redirects=False)

            assert response.status == 302
            assert response.headers["Location"].endswith("/s/bot-one/unique/")

    asyncio.run(check())


def test_canonical_url_serves_nested_static_file(tmp_path, monkeypatch):
    bot = {"id": "bot-one", "ownerId": "owner-1", "name": "display-name", "status": "running"}
    root = tmp_path / "owner-1" / "bot-one"
    nested = root / "public" / "assets"
    nested.mkdir(parents=True)
    (nested / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(store, "bot_dir", lambda _bot_id, _owner_id: root)

    async def check():
        cloud = FakeCloud([bot])
        async with TestClient(TestServer(Gateway(cloud).create_app())) as client:
            response = await client.get("/s/bot-one/any-slug/assets/app.js")

            assert response.status == 200
            assert await response.text() == "console.log('ok')"
            assert cloud.get_calls == ["bot-one"]

    asyncio.run(check())
