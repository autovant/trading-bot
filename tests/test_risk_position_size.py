import pytest
from src.engine.perps_executor import risk_position_size


def test_risk_position_size_normal_case_cash_cap_binds():
    equity = 10000.0
    risk_pct = 0.01
    stop_loss_pct = 0.02
    price = 100.0
    cash_cap = 0.20
    
    qty = risk_position_size(
        equity_usdt=equity,
        risk_pct=risk_pct,
        stop_loss_pct=stop_loss_pct,
        price=price,
        cash_cap=cash_cap,
    )
    
    risk_dollars = equity * risk_pct
    notional = risk_dollars / stop_loss_pct
    max_deploy = equity * cash_cap
    expected_notional = min(notional, max_deploy)
    expected_qty = expected_notional / price
    
    assert qty == pytest.approx(expected_qty, rel=1e-6)
    assert qty == pytest.approx(20.0, rel=1e-6)


def test_risk_position_size_risk_limit_binds():
    equity = 10000.0
    risk_pct = 0.005
    stop_loss_pct = 0.02
    price = 100.0
    cash_cap = 0.50
    
    qty = risk_position_size(
        equity_usdt=equity,
        risk_pct=risk_pct,
        stop_loss_pct=stop_loss_pct,
        price=price,
        cash_cap=cash_cap,
    )
    
    risk_dollars = equity * risk_pct
    notional = risk_dollars / stop_loss_pct
    max_deploy = equity * cash_cap
    expected_notional = min(notional, max_deploy)
    expected_qty = expected_notional / price
    
    assert qty == pytest.approx(expected_qty, rel=1e-6)
    assert qty == pytest.approx(25.0, rel=1e-6)



def test_risk_position_size_zero_stop_loss():
    qty = risk_position_size(
        equity_usdt=10000.0,
        risk_pct=0.01,
        stop_loss_pct=0.0,
        price=100.0,
        cash_cap=0.20,
    )
    assert qty == 0.0


def test_risk_position_size_zero_price():
    qty = risk_position_size(
        equity_usdt=10000.0,
        risk_pct=0.01,
        stop_loss_pct=0.02,
        price=0.0,
        cash_cap=0.20,
    )
    assert qty == 0.0


def test_risk_position_size_zero_equity():
    qty = risk_position_size(
        equity_usdt=0.0,
        risk_pct=0.01,
        stop_loss_pct=0.02,
        price=100.0,
        cash_cap=0.20,
    )
    assert qty == 0.0


def test_risk_position_size_negative_inputs():
    qty = risk_position_size(
        equity_usdt=-1000.0,
        risk_pct=0.01,
        stop_loss_pct=0.02,
        price=100.0,
        cash_cap=0.20,
    )
    assert qty == 0.0
