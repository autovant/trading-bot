import unittest
import pandas as pd
import numpy as np
from src.indicators import TechnicalIndicators
from src.orderbook_indicators import OrderBookIndicators

class TestNewIndicators(unittest.TestCase):
    def test_rolling_vwap(self):
        data = pd.DataFrame({
            "high": [10, 11, 12, 13, 14],
            "low": [8, 9, 10, 11, 12],
            "close": [9, 10, 11, 12, 13],
            "volume": [100, 100, 100, 100, 100]
        })
        # Typical Price: 9, 10, 11, 12, 13
        # Volume: 100 each
        # Rolling 2
        # T=1: (9*100 + 10*100) / 200 = 9.5
        
        vwap = TechnicalIndicators.rolling_vwap(data, window=2)
        self.assertTrue(np.isnan(vwap.iloc[0]))
        self.assertAlmostEqual(vwap.iloc[1], 9.5)
        self.assertAlmostEqual(vwap.iloc[2], 10.5)

    def test_obi(self):
        ob = {
            "bids": [[100, 10], [99, 10]],
            "asks": [[101, 5], [102, 5]]
        }
        # Bid Vol = 20, Ask Vol = 10
        # OBI = (20 - 10) / 30 = 0.333
        obi = OrderBookIndicators.compute_orderbook_imbalance(ob, depth=2)
        self.assertAlmostEqual(obi, 1/3)

    def test_spread(self):
        ob = {
            "bids": [[100, 10]],
            "asks": [[101, 5]]
        }
        spread, mid, _ = OrderBookIndicators.compute_spread_and_mid(ob)
        self.assertEqual(spread, 1.0)
        self.assertEqual(mid, 100.5)

    def test_walls(self):
        ob = {
            "bids": [[100, 10], [99, 100]], # Wall at 99
            "asks": [[101, 10], [102, 10]]
        }
        # Avg bid size (top 2) = 55. Wall multiplier 3 -> threshold 165? No.
        # Logic: avg of top N.
        # If depth=2, avg = 55. 100 > 55 * 1.5? Yes.
        # Let's check default multiplier 3.0. 100 > 55 * 3? No.
        
        # Let's adjust input to have more normal levels so the wall stands out against the average
        ob = {
            "bids": [[100, 10], [99, 10], [98, 10], [97, 1000]], # Wall at 97. Avg (4 items) = (30+1000)/4 = 257.5. 1000 > 257.5 * 3 (772.5) -> True
            "asks": [[101, 10], [102, 10], [103, 10], [104, 10]]
        }
        walls = OrderBookIndicators.detect_liquidity_walls(ob, depth=4, wall_multiplier=3.0)
        self.assertTrue(walls["has_bid_wall"])
        self.assertFalse(walls["has_ask_wall"])
        self.assertEqual(walls["bid_wall_price"], 97)

if __name__ == "__main__":
    unittest.main()
