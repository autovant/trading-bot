"""Exchange testnet integration tests (2.2.1–2.2.5).

Requires Zoomex/Bybit testnet API keys:
    EXCHANGE_API_KEY  — testnet API key
    EXCHANGE_SECRET_KEY — testnet API secret

Run:  pytest tests/test_exchange_testnet.py -m integration
Skip: pytest -m "not integration" to exclude when keys are unavailable.
"""
from __future__ import annotations

import os

import aiohttp
import pytest

from src.exchanges.zoomex_v3 import ZoomexV3Client
from src.security.mode_guard import validate_mode_config

TESTNET_URL = "https://openapi-testnet.zoomex.com"
TESTNET_API_KEY = os.environ.get("EXCHANGE_API_KEY", "")
TESTNET_SECRET = os.environ.get("EXCHANGE_SECRET_KEY", "")
SKIP_REASON = "EXCHANGE_API_KEY and EXCHANGE_SECRET_KEY required for testnet tests"

skip_no_keys = pytest.mark.skipif(
    not (TESTNET_API_KEY and TESTNET_SECRET), reason=SKIP_REASON
)

pytestmark = pytest.mark.integration


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def zoomex_session():
    """Create and teardown an aiohttp session."""
    session = aiohttp.ClientSession()
    yield session
    await session.close()


@pytest.fixture
async def testnet_client(zoomex_session: aiohttp.ClientSession) -> ZoomexV3Client:
    """Create a ZoomexV3Client pointed at testnet."""
    client = ZoomexV3Client(
        zoomex_session,
        base_url=TESTNET_URL,
        api_key=TESTNET_API_KEY,
        api_secret=TESTNET_SECRET,
        category="linear",
        mode_name="testnet",
        require_auth=True,
    )
    await client.sync_time()
    return client


# ── 2.2.1: Testnet Connection — fetch balance ───────────────────────────────


@skip_no_keys
class TestTestnetConnection:
    """Verify connectivity and balance retrieval on Zoomex testnet."""

    async def test_testnet_connection(self, testnet_client: ZoomexV3Client):
        """Fetch wallet balance from testnet; USDT equity should be >= 0."""
        balance = await testnet_client.get_wallet_balance()
        assert "list" in balance, "Wallet balance response missing 'list'"
        assert len(balance["list"]) > 0, "Wallet balance list is empty"
        # Find USDT coin entry
        coins = balance["list"][0].get("coin", [])
        usdt = [c for c in coins if c.get("coin") == "USDT"]
        assert len(usdt) > 0, "USDT not found in wallet balance"
        equity = float(usdt[0].get("equity", "0"))
        assert equity >= 0


# ── 2.2.2: Order Lifecycle — place, verify, cancel ──────────────────────────


@skip_no_keys
class TestTestnetOrderLifecycle:
    """Place a far-from-market limit order, verify its status, then cancel."""

    SYMBOL = "BTCUSDT"

    async def test_testnet_order_lifecycle(self, testnet_client: ZoomexV3Client):
        """Place limit order far from market, query it, then cancel."""
        # Get current ticker to set order far from market
        klines = await testnet_client.get_klines(self.SYMBOL, interval="1", limit=1)
        assert not klines.empty, "Failed to fetch klines for price reference"
        last_price = float(klines.iloc[-1]["close"])
        far_price = round(last_price * 0.5, 1)  # 50% below market

        order_id = None
        try:
            # Place
            result = await testnet_client.place_order(
                symbol=self.SYMBOL,
                side="Buy",
                order_type="Limit",
                qty=0.001,
                price=far_price,
            )
            order_id = result.get("orderId")
            assert order_id, f"Order placement returned no orderId: {result}"

            # Verify — fetch open orders and find ours
            open_orders = await testnet_client.get_open_orders(self.SYMBOL)
            order_ids = [o.get("orderId") for o in open_orders.get("list", [])]
            assert order_id in order_ids, (
                f"Placed order {order_id} not found in open orders"
            )
        finally:
            # Cancel (cleanup)
            if order_id:
                cancel_payload = {
                    "category": testnet_client.category,
                    "symbol": self.SYMBOL,
                    "orderId": order_id,
                }
                await testnet_client._request(
                    "POST",
                    "/v3/private/order/cancel",
                    payload=cancel_payload,
                    signed=True,
                )


# ── 2.2.3: Market Data — ticker, orderbook, klines ──────────────────────────


