import tempfile
import unittest
from pathlib import Path

from disscloud.cloud import extract_zip_safe, sanitize_name
from disscloud.store import read_dotenv, write_dotenv


class CloudHelpersTest(unittest.TestCase):
    def test_sanitize_name_removes_unsafe_characters(self):
        self.assertEqual(sanitize_name(" my bot/../テスト! "), "mybotテスト")

    def test_dotenv_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            write_dotenv(path, {"DISCORD_TOKEN": "secret", "EMPTY": ""})
            self.assertEqual(read_dotenv(path), {"DISCORD_TOKEN": "secret", "EMPTY": ""})

    def test_zip_traversal_is_rejected(self):
        import zipfile

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("../outside.txt", "no")
            with self.assertRaises(ValueError):
                extract_zip_safe(archive, Path(directory) / "output")


if __name__ == "__main__":
    unittest.main()
