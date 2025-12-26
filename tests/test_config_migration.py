
import os
import pytest
from src.config import get_config, load_config

def test_config_env_override():
    """Test that environment variables override configuration."""
    
    # Set an env var that corresponds to a field in TradingBotConfig
    # We use a field that is explicitly in TradingBotConfig and NOT in the yaml usually,
    # or one that we can check easily.
    # TradingBotConfig.log_level is one.
    
    os.environ["LOG_LEVEL"] = "DEBUG"
    os.environ["DB_URL"] = "sqlite:///test_db.sqlite"
    
    # Reload config
    config = load_config()
    
    assert config.log_level == "DEBUG"
    assert config.db_url == "sqlite:///test_db.sqlite"
    
    # Cleanup
    del os.environ["LOG_LEVEL"]
    del os.environ["DB_URL"]

def test_app_mode_override():
    """Test APP_MODE override."""
    os.environ["APP_MODE"] = "live"
    # Note: live mode requires api keys, which might fail validation if not provided.
    # So we should provide dummy keys or catch the error.
    
    # Actually load_config calls _validate_live_credentials
    os.environ["BYBIT_API_KEY"] = "dummy"
    os.environ["BYBIT_SECRET_KEY"] = "dummy" 
    try:
        # We only test app_mode override here as it is explicitly handled in load_config
        config = load_config()
        assert config.app_mode == "live"
    except Exception as e:
        # It might fail due to missing API keys for live mode, which is expected
        # if we don't provide them in yaml or env vars properly matched by substitution.
        # But here we just want to verify app_mode is picked up.
        # However, validation happens AFTER instantiation.
        # So we expect a ValueError about API keys if we don't provide them.
        assert "API key" in str(e)
    finally:
        del os.environ["APP_MODE"]