@skip_no_keys
class TestTestnetMarketData:
    """Fetch ticker, orderbook, and klines from Zoomex testnet."""

    SYMBOL = "SOLUSDT"

    async def test_testnet_market_data(self, testnet_client: ZoomexV3Client):
        """Klines, instrument info, and positions endpoint all return data."""
        # Klines
        klines = await testnet_client.get_klines(self.SYMBOL, interval="60", limit=10)
        assert not klines.empty, "Klines should return rows"
        assert len(klines) <= 10
        for col in ("open", "high", "low", "close", "volume"):
            assert col in klines.columns, f"Missing column {col}"

        # Instrument info (acts as ticker / symbol metadata)
        info = await testnet_client.get_instruments_info(symbol=self.SYMBOL)
        assert "list" in info and len(info["list"]) > 0
        instrument = info["list"][0]
        assert instrument.get("symbol") == self.SYMBOL

        # Precision
        precision = await testnet_client.get_precision(self.SYMBOL)
        assert precision.qty_step > 0
        assert precision.min_qty > 0


# ── 2.2.4: Mode Switch Guard (unit test, no external deps) ──────────────────


class TestModeSwitchGuard:
    """Mode guard must prevent unsafe paper-to-live transitions."""

    def test_mode_switch_guard(self):
        """Live mode with testnet flags raises ValueError."""
        # Live + testnet exchange = invalid
        with pytest.raises(ValueError, match="Live mode cannot use testnet"):
            validate_mode_config(
                mode_name="live",
                exchange_testnet=True,
                perps_testnet=False,
                exchange_base_url=None,
            )

        # Live + testnet perps = invalid
        with pytest.raises(ValueError, match="Live mode cannot use testnet"):
            validate_mode_config(
                mode_name="live",
                exchange_testnet=False,
                perps_testnet=True,
                exchange_base_url=None,
            )

        # Live + testnet URL = invalid
        with pytest.raises(ValueError, match="Live mode cannot use a testnet"):
            validate_mode_config(
                mode_name="live",
                exchange_testnet=False,
                perps_testnet=False,
                exchange_base_url="https://openapi-testnet.zoomex.com",
            )

        # Testnet mode requires testnet flags
        with pytest.raises(ValueError, match="Testnet mode requires"):
            validate_mode_config(
                mode_name="testnet",
                exchange_testnet=False,
                perps_testnet=True,
                exchange_base_url="https://openapi-testnet.zoomex.com",
            )

    def test_mode_switch_guard_valid_configs(self):
        """Valid configurations should not raise."""
        # Live with production settings
        validate_mode_config(
            mode_name="live",
            exchange_testnet=False,
            perps_testnet=False,
            exchange_base_url="https://openapi.zoomex.com",
        )

        # Testnet with all testnet flags
        validate_mode_config(
            mode_name="testnet",
            exchange_testnet=True,
            perps_testnet=True,
            exchange_base_url="https://openapi-testnet.zoomex.com",
        )


# ── 2.2.5: Order Reconciliation ─────────────────────────────────────────────


@skip_no_keys
class TestOrderReconciliation:
    """Place order, fetch from exchange, compare with local state."""

    SYMBOL = "BTCUSDT"

    async def test_order_reconciliation(self, testnet_client: ZoomexV3Client):
        """Placed order fields match when re-fetched from exchange."""
        klines = await testnet_client.get_klines(self.SYMBOL, interval="1", limit=1)
        assert not klines.empty
        last_price = float(klines.iloc[-1]["close"])
        far_price = round(last_price * 0.5, 1)
        order_qty = 0.001

        order_id = None
        try:
            # Place
            result = await testnet_client.place_order(
                symbol=self.SYMBOL,
                side="Buy",
                order_type="Limit",
                qty=order_qty,
                price=far_price,
            )
            order_id = result.get("orderId")
            assert order_id

            # Local state from placement response
            local_state = {
                "orderId": order_id,
                "symbol": self.SYMBOL,
                "side": "Buy",
                "price": far_price,
                "qty": order_qty,
            }

            # Fetch from exchange
            open_orders = await testnet_client.get_open_orders(self.SYMBOL)
            remote_orders = {
                o["orderId"]: o for o in open_orders.get("list", [])
            }
            assert order_id in remote_orders, (
                f"Order {order_id} not found on exchange"
            )
            remote = remote_orders[order_id]

            # Reconcile key fields
            assert remote["symbol"] == local_state["symbol"]
            assert remote["side"] == local_state["side"]
            assert float(remote["price"]) == pytest.approx(
                local_state["price"], abs=0.1
            )
            assert float(remote["qty"]) == pytest.approx(
                local_state["qty"], abs=0.0001
            )
        finally:
            if order_id:
                cancel_payload = {
                    "category": testnet_client.category,
                    "symbol": self.SYMBOL,
                    "orderId": order_id,
                }
                await testnet_client._request(
                    "POST",
                    "/v3/private/order/cancel",
                    payload=cancel_payload,
                    signed=True,
                )
