import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web

from disscloud.gateway import Gateway, is_reserved_file_path
from disscloud.web_ui import dashboard_page


class FakeCloud:
    def __init__(self):
        self.bot = {"id": "bot-1", "ownerId": "owner-1", "name": "demo", "status": "stopped", "entry": "bot.py"}
        self.env = {"API_KEY": "top-secret-value", "DISCORD_TOKEN": "discord-secret"}

    def get(self, bot_id, owner_id=None):
        return self.bot if bot_id == self.bot["id"] and owner_id == self.bot["ownerId"] else None

    def get_env(self, _bot_id, _owner_id):
        return dict(self.env)

    def set_env(self, _bot_id, _owner_id, key, value):
        if value is None:
            self.env.pop(key, None)
        else:
            self.env[key] = value

    def list(self, owner_id=None):
        return [self.bot] if owner_id in (None, self.bot["ownerId"]) else []


class FakeRequest:
    def __init__(self, *, key=None, payload=None):
        self.match_info = {"bot_id": "bot-1"}
        if key is not None:
            self.match_info["key"] = key
        self._payload = payload

    async def json(self):
        return self._payload


class SecretsApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cloud = FakeCloud()
        self.gateway = Gateway(self.cloud)
        self.auth = patch("disscloud.gateway.get_session_user", return_value={"id": "owner-1"})
        self.auth.start()

    def tearDown(self):
        self.auth.stop()

    async def test_list_returns_names_and_token_state_but_never_values(self):
        response = await self.gateway.handle_env_list(FakeRequest())
        body = response.text
        self.assertEqual({"keys": ["API_KEY"], "discordTokenConfigured": True}, json.loads(body))
        self.assertNotIn("top-secret-value", body)
        self.assertNotIn("discord-secret", body)

    async def test_put_response_does_not_echo_value(self):
        secret = "new-never-echo-this-secret"
        response = await self.gateway.handle_env_put(FakeRequest(key="NEW_KEY", payload={"value": secret}))
        self.assertEqual(secret, self.cloud.env["NEW_KEY"])
        self.assertNotIn(secret, response.text)

    async def test_invalid_json_error_does_not_echo_value(self):
        secret = "malformed-secret"

        class InvalidRequest(FakeRequest):
            async def json(self):
                raise ValueError(secret)

        with self.assertRaises(web.HTTPBadRequest) as raised:
            await self.gateway.handle_env_put(InvalidRequest(key="API_KEY"))
        self.assertNotIn(secret, raised.exception.text)

    def test_dashboard_uses_password_fields_and_contains_no_values(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("disscloud.web_ui.user_dir", return_value=Path(directory)):
                page = dashboard_page({"id": "owner-1", "username": "owner"}, self.cloud, {})
        self.assertGreaterEqual(page.count('type="password"'), 2)
        self.assertNotIn("top-secret-value", page)
        self.assertNotIn("discord-secret", page)


class ReservedPathTests(unittest.TestCase):
    def test_secrets_logs_temporary_and_internal_paths_are_reserved(self):
        for path in (".env", "cloud.log", "src/cache.tmp", ".git/config", "__pycache__/x.pyc", ".cloud-state"):
            with self.subTest(path=path):
                self.assertTrue(is_reserved_file_path(path))

    def test_normal_source_is_not_reserved(self):
        self.assertFalse(is_reserved_file_path("src/bot.py"))

    def test_windows_absolute_file_path_is_rejected(self):
        gateway = Gateway(FakeCloud())
        request = FakeRequest()
        request.match_info["path"] = r"C:\\Users\\owner\\secret.txt"
        with self.assertRaises(web.HTTPForbidden):
            gateway._file_target(request, gateway.cloud.bot)


if __name__ == "__main__":
    unittest.main()
