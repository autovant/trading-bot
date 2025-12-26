import time
from datetime import datetime, timezone

from src.engine.order_id_generator import generate_order_id


def test_generate_order_id_basic():
    timestamp = datetime(2024, 1, 15, 14, 30, 45, tzinfo=timezone.utc)
    order_id = generate_order_id("BTCUSDT", "Buy", timestamp)

    assert order_id.startswith("BTCB")
    assert "143045" in order_id
    assert len(order_id) == 18


def test_generate_order_id_deterministic():
    timestamp = datetime(2024, 1, 15, 14, 30, 45, tzinfo=timezone.utc)

    order_id_1 = generate_order_id("BTCUSDT", "Buy", timestamp)
    order_id_2 = generate_order_id("BTCUSDT", "Buy", timestamp)

    assert order_id_1 == order_id_2


def test_generate_order_id_different_symbols():
    timestamp = datetime(2024, 1, 15, 14, 30, 45, tzinfo=timezone.utc)

    btc_id = generate_order_id("BTCUSDT", "Buy", timestamp)
    eth_id = generate_order_id("ETHUSDT", "Buy", timestamp)

    assert btc_id != eth_id
    assert btc_id.startswith("BTCB")
    assert eth_id.startswith("ETHB")


def test_generate_order_id_different_sides():
    timestamp = datetime(2024, 1, 15, 14, 30, 45, tzinfo=timezone.utc)

    buy_id = generate_order_id("BTCUSDT", "Buy", timestamp)
    sell_id = generate_order_id("BTCUSDT", "Sell", timestamp)

    assert buy_id != sell_id
    assert "B" in buy_id[:4]
    assert "S" in sell_id[:4]


def test_generate_order_id_different_timestamps():
    ts1 = datetime(2024, 1, 15, 14, 30, 45, tzinfo=timezone.utc)
    ts2 = datetime(2024, 1, 15, 14, 30, 46, tzinfo=timezone.utc)

    id1 = generate_order_id("BTCUSDT", "Buy", ts1)
    id2 = generate_order_id("BTCUSDT", "Buy", ts2)

    assert id1 != id2


def test_generate_order_id_with_nonce():
    timestamp = datetime(2024, 1, 15, 14, 30, 45, tzinfo=timezone.utc)

    id1 = generate_order_id("BTCUSDT", "Buy", timestamp, nonce="abc")
    id2 = generate_order_id("BTCUSDT", "Buy", timestamp, nonce="xyz")

    assert id1 != id2


def test_generate_order_id_without_timestamp():
    id1 = generate_order_id("BTCUSDT", "Buy")
    time.sleep(1.1)
    id2 = generate_order_id("BTCUSDT", "Buy")

    assert id1 != id2
    assert len(id1) == 18
    assert len(id2) == 18


def test_generate_order_id_format():
    timestamp = datetime(2024, 1, 15, 14, 30, 45, tzinfo=timezone.utc)
    order_id = generate_order_id("SOLUSDT", "Sell", timestamp)

    assert order_id.startswith("SOLS")
    assert len(order_id) == 18
    assert order_id.isalnum()
