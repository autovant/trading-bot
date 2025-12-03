import pytest
from datetime import datetime, timezone, timedelta
from src.engine.pnl_tracker import PnLTracker


def test_pnl_tracker_initialization():
    tracker = PnLTracker()
    assert tracker.peak_equity == 0.0
    assert tracker.consecutive_losses == 0
    assert len(tracker.daily_pnl) == 0
    assert len(tracker.trade_history) == 0


def test_update_peak_equity():
    tracker = PnLTracker()
    tracker.update_peak_equity(1000.0)
    assert tracker.peak_equity == 1000.0
    
    tracker.update_peak_equity(900.0)
    assert tracker.peak_equity == 1000.0
    
    tracker.update_peak_equity(1200.0)
    assert tracker.peak_equity == 1200.0


def test_get_drawdown():
    tracker = PnLTracker()
    tracker.update_peak_equity(1000.0)
    
    drawdown = tracker.get_drawdown(900.0)
    assert drawdown == pytest.approx(0.10, rel=1e-6)
    
    drawdown = tracker.get_drawdown(800.0)
    assert drawdown == pytest.approx(0.20, rel=1e-6)
    
    drawdown = tracker.get_drawdown(1000.0)
    assert drawdown == pytest.approx(0.0, rel=1e-6)


def test_get_drawdown_zero_peak():
    tracker = PnLTracker()
    drawdown = tracker.get_drawdown(100.0)
    assert drawdown == 0.0


def test_record_trade_winning():
    tracker = PnLTracker()
    now = datetime.now(timezone.utc)
    
    tracker.record_trade(100.0, now)
    
    assert tracker.consecutive_losses == 0
    assert len(tracker.trade_history) == 1
    assert tracker.trade_history[0]["pnl"] == 100.0
    
    date_key = now.strftime("%Y-%m-%d")
    assert tracker.daily_pnl[date_key] == 100.0


def test_record_trade_losing():
    tracker = PnLTracker()
    now = datetime.now(timezone.utc)
    
    tracker.record_trade(-50.0, now)
    
    assert tracker.consecutive_losses == 1
    assert len(tracker.trade_history) == 1
    
    date_key = now.strftime("%Y-%m-%d")
    assert tracker.daily_pnl[date_key] == -50.0


def test_consecutive_losses():
    tracker = PnLTracker()
    now = datetime.now(timezone.utc)
    
    tracker.record_trade(-10.0, now)
    assert tracker.consecutive_losses == 1
    
    tracker.record_trade(-20.0, now)
    assert tracker.consecutive_losses == 2
    
    tracker.record_trade(-30.0, now)
    assert tracker.consecutive_losses == 3
    
    tracker.record_trade(50.0, now)
    assert tracker.consecutive_losses == 0


def test_daily_pnl_accumulation():
    tracker = PnLTracker()
    now = datetime.now(timezone.utc)
    
    tracker.record_trade(100.0, now)
    tracker.record_trade(-30.0, now)
    tracker.record_trade(50.0, now)
    
    date_key = now.strftime("%Y-%m-%d")
    assert tracker.daily_pnl[date_key] == pytest.approx(120.0, rel=1e-6)


def test_get_daily_pnl_current_day():
    tracker = PnLTracker()
    now = datetime.now(timezone.utc)
    
    tracker.record_trade(100.0, now)
    
    daily_pnl = tracker.get_daily_pnl()
    assert daily_pnl == 100.0


def test_get_daily_pnl_specific_date():
    tracker = PnLTracker()
    date = "2024-01-15"
    timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    
    tracker.record_trade(200.0, timestamp)
    
    daily_pnl = tracker.get_daily_pnl(date)
    assert daily_pnl == 200.0


def test_get_daily_pnl_missing_date():
    tracker = PnLTracker()
    daily_pnl = tracker.get_daily_pnl("2024-01-01")
    assert daily_pnl == 0.0


def test_cleanup_old_days():
    tracker = PnLTracker()
    
    old_date = datetime.now(timezone.utc) - timedelta(days=40)
    recent_date = datetime.now(timezone.utc) - timedelta(days=10)
    
    tracker.record_trade(100.0, old_date)
    tracker.record_trade(200.0, recent_date)
    
    assert len(tracker.daily_pnl) == 2
    
    tracker.cleanup_old_days(days_to_keep=30)
    
    assert len(tracker.daily_pnl) == 1
    recent_key = recent_date.strftime("%Y-%m-%d")
    assert recent_key in tracker.daily_pnl
