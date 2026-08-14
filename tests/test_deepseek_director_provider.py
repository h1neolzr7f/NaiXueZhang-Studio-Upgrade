from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pixiv_ai_transport
import pixiv_launch


DEEPSEEK_CONFIG = {
    "ai": {
        "provider": "DeepSeek",
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "timeout": 30,
        "max_tokens": 1024,
    }
}


class DeepSeekDirectorProviderTests(unittest.TestCase):
    def test_provider_presets_are_reexported_by_the_pixiv_launch_facade(self) -> None:
        presets = pixiv_launch.provider_presets()["presets"]

        self.assertIn("DeepSeek", presets)
        self.assertEqual(presets["DeepSeek"]["base"], "https://api.deepseek.com/v1")

    def test_model_discovery_prefers_deepseek_environment_key_over_saved_relay_key(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "data": [
                {"id": "deepseek-v4-pro"},
                {"id": "deepseek-v4-flash"},
            ]
        }
        client = MagicMock()
        client.get.return_value = response
        context = MagicMock()
        context.__enter__.return_value = client
        context.__exit__.return_value = False

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "deepseek-environment-key"}, clear=False
        ), patch.object(pixiv_ai_transport, "DATA_DIR", Path(temp_dir)), patch.object(
            pixiv_ai_transport, "load_config", return_value=DEEPSEEK_CONFIG
        ), patch.object(
            pixiv_ai_transport, "_read_ai_secret", return_value={"api_key": "saved-relay-key"}
        ), patch.object(
            pixiv_ai_transport.httpx, "Client", return_value=context
        ):
            result = pixiv_launch.list_ai_models()

        self.assertEqual(
            result["models"], ["deepseek-v4-flash", "deepseek-v4-pro"]
        )
        self.assertEqual(
            client.get.call_args.kwargs["headers"]["Authorization"],
            "Bearer deepseek-environment-key",
        )


if __name__ == "__main__":
    unittest.main()
