from src.config import load_config
import os

# Ensure env vars are unset
if "EXCHANGE_API_KEY" in os.environ:
    del os.environ["EXCHANGE_API_KEY"]

try:
    config = load_config()
    print(f"API Key: '{config.exchange.api_key}'")
    
    # Force live mode to test validation
    config.app_mode = "live"
    # This should trigger validation if we re-validate, but pydantic validation runs on init.
    # So let's try to create a new config with live mode
    
    from src.config import TradingBotConfig
    # We need to reconstruct the dict to pass to TradingBotConfig
    # But load_config does that.
    
    # Let's just see if we can instantiate TradingBotConfig with live mode and the current api_key
    print("Attempting to validate live mode with current keys...")
    try:
        # We need to simulate what happens in set_mode
        # It sets os.environ["APP_MODE"] = "live" and calls reload_config()
        os.environ["APP_MODE"] = "live"
        config = load_config()
        print("SUCCESS: Config loaded in live mode (UNEXPECTED)")
    except Exception as e:
        print(f"FAILURE: Config failed to load (EXPECTED): {e}")

except Exception as e:
    print(f"Error: {e}")
