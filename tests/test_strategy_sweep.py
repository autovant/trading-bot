import pandas as pd
import pytest

from tools.run_strategy_sweep import StrategySweeper, generate_grid


class MockDataProvider:
    async def fetch(self, symbol, interval, start, end):
        # Return a minimal valid DataFrame
        dates = pd.date_range(start="2023-01-01", periods=100, freq=f"{interval}min")
        df = pd.DataFrame(
            {
                "open": [100.0] * 100,
                "high": [101.0] * 100,
                "low": [99.0] * 100,
                "close": [100.0] * 100,
                "volume": [1000.0] * 100,
            },
            index=dates,
        )
        return df


def test_generate_grid():
    grid = generate_grid()
    assert len(grid) > 0
    assert "atrPeriod" in grid[0]


@pytest.mark.asyncio
async def test_sweeper_initialization(tmp_path):
    sweeper = StrategySweeper(["BTCUSDT"], str(tmp_path), str(tmp_path / "results"))
    assert sweeper.symbols == ["BTCUSDT"]
    assert sweeper.base_config.perps.useMultiTfAtrStrategy is True


@pytest.mark.asyncio
async def test_score_calculation(tmp_path):
    sweeper = StrategySweeper([], str(tmp_path), str(tmp_path))
    result = {
        "metrics": {
            "profit_factor": 2.0,
            "sharpe_ratio": 1.0,
            "max_drawdown": -10.0,  # 10% DD
        }
    }
    score = sweeper._calculate_score(result)
    # 2.0 + 0.5*1.0 - 0.5*(10/10) = 2.0 + 0.5 - 0.5 = 2.0
    assert score == 2.0


def test_profile_selection(tmp_path):
    sweeper = StrategySweeper([], str(tmp_path), str(tmp_path))
    configs = [
        {
            "params": {"p": 1},
            "metrics": {
                "profit_factor": 2.0,
                "sharpe_ratio": 2.0,
                "max_drawdown": -5.0,
                "total_trades": 50,
                "avg_r_multiple": 1.0,
            },
        },
        {
            "params": {"p": 2},
            "metrics": {
                "profit_factor": 1.2,
                "sharpe_ratio": 0.5,
                "max_drawdown": -20.0,
                "total_trades": 50,
                "avg_r_multiple": 1.0,
            },
        },
    ]

    cons = sweeper._select_profile(configs, "conservative")
    assert cons is not None
    assert cons["params"]["p"] == 1

    agg = sweeper._select_profile(configs, "aggressive")
    assert agg is not None
    # Config 1 is better than 2 even for aggressive, so it should pick 1
    assert agg["params"]["p"] == 1
