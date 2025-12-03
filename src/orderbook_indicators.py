"""
Order book microstructure indicators.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

logger = logging.getLogger(__name__)

class OrderBookIndicators:
    """
    Calculates indicators based on order book microstructure.
    Expects CCXT-style order book format:
    {
        'bids': [[price, size], ...],
        'asks': [[price, size], ...],
        ...
    }
    """

    @staticmethod
    def compute_orderbook_imbalance(orderbook: Dict[str, Any], depth: int = 5) -> float:
        """
        Calculate Order Book Imbalance (OBI).
        
        OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        Range: [-1, 1]
        Positive = Bid dominant (Bullish)
        Negative = Ask dominant (Bearish)
        """
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            if not bids or not asks:
                return 0.0

            # Take top N levels
            bids_depth = bids[:depth]
            asks_depth = asks[:depth]

            bid_vol = sum(level[1] for level in bids_depth)
            ask_vol = sum(level[1] for level in asks_depth)

            total_vol = bid_vol + ask_vol
            
            if total_vol == 0:
                return 0.0

            imbalance = (bid_vol - ask_vol) / total_vol
            return imbalance

        except Exception as e:
            logger.error(f"Error calculating OBI: {e}")
            return 0.0

    @staticmethod
    def compute_spread_and_mid(orderbook: Dict[str, Any]) -> Tuple[float, float, float]:
        """
        Calculate top-of-book spread and mid-price.
        
        Returns:
            (spread, mid_price, spread_bps)
        """
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            if not bids or not asks:
                return 0.0, 0.0, 0.0

            best_bid = bids[0][0]
            best_ask = asks[0][0]

            spread = best_ask - best_bid
            mid_price = (best_ask + best_bid) / 2
            
            spread_bps = 0.0
            if mid_price > 0:
                spread_bps = (spread / mid_price) * 10000

            return spread, mid_price, spread_bps

        except Exception as e:
            logger.error(f"Error calculating spread/mid: {e}")
            return 0.0, 0.0, 0.0

    @staticmethod
    def detect_liquidity_walls(
        orderbook: Dict[str, Any], 
        depth: int = 10, 
        wall_multiplier: float = 3.0
    ) -> Dict[str, Any]:
        """
        Detect liquidity walls (large orders) in the order book.
        
        Returns:
            {
                "has_bid_wall": bool,
                "has_ask_wall": bool,
                "dominant_side": "bid" | "ask" | "none",
                "bid_wall_price": float | None,
                "ask_wall_price": float | None
            }
        """
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            if not bids or not asks:
                return {
                    "has_bid_wall": False,
                    "has_ask_wall": False,
                    "dominant_side": "none",
                    "bid_wall_price": None,
                    "ask_wall_price": None
                }

            # Analyze top N levels
            bids_depth = bids[:depth]
            asks_depth = asks[:depth]

            # Calculate average sizes
            avg_bid_size = np.mean([level[1] for level in bids_depth]) if bids_depth else 0
            avg_ask_size = np.mean([level[1] for level in asks_depth]) if asks_depth else 0

            has_bid_wall = False
            has_ask_wall = False
            bid_wall_price = None
            ask_wall_price = None

            # Check for walls
            for price, size in bids_depth:
                if size > avg_bid_size * wall_multiplier:
                    has_bid_wall = True
                    bid_wall_price = price
                    break # Found the highest wall

            for price, size in asks_depth:
                if size > avg_ask_size * wall_multiplier:
                    has_ask_wall = True
                    ask_wall_price = price
                    break

            dominant_side = "none"
            if has_bid_wall and not has_ask_wall:
                dominant_side = "bid"
            elif has_ask_wall and not has_bid_wall:
                dominant_side = "ask"
            elif has_bid_wall and has_ask_wall:
                # If both have walls, check which is closer or larger? 
                # For simplicity, let's say "none" or "neutral" if both exist, 
                # or maybe check relative size.
                # Let's keep it simple as requested.
                dominant_side = "neutral" 

            return {
                "has_bid_wall": has_bid_wall,
                "has_ask_wall": has_ask_wall,
                "dominant_side": dominant_side,
                "bid_wall_price": bid_wall_price,
                "ask_wall_price": ask_wall_price
            }

        except Exception as e:
            logger.error(f"Error detecting liquidity walls: {e}")
            return {
                "has_bid_wall": False,
                "has_ask_wall": False,
                "dominant_side": "none",
                "bid_wall_price": None,
                "ask_wall_price": None
            }
