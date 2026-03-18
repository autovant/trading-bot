"""CLI entry point for the Polymarket copy trading bot."""

from __future__ import annotations

import asyncio
import sys

import click


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """Polymarket Copy Trading Bot — mirror top traders automatically."""


@main.command()
@click.option("--config", "-c", default=None, help="Path to YAML config file")
@click.option("--dry-run/--live", default=True, help="Dry-run mode (no real orders)")
@click.option("--wallet", "-w", multiple=True, help="Source wallet address(es) to monitor")
def start(config: str | None, dry_run: bool, wallet: tuple[str, ...]) -> None:
    """Start the copy trading bot."""
    import os

    # Allow CLI wallet args to supplement env/config wallets
    if wallet:
        existing = os.getenv("SOURCE_WALLETS", "")
        combined = ",".join(list(wallet) + ([existing] if existing else []))
        os.environ["SOURCE_WALLETS"] = combined

    from .config import load_config

    cfg = load_config(config)
    cfg.dry_run = dry_run

    from .app import App

    app = App(cfg)

    click.echo("🚀 Starting Polymarket Copy Trading Bot")
    click.echo(f"   Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    click.echo(f"   Wallets: {len(cfg.source_wallets)}")
    click.echo(f"   Sizing: {cfg.copy.sizing_mode}")
    click.echo()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(app.start())
    except KeyboardInterrupt:
        click.echo("\n⛔ Interrupted — shutting down…")
        loop.run_until_complete(app.stop())
    finally:
        loop.close()


@main.command()
@click.option("--config", "-c", default=None, help="Path to YAML config file")
@click.option("--limit", "-n", default=20, help="Number of recent trades to show")
def history(config: str | None, limit: int) -> None:
    """Show recent copied trade history."""
    from .config import load_config
    from .persistence import TradeStore

    cfg = load_config(config)
    store = TradeStore(cfg.database.url)

    async def _show():
        await store.start()
        trades = await store.get_recent_trades(limit)
        await store.stop()
        if not trades:
            click.echo("No trades found.")
            return
        click.echo(f"{'ID':>5} {'Status':<12} {'Side':<5} {'Price':>8} {'Size':>10} {'Source':<12} {'Time'}")
        click.echo("-" * 75)
        for t in trades:
            click.echo(
                f"{t.id or 0:>5} {t.status.value:<12} {t.side.value:<5} "
                f"{t.price:>8.4f} {t.size:>10.2f} {t.source_wallet[:12]:<12} "
                f"{t.created_at.strftime('%Y-%m-%d %H:%M')}"
            )

    asyncio.run(_show())


@main.command()
@click.option("--config", "-c", default=None, help="Path to YAML config file")
def stats(config: str | None) -> None:
    """Show aggregate trading statistics."""
    from .config import load_config
    from .persistence import TradeStore

    cfg = load_config(config)
    store = TradeStore(cfg.database.url)

    async def _show():
        await store.start()
        s = await store.get_stats()
        await store.stop()
        if not s:
            click.echo("No statistics available.")
            return
        click.echo("📊 Trading Statistics")
        click.echo(f"   Total trades:  {s.get('total', 0)}")
        click.echo(f"   Filled:        {s.get('filled', 0)}")
        click.echo(f"   Failed:        {s.get('failed', 0)}")
        click.echo(f"   Wins:          {s.get('wins', 0)}")
        click.echo(f"   Losses:        {s.get('losses', 0)}")
        click.echo(f"   Total PnL:     ${s.get('total_pnl', 0):.2f}")
        click.echo(f"   Volume:        ${s.get('total_volume', 0):.2f}")

    asyncio.run(_show())


@main.command()
@click.option("--config", "-c", default=None, help="Path to YAML config file")
def validate(config: str | None) -> None:
    """Validate configuration and connectivity."""
    from .config import load_config

    cfg = load_config(config)

    click.echo("✅ Configuration loaded successfully")
    click.echo(f"   CLOB URL:       {cfg.polymarket.clob_url}")
    click.echo(f"   Chain ID:       {cfg.polymarket.chain_id}")
    click.echo(f"   Source wallets:  {len(cfg.source_wallets)}")
    click.echo(f"   Dry run:        {cfg.dry_run}")
    click.echo(f"   Sizing mode:    {cfg.copy.sizing_mode}")
    click.echo(f"   Max position:   ${cfg.risk.max_position_size_usdc:.2f}")
    click.echo(f"   Max exposure:   ${cfg.risk.max_portfolio_exposure_usdc:.2f}")
    click.echo(f"   Database:       {cfg.database.url}")

    has_key = bool(cfg.polymarket.private_key)
    click.echo(f"   Private key:    {'✅ Set' if has_key else '⚠️  Not set (read-only mode)'}")

    if not cfg.source_wallets:
        click.echo("\n⚠️  No source wallets configured — add via config or SOURCE_WALLETS env var")
    else:
        for i, w in enumerate(cfg.source_wallets, 1):
            click.echo(f"   Wallet {i}: {w}")


if __name__ == "__main__":
    main()
