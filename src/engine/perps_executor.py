from __future__ import annotations

import logging
from typing import Optional

from src.exchange import ExchangeClient
from src.exchanges.zoomex_v3 import Precision

logger = logging.getLogger(__name__)


def risk_position_size(
    *,
    equity_usdt: float,
    risk_pct: float,
    stop_loss_pct: float,
    price: float,
    cash_cap: float = 0.20,
) -> float:
    if stop_loss_pct <= 0 or price <= 0 or equity_usdt <= 0:
        return 0.0
    risk_dollars = equity_usdt * risk_pct
    notional = risk_dollars / stop_loss_pct
    usd_to_deploy = min(notional, equity_usdt * cash_cap)
    return usd_to_deploy / price


def round_quantity(qty: float, precision: Precision) -> Optional[float]:
    if qty < precision.min_qty:
        return None
    step = precision.qty_step
    if step == 0:
        return qty
    rounded = round(qty / step) * step
    if rounded < precision.min_qty:
        return None
    return rounded


async def enter_long_with_brackets(
    client: ExchangeClient,
    *,
    symbol: str,
    qty: float,
    take_profit: float,
    stop_loss: float,
    position_idx: int,
    trigger_by: str,
    order_link_id: str,
) -> dict:
    logger.info(
        "Entering long %s qty=%.6f tp=%.4f sl=%.4f",
        symbol,
        qty,
        take_profit,
        stop_loss,
    )
    return await client.create_market_with_brackets(
        symbol=symbol,
        side="Buy",
        qty=qty,
        tp=take_profit,
        sl=stop_loss,
        position_idx=position_idx,
        trigger_by=trigger_by,
        order_link_id=order_link_id,
    )


async def early_exit_reduce_only(
    client: ExchangeClient,
    *,
    symbol: str,
    qty: float,
    position_idx: int,
    order_link_id: str,
) -> dict:
    logger.info("Reduce-only exit %s qty=%.6f", symbol, qty)
    return await client.close_position_reduce_only(
        symbol=symbol,
        qty=qty,
        side="Sell",
        position_idx=position_idx,
        order_link_id=order_link_id,
    )
