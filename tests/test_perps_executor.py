from src.engine.perps_executor import risk_position_size, round_quantity
from src.exchanges.zoomex_v3 import Precision


def test_risk_position_size():
    qty = risk_position_size(
        equity_usdt=1000.0,
        risk_pct=0.01,
        stop_loss_pct=0.02,
        price=100.0,
        cash_cap=0.5,
    )
    expected = (1000 * 0.01) / 0.02 / 100
    assert abs(qty - expected) < 0.001


def test_risk_position_size_capped():
    qty = risk_position_size(
        equity_usdt=1000.0,
        risk_pct=0.5,
        stop_loss_pct=0.01,
        price=100.0,
        cash_cap=0.2,
    )
    max_qty = (1000 * 0.2) / 100
    assert abs(qty - max_qty) < 0.001


def test_risk_position_size_zero_inputs():
    qty = risk_position_size(
        equity_usdt=0,
        risk_pct=0.01,
        stop_loss_pct=0.02,
        price=100.0,
    )
    assert qty == 0.0

    qty = risk_position_size(
        equity_usdt=1000.0,
        risk_pct=0.01,
        stop_loss_pct=0,
        price=100.0,
    )
    assert qty == 0.0


def test_round_quantity():
    prec = Precision(qty_step=0.01, min_qty=0.1)

    assert round_quantity(1.2345, prec) == 1.23
    assert round_quantity(0.05, prec) is None
    assert round_quantity(0.1, prec) == 0.1


def test_round_quantity_zero_step():
    prec = Precision(qty_step=0.0, min_qty=0.1)
    assert round_quantity(1.2345, prec) == 1.2345
