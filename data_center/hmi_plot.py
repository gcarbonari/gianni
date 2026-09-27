"""Finestra HMI minimale: grafico live dei tag dell'accentratore."""

from __future__ import annotations

import os
import time
from collections import deque
from pathlib import Path

import matplotlib

from data_center.runtime import DataCenter

DEFAULT_TAGS = (
    "veh.EEC1.EngineSpeed",
    "veh.CCVS.WheelBasedSpeed",
    "avionics.heading",
    "plc.Temperatura",
)


def _need_agg(save_path: str | None) -> bool:
    if save_path:
        return True
    return not os.environ.get("DISPLAY") and os.name != "nt"


def run_hmi_plot(
    dc: DataCenter,
    *,
    tags: tuple[str, ...] = DEFAULT_TAGS,
    window_seconds: float = 20.0,
    interval_ms: int = 200,
    save_path: str | None = None,
    seconds: float | None = None,
    title: str = "Data center — CAN + ARINC + PLC",
) -> Path | None:
    if _need_agg(save_path):
        matplotlib.use("Agg")

    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    n = len(tags)
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.1 * n), constrained_layout=True)
    if n == 1:
        axes = [axes]
    try:
        fig.canvas.manager.set_window_title("Data center HMI")  # type: ignore[union-attr]
    except Exception:
        pass
    fig.suptitle(title, fontsize=13)

    series = {name: deque() for name in tags}
    times: deque[float] = deque()
    lines = []
    value_texts = []
    t0 = time.monotonic()
    for ax, name in zip(axes, tags):
        (line,) = ax.plot([], [], lw=1.6)
        lines.append(line)
        ax.set_ylabel(name.split(".")[-1])
        ax.grid(True, alpha=0.35)
        txt = ax.text(0.99, 0.88, "", transform=ax.transAxes, ha="right", va="top", fontsize=10)
        value_texts.append(txt)
    axes[-1].set_xlabel("tempo (s)")

    def _draw(_frame: int = 0) -> None:
        now = time.monotonic() - t0
        snap = dc.bus.snapshot()
        times.append(now)
        for name in tags:
            upd = snap.get(name)
            series[name].append(float(upd.value) if upd is not None else float("nan"))
        cutoff = now - window_seconds
        while times and times[0] < cutoff:
            times.popleft()
            for name in tags:
                series[name].popleft()
        xs = list(times)
        for line, txt, name in zip(lines, value_texts, tags):
            ys = list(series[name])
            line.set_data(xs, ys)
            ax = line.axes
            ax.relim()
            ax.autoscale_view()
            upd = snap.get(name)
            if upd is None:
                txt.set_text("—")
            else:
                txt.set_text(f"{upd.value:.2f} {upd.unit}".strip())

    if save_path or seconds is not None:
        duration = seconds if seconds is not None else 4.0
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            time.sleep(max(interval_ms / 1000.0, 0.05))
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
    _ = animation
    return None
