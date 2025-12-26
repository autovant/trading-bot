from .dynamic_strategy import (
    ConditionConfig,
    IndicatorConfig,
    RegimeConfig,
    RiskConfig,
    SetupConfig,
    SignalConfig,
    StrategyConfig,
)


def get_preset_strategies():
    """Return a list of preset strategies."""
    return [
        StrategyConfig(
            name="Trend Surfer (Golden Cross)",
            description="Classic trend following strategy using EMA crossovers and MACD confirmation. Best for trending markets.",
            regime=RegimeConfig(
                timeframe="1d",
                indicators=[IndicatorConfig(name="ema", params={"period": 200})],
                bullish_conditions=[
                    ConditionConfig(
                        indicator_a="close", operator=">", indicator_b="ema_200"
                    )
                ],
                bearish_conditions=[
                    ConditionConfig(
                        indicator_a="close", operator="<", indicator_b="ema_200"
                    )
                ],
            ),
            setup=SetupConfig(
                timeframe="4h",
                indicators=[
                    IndicatorConfig(name="ema", params={"period": 50}),
                    IndicatorConfig(name="ema", params={"period": 200}),
                ],
                bullish_conditions=[
                    ConditionConfig(
                        indicator_a="ema_50", operator=">", indicator_b="ema_200"
                    )
                ],
                bearish_conditions=[
                    ConditionConfig(
                        indicator_a="ema_50", operator="<", indicator_b="ema_200"
                    )
                ],
            ),
            signals=[
                SignalConfig(
                    timeframe="1h",
                    signal_type="trend_pullback",
                    direction="long",
                    indicators=[
                        IndicatorConfig(
                            name="macd", params={"fast": 12, "slow": 26, "signal": 9}
                        ),
                        IndicatorConfig(name="ema", params={"period": 20}),
                    ],
                    entry_conditions=[
                        ConditionConfig(
                            indicator_a="macd", operator=">", indicator_b="macd_signal"
                        ),
                        ConditionConfig(
                            indicator_a="close", operator=">", indicator_b="ema_20"
                        ),
                    ],
                )
            ],
            risk=RiskConfig(
                stop_loss_type="atr",
                stop_loss_value=2.0,
                take_profit_type="risk_reward",
                take_profit_value=2.0,
            ),
        ),
        StrategyConfig(
            name="Mean Reversion Sniper",
            description="Contrarian strategy for ranging markets using Bollinger Bands and RSI. Enters when price is overextended.",
            regime=RegimeConfig(
                timeframe="1d",
                indicators=[IndicatorConfig(name="adx", params={"period": 14})],
                bullish_conditions=[
                    ConditionConfig(indicator_a="adx_14", operator="<", indicator_b=25)
                ],
                bearish_conditions=[
                    ConditionConfig(indicator_a="adx_14", operator="<", indicator_b=25)
                ],
            ),
            setup=SetupConfig(
                timeframe="4h",
                indicators=[
                    IndicatorConfig(
                        name="bollinger_bands", params={"period": 20, "std_dev": 2.0}
                    )
                ],
                bullish_conditions=[
                    ConditionConfig(
                        indicator_a="bb_width", operator=">", indicator_b=0.05
                    )
                ],
                bearish_conditions=[
                    ConditionConfig(
                        indicator_a="bb_width", operator=">", indicator_b=0.05
                    )
                ],
            ),
            signals=[
                SignalConfig(
                    timeframe="1h",
                    signal_type="oversold_reversal",
                    direction="long",
                    indicators=[
                        IndicatorConfig(name="rsi", params={"period": 14}),
                        IndicatorConfig(
                            name="bollinger_bands",
                            params={"period": 20, "std_dev": 2.0},
                        ),
                    ],
                    entry_conditions=[
                        ConditionConfig(
                            indicator_a="rsi_14", operator="<", indicator_b=30
                        ),
                        ConditionConfig(
                            indicator_a="close", operator="<", indicator_b="bb_lower"
                        ),
                    ],
                ),
                SignalConfig(
                    timeframe="1h",
                    signal_type="overbought_reversal",
                    direction="short",
                    indicators=[
                        IndicatorConfig(name="rsi", params={"period": 14}),
                        IndicatorConfig(
                            name="bollinger_bands",
                            params={"period": 20, "std_dev": 2.0},
                        ),
                    ],
                    entry_conditions=[
                        ConditionConfig(
                            indicator_a="rsi_14", operator=">", indicator_b=70
                        ),
                        ConditionConfig(
                            indicator_a="close", operator=">", indicator_b="bb_upper"
                        ),
                    ],
                ),
            ],
            risk=RiskConfig(
                stop_loss_type="percent",
                stop_loss_value=1.5,
                take_profit_type="percent",
                take_profit_value=3.0,
            ),
        ),
        StrategyConfig(
            name="Volatility Breakout",
            description="Momentum strategy capturing explosive moves after a period of consolidation (Bollinger Squeeze).",
            regime=RegimeConfig(
                timeframe="1d",
                indicators=[IndicatorConfig(name="adx", params={"period": 14})],
                bullish_conditions=[
                    ConditionConfig(indicator_a="adx_14", operator=">", indicator_b=20)
                ],
                bearish_conditions=[
                    ConditionConfig(indicator_a="adx_14", operator=">", indicator_b=20)
                ],
            ),
            setup=SetupConfig(
                timeframe="4h",
                indicators=[
                    IndicatorConfig(
                        name="bollinger_bands", params={"period": 20, "std_dev": 2.0}
                    )
                ],
                bullish_conditions=[
                    ConditionConfig(
                        indicator_a="bb_width", operator="<", indicator_b=0.10
                    )
                ],
                bearish_conditions=[
                    ConditionConfig(
                        indicator_a="bb_width", operator="<", indicator_b=0.10
                    )
                ],
            ),
            signals=[
                SignalConfig(
                    timeframe="1h",
                    signal_type="bullish_breakout",
                    direction="long",
                    indicators=[
                        IndicatorConfig(
                            name="bollinger_bands",
                            params={"period": 20, "std_dev": 2.0},
                        ),
                        IndicatorConfig(
                            name="sma", params={"period": 20, "source": "volume"}
                        ),
                    ],
                    entry_conditions=[
                        ConditionConfig(
                            indicator_a="close", operator=">", indicator_b="bb_upper"
                        ),
                        ConditionConfig(
                            indicator_a="volume", operator=">", indicator_b="sma_20"
                        ),
                    ],
                )
            ],
            risk=RiskConfig(
                stop_loss_type="atr",
                stop_loss_value=1.5,
                take_profit_type="risk_reward",
                take_profit_value=3.0,
            ),
        ),
        StrategyConfig(
            name="Divergence Master",
            description="Advanced strategy trading Regular (Reversal) and Hidden (Continuation) divergences on RSI.",
            regime=RegimeConfig(
                timeframe="1d",
                indicators=[IndicatorConfig(name="ema", params={"period": 200})],
                bullish_conditions=[
                    ConditionConfig(
                        indicator_a="close", operator=">", indicator_b="ema_200"
                    )
                ],
                bearish_conditions=[
                    ConditionConfig(
                        indicator_a="close", operator="<", indicator_b="ema_200"
                    )
                ],
            ),
            setup=SetupConfig(
                timeframe="4h",
                indicators=[IndicatorConfig(name="rsi", params={"period": 14})],
                bullish_conditions=[
                    ConditionConfig(indicator_a="rsi_14", operator=">", indicator_b=40)
                ],
                bearish_conditions=[
                    ConditionConfig(indicator_a="rsi_14", operator="<", indicator_b=60)
                ],
            ),
            signals=[
                SignalConfig(
                    timeframe="1h",
                    signal_type="regular_bullish_div",
                    direction="long",
                    indicators=[
                        IndicatorConfig(name="rsi", params={"period": 14}),
                        IndicatorConfig(
                            name="divergence",
                            params={"oscillator": "rsi_14", "lookback": 3},
                        ),
                    ],
                    entry_conditions=[
                        ConditionConfig(
                            indicator_a="rsi_14_div_reg_bull",
                            operator="==",
                            indicator_b=1.0,
                        )
                    ],
                ),
                SignalConfig(
                    timeframe="1h",
                    signal_type="hidden_bullish_div",
                    direction="long",
                    indicators=[
                        IndicatorConfig(name="rsi", params={"period": 14}),
                        IndicatorConfig(
                            name="divergence",
                            params={"oscillator": "rsi_14", "lookback": 3},
                        ),
                    ],
                    entry_conditions=[
                        ConditionConfig(
                            indicator_a="rsi_14_div_hid_bull",
                            operator="==",
                            indicator_b=1.0,
                        )
                    ],
                ),
                SignalConfig(
                    timeframe="1h",
                    signal_type="regular_bearish_div",
                    direction="short",
                    indicators=[
                        IndicatorConfig(name="rsi", params={"period": 14}),
                        IndicatorConfig(
                            name="divergence",
                            params={"oscillator": "rsi_14", "lookback": 3},
                        ),
                    ],
                    entry_conditions=[
                        ConditionConfig(
                            indicator_a="rsi_14_div_reg_bear",
                            operator="==",
                            indicator_b=1.0,
                        )
                    ],
                ),
                SignalConfig(
                    timeframe="1h",
                    signal_type="hidden_bearish_div",
                    direction="short",
                    indicators=[
                        IndicatorConfig(name="rsi", params={"period": 14}),
                        IndicatorConfig(
                            name="divergence",
                            params={"oscillator": "rsi_14", "lookback": 3},
                        ),
                    ],
                    entry_conditions=[
                        ConditionConfig(
                            indicator_a="rsi_14_div_hid_bear",
                            operator="==",
                            indicator_b=1.0,
                        )
                    ],
                ),
            ],
            risk=RiskConfig(
                stop_loss_type="atr",
                stop_loss_value=2.0,
                take_profit_type="risk_reward",
                take_profit_value=2.5,
            ),
        ),
    ]
