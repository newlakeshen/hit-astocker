"""Hit-Astocker: A-Stock limit-up board hitting quantitative analysis system."""

import logging

import typer

from hit_astocker.commands.backtest_cmd import backtest_app
from hit_astocker.commands.daily_cmd import daily_app
from hit_astocker.commands.dragon_cmd import dragon_app
from hit_astocker.commands.event_cmd import event_app
from hit_astocker.commands.firstboard_cmd import firstboard_app
from hit_astocker.commands.flow_cmd import flow_app
from hit_astocker.commands.lianban_cmd import lianban_app
from hit_astocker.commands.predict_cmd import predict_app
from hit_astocker.commands.sector_cmd import sector_app
from hit_astocker.commands.sentiment_cmd import sentiment_app
from hit_astocker.commands.signal_cmd import signal_app
from hit_astocker.commands.sync_cmd import sync_app
from hit_astocker.commands.backtest_diag_cmd import diag_app
from hit_astocker.commands.train_cmd import train_app

app = typer.Typer(
    name="hit-astocker",
    help="A-Stock limit-up board hitting quantitative analysis system (打板量化分析系统)",
    no_args_is_help=True,
)

# Register sub-commands
app.add_typer(sync_app, name="sync")
app.add_typer(daily_app, name="daily")
app.add_typer(sentiment_app, name="sentiment")
app.add_typer(firstboard_app, name="firstboard")
app.add_typer(lianban_app, name="lianban")
app.add_typer(sector_app, name="sector")
app.add_typer(dragon_app, name="dragon")
app.add_typer(signal_app, name="signal")
app.add_typer(backtest_app, name="backtest")
app.add_typer(predict_app, name="predict")
app.add_typer(flow_app, name="flow")
app.add_typer(event_app, name="event")
app.add_typer(train_app, name="train")
app.add_typer(diag_app, name="backtest-diag")


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
):
    """Hit-Astocker quantitative analysis system."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


if __name__ == "__main__":
    app()
