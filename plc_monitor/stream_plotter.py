"""Grafico realtime dello stream multi-canale con timestamp di pacchetto."""

from __future__ import annotations

import os
import time
from pathlib import Path

import matplotlib
import numpy as np

from plc_monitor.stream_client import PacketBuffer


def _need_agg(save_path: str | None) -> bool:
    if save_path:
        return True
    return not os.environ.get("DISPLAY") and os.name != "nt"


def run_stream_plot(
    buffer: PacketBuffer,
    *,
    channels_to_show: list[int] | None = None,
    sample_hz: float = 1000.0,
    window_packets: int = 50,
    packet_ms: float = 100.0,
    save_path: str | None = None,
    seconds: float | None = None,
    title: str = "Stream PLC Siemens",
) -> Path | None:
    """Mostra fino a 4 canali + stato pacchetti (seq, timestamp, rate).

    Di default apre una finestra matplotlib live aggiornata ogni ``packet_ms``
    (≈100 ms / 10 Hz). Usa ``save_path`` / ``seconds`` solo per headless/CI.
    """
    if _need_agg(save_path):
        matplotlib.use("Agg")

    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    # Allinea il refresh del grafico al passo pacchetto (default 100 ms ≈ 10 Hz).
    interval_ms = max(int(round(packet_ms)), 1)

    show = channels_to_show or [0, 1, 2, 3]
    n = len(show)
    fig, axes = plt.subplots(n + 1, 1, figsize=(12, 2.0 * (n + 1)), constrained_layout=True)
    if n + 1 == 1:
        axes = [axes]
    fig.suptitle(title)

    wave_lines = []
    for ax, ch in zip(axes[:-1], show):
        (line,) = ax.plot([], [], lw=1.2)
        wave_lines.append(line)
        ax.set_ylabel(f"CH{ch}")
        ax.grid(True, alpha=0.35)
    status_ax = axes[-1]
    (rate_line,) = status_ax.plot([], [], lw=1.4, color="tab:orange")
    status_ax.set_ylabel("pkt/s")
    status_ax.set_xlabel("tempo pacchetto (s)")
    status_ax.grid(True, alpha=0.35)
    info = fig.text(0.01, 0.01, "", fontsize=9, family="monospace")

    history_t: list[float] = []
    history_rate: list[float] = []
    t0_ref: float | None = None

    def _draw(_frame: int = 0) -> None:
        nonlocal t0_ref
        packets, stats = buffer.snapshot()
        if not packets:
            info.set_text(stats.last_error or "In attesa di pacchetti...")
            return
        recent = packets[-window_packets:]
        last = recent[-1]
        if t0_ref is None:
            t0_ref = last.timestamp_s
        # onde: ultimo pacchetto, asse = tempo assoluto del campione
        t_wave = last.timestamp_s + np.arange(last.samples) / sample_hz
        for line, ch in zip(wave_lines, show):
            if ch < last.channels:
                line.set_data(t_wave, last.data[ch])
                ax = line.axes
                ax.set_xlim(t_wave[0], t_wave[-1])
                ys = last.data[ch]
                pad = max(0.1, 0.05 * (float(ys.max()) - float(ys.min()) or 1.0))
                ax.set_ylim(float(ys.min()) - pad, float(ys.max()) + pad)
        # rate history
        history_t.clear()
        history_rate.clear()
        for i, pkt in enumerate(recent):
            history_t.append(pkt.timestamp_s - t0_ref)
            # stima locale: distanza dal precedente
            if i == 0:
                history_rate.append(stats.rate_hz)
            else:
                dt = (pkt.timestamp_ns - recent[i - 1].timestamp_ns) / 1e9
                history_rate.append(1.0 / dt if dt > 0 else 0.0)
        rate_line.set_data(history_t, history_rate)
        if history_t:
            status_ax.set_xlim(history_t[0], max(history_t[-1], history_t[0] + 0.1))
            status_ax.set_ylim(0, max(15.0, max(history_rate) * 1.2))
        ts_ms = last.timestamp_ns / 1e6
        info.set_text(
            f"seq={last.sequence}  ts_ns={last.timestamp_ns}  ts_ms={ts_ms:.3f}  "
            f"ch={last.channels} samp={last.samples}  "
            f"rate={stats.rate_hz:.1f} pkt/s  gaps={stats.gaps}  "
            f"bytes={stats.bytes_rx}  err={stats.last_error or '-'}  "
            f"refresh={interval_ms}ms"
        )

    if save_path or seconds is not None:
        duration = seconds if seconds is not None else 5.0
        deadline = time.monotonic() + duration
        sleep_s = max(interval_ms / 1000.0, 0.01)
        while time.monotonic() < deadline:
            time.sleep(sleep_s)
            _draw(0)
        if save_path:
            out = Path(save_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out, dpi=120)
            plt.close(fig)
            return out
        plt.close(fig)
        return None

    # Finestra live (default): FuncAnimation ≈ packet_ms (100 ms → ~10 Hz).
    animation = FuncAnimation(fig, _draw, interval=interval_ms, cache_frame_data=False)
    plt.show()
    _ = animation
    return None
