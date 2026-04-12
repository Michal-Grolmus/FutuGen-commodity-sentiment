from __future__ import annotations

import logging
from datetime import datetime, timezone

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.models import CommoditySignal, Direction, ScoringResult

logger = logging.getLogger(__name__)

DIRECTION_COLORS = {
    Direction.BULLISH: "green",
    Direction.BEARISH: "red",
    Direction.NEUTRAL: "yellow",
}

DIRECTION_ARROWS = {
    Direction.BULLISH: "^",
    Direction.BEARISH: "v",
    Direction.NEUTRAL: "-",
}


class TerminalDisplay:
    def __init__(self, max_signals: int = 20) -> None:
        self._console = Console()
        self._signals: list[tuple[datetime, CommoditySignal]] = []
        self._max_signals = max_signals
        self._chunks_processed = 0
        self._live: Live | None = None

    def start(self) -> Live:
        self._live = Live(self._render(), console=self._console, refresh_per_second=2)
        return self._live

    def update(self, result: ScoringResult) -> None:
        self._chunks_processed += 1
        now = datetime.now(timezone.utc)
        for sig in result.signals:
            self._signals.append((now, sig))
        self._signals = self._signals[-self._max_signals:]

        if self._live:
            self._live.update(self._render())

    def _render(self) -> Panel:
        table = Table(title="Commodity Signals", expand=True)
        table.add_column("Time", width=8)
        table.add_column("Commodity", width=18)
        table.add_column("Dir", width=5, justify="center")
        table.add_column("Conf", width=6, justify="right")
        table.add_column("Timeframe", width=12)
        table.add_column("Rationale", ratio=1)

        for ts, sig in reversed(self._signals):
            color = DIRECTION_COLORS[sig.direction]
            arrow = DIRECTION_ARROWS[sig.direction]
            dir_text = Text(f"{arrow} {sig.direction.value}", style=color)
            conf_text = Text(f"{sig.confidence:.0%}", style="bold" if sig.confidence > 0.7 else "")
            table.add_row(
                ts.strftime("%H:%M:%S"),
                sig.display_name,
                dir_text,
                conf_text,
                sig.timeframe.value.replace("_", " "),
                sig.rationale[:60],
            )

        header = Text(f"Chunks: {self._chunks_processed} | Signals: {len(self._signals)}")
        return Panel(table, title="[bold]Commodity Sentiment Monitor[/bold]", subtitle=str(header))
