"""Grafico live (o PNG in modalità headless) dei segnali PLC."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from pathlib import Path

import matplotlib

from plc_monitor.config import AppConfig, Signal
from plc_monitor.sampler import SampleBuffer


def _need_agg(save_path: str | None) -> bool:
    if save_path:
        return True
    return not os.environ.get("DISPLAY") and os.name != "nt"


def run_plot(
    config: AppConfig,
    buffer: SampleBuffer,
    *,
    save_path: str | None = None,
    seconds: float | None = None,
    wait_for_stop=None,
) -> Path | None:
    """Mostra il grafico live, oppure campiona `seconds` e salva un PNG.

    `wait_for_stop` è un callable opzionale (es. Event.wait) usato dai test
    per interrompere l'animazione senza un display.
    """
    if _need_agg(save_path):
        matplotlib.use("Agg")

    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    signals: Sequence[Signal] = config.signals
    fig, axes = plt.subplots(
        len(signals),
        1,
        sharex=True,
        figsize=(11, 2.2 * len(signals)),
        constrained_layout=True,
    )
    if len(signals) == 1:
        axes = [axes]

    fig.suptitle(config.plot.title)
    lines = []
    value_texts = []
    for ax, signal in zip(axes, signals):
        (line,) = ax.plot([], [], lw=1.6)
        lines.append(line)
        ylabel = signal.name if not signal.unit else f"{signal.name} ({signal.unit})"
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.35)
        text = ax.text(0.01, 0.88, "", transform=ax.transAxes, fontsize=9)
        value_texts.append(text)
    axes[-1].set_xlabel("tempo (s)")
    status = fig.text(0.01, 0.01, "", fontsize=8, color="tab:red")

    def _draw(_frame: int) -> None:
        times, series, error, last = buffer.snapshot()
        xmax = max(config.plot.window_seconds, 1.0)
        if times:
            xmax = max(times[-1], 1.0)
        for ax, signal, line, label in zip(axes, signals, lines, value_texts):
            ys = series[signal.name]
            line.set_data(times, ys)
            ax.set_xlim(0, xmax)
            if ys:
                ymin, ymax = min(ys), max(ys)
                pad = max(0.05 * (ymax - ymin), 0.1)
                if ymin == ymax:
                    pad = max(abs(ymin) * 0.05, 0.5)
                ax.set_ylim(ymin - pad, ymax + pad)
                current = last.get(signal.name)
                if current is not None:
                    unit = f" {signal.unit}" if signal.unit else ""
                    label.set_text(f"{current:.2f}{unit}")
        status.set_text(error or "")

    interval_ms = max(int(config.poll_interval * 1000), 50)

    if save_path or seconds is not None:
        duration = seconds if seconds is not None else 8.0
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if wait_for_stop and wait_for_stop(0.05):
                break
            time.sleep(0.05)
            _draw(0)
        if save_path:
            out = Path(save_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out, dpi=120)
            plt.close(fig)
            return out
        plt.close(fig)
        return None

    animation = FuncAnimation(fig, _draw, interval=interval_ms, cache_frame_data=False)
    plt.show()
    # riferimento tenuto finché la finestra è aperta
    _ = animation
    return None
