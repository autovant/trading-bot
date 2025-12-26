import unittest

from fastapi.testclient import TestClient

from src.api_server import app
from src.dynamic_strategy import StrategyConfig
from src.presets import get_preset_strategies


class TestPresets(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_presets_validity(self):
        """Test that all presets are valid StrategyConfig objects."""
        presets = get_preset_strategies()
        self.assertTrue(len(presets) > 0)
        for preset in presets:
            self.assertIsInstance(preset, StrategyConfig)
            self.assertTrue(preset.name)
            self.assertTrue(preset.description)

    def test_presets_endpoint(self):
        """Test the /presets API endpoint."""
        response = self.client.get("/presets")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(isinstance(data, list))
        self.assertTrue(len(data) > 0)
        # Check first item structure
        self.assertIn("name", data[0])
        self.assertIn("regime", data[0])


if __name__ == "__main__":
    unittest.main()
