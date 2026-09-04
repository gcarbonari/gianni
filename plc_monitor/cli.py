"""Interfaccia a riga di comando."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from plc_monitor.client import PlcClient, PlcReadError
from plc_monitor.config import load_config, with_plc
from plc_monitor.plotter import run_plot
from plc_monitor.sampler import CsvLogger, Poller, SampleBuffer
from plc_monitor.simulator import SimulatorThread, run_simulator
from plc_monitor.stream_client import PacketBuffer, StreamClient
from plc_monitor.stream_config import apply_stream_overrides, load_stream_config
from plc_monitor.stream_plotter import run_stream_plot
from plc_monitor.stream_sim import PacketStreamServer

log = logging.getLogger("plc_monitor")

LOCAL_SIM_HOST = "127.0.0.1"
LOCAL_SIM_PORT = 5020
LOCAL_STREAM_HOST = "127.0.0.1"
DEFAULT_STREAM_CONFIG = "config.siemens.yaml"
STREAM_COMMANDS = frozenset({"stream", "stream-sim", "stream-demo"})


def _add_common(
    parser: argparse.ArgumentParser,
    *,
    default_config: str = "config.yaml",
) -> None:
    parser.add_argument(
        "-c",
        "--config",
        default=default_config,
        help=f"File YAML di configurazione (default: {default_config})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log più dettagliati")


def _add_connection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="IP del PLC (sovrascrive la config)")
    parser.add_argument("--port", type=int, help="Porta TCP (sovrascrive la config, di solito 502)")
    parser.add_argument("--unit-id", type=int, dest="unit_id", help="Unit ID / slave Modbus")
    parser.add_argument("--poll-ms", type=int, dest="poll_ms", help="Intervallo di lettura in ms")


def _add_stream_connection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="IP del PLC / stream (sovrascrive la config)")
    parser.add_argument("--port", type=int, help="Porta TCP stream (sovrascrive la config)")


def _add_stream_plot_opts(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--save", help="Salva un PNG invece di aprire la finestra")
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Durata della cattura in secondi (implicito se usi --save)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plc-monitor",
        description=(
            "Legge segnali da un PLC via Modbus TCP oppure stream TCP multi-canale "
            "(Siemens 100 ch @ 1000 Hz) e li graficizza in tempo reale."
        ),
    )
    _add_common(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    test = sub.add_parser("test", help="Prova la connessione e stampa un campione")
    _add_common(test)
    _add_connection(test)

    plot = sub.add_parser("plot", help="Connetti al PLC e mostra il grafico live")
    _add_common(plot)
    _add_connection(plot)
    plot.add_argument("--save", help="Salva un PNG invece di aprire la finestra")
    plot.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Durata della cattura in secondi (implicito se usi --save)",
    )
    plot.add_argument("--csv", help="Percorso CSV di log (sovrascrive la config)")

    simulate = sub.add_parser("simulate", help="Avvia un PLC Modbus TCP simulato")
    _add_common(simulate)
    _add_connection(simulate)

    demo = sub.add_parser("demo", help="Simulatore + grafico, senza hardware")
    _add_common(demo)
    _add_connection(demo)
    demo.add_argument("--save", help="Salva un PNG invece di aprire la finestra")
    demo.add_argument("--seconds", type=float, default=None)
    demo.add_argument("--csv", help="Percorso CSV di log")

    stream = sub.add_parser(
        "stream",
        help="Ricevi stream TCP multi-canale (Siemens 100 ch @ 1000 Hz) e grafica",
    )
    _add_common(stream, default_config=DEFAULT_STREAM_CONFIG)
    _add_stream_connection(stream)
    _add_stream_plot_opts(stream)

    stream_sim = sub.add_parser(
        "stream-sim",
        help="Avvia un simulatore di stream TCP (100 ch @ 1000 Hz, pacchetti da 100 ms)",
    )
    _add_common(stream_sim, default_config=DEFAULT_STREAM_CONFIG)
    _add_stream_connection(stream_sim)

    stream_demo = sub.add_parser(
        "stream-demo",
        help="Simulatore stream + grafico locale, senza PLC",
    )
    _add_common(stream_demo, default_config=DEFAULT_STREAM_CONFIG)
    _add_stream_connection(stream_demo)
    _add_stream_plot_opts(stream_demo)

    return parser


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def apply_connection_overrides(config, args):
    changes = {}
    if getattr(args, "host", None):
        changes["host"] = args.host
    if getattr(args, "port", None) is not None:
        changes["port"] = args.port
    if getattr(args, "unit_id", None) is not None:
        changes["unit_id"] = args.unit_id
    if getattr(args, "poll_ms", None) is not None:
        changes["poll_ms"] = args.poll_ms
    return with_plc(config, **changes) if changes else config


def _start_session(config, csv_override: str | None):
    names = tuple(signal.name for signal in config.signals)
    buffer = SampleBuffer(names, config.plot.window_seconds)
    csv_path = csv_override or (config.csv.path if config.csv.enabled else None)
    csv_logger = CsvLogger(csv_path, names) if csv_path else None
    client = PlcClient(config)
    client.connect()
    poller = Poller(client, config, buffer, csv_logger)
    poller.start()
    return client, buffer, poller, csv_logger


def _stop_session(client: PlcClient, poller: Poller, csv_logger: CsvLogger | None) -> None:
    poller.stop()
    poller.join(timeout=2)
    client.close()
    if csv_logger:
        csv_logger.close()


def _load(args, *, local_sim: bool = False):
    config = apply_connection_overrides(load_config(args.config), args)
    if local_sim:
        host = args.host or LOCAL_SIM_HOST
        port = args.port if args.port is not None else LOCAL_SIM_PORT
        config = with_plc(config, host=host, port=port)
    return config


def cmd_test(args: argparse.Namespace) -> int:
    config = _load(args)
    log.info("Provo %s:%s (unit %s)", config.plc.host, config.plc.port, config.plc.unit_id)
    client = PlcClient(config)
    try:
        client.connect()
        _stamp, values = client.poll_once()
    except PlcReadError as exc:
        log.error("%s", exc)
        return 1
    finally:
        client.close()
    for name, value in values.items():
        signal = next(s for s in config.signals if s.name == name)
        unit = f" {signal.unit}" if signal.unit else ""
        log.info("  %s = %s%s", name, value, unit)
    log.info("Connessione ok. Per il grafico: python -m plc_monitor plot")
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    config = _load(args)
    log.info("Grafico live da %s:%s", config.plc.host, config.plc.port)
    client, buffer, poller, csv_logger = _start_session(config, getattr(args, "csv", None))
    try:
        saved = run_plot(config, buffer, save_path=args.save, seconds=args.seconds)
        if saved:
            log.info("Grafico salvato in %s", saved)
        return 0
    finally:
        _stop_session(client, poller, csv_logger)


def cmd_simulate(args: argparse.Namespace) -> int:
    config = _load(args, local_sim=True)
    log.info("Avvio simulatore su %s:%s", config.plc.host, config.plc.port)
    run_simulator(config.plc.host, config.plc.port)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    config = _load(args, local_sim=True)
    sim = SimulatorThread(host=config.plc.host, port=config.plc.port)
    sim.start()
    try:
        args.host = config.plc.host
        args.port = config.plc.port
        return cmd_plot(args)
    finally:
        sim.stop()


def _load_stream(args: argparse.Namespace, *, local_sim: bool = False):
    cfg = apply_stream_overrides(load_stream_config(args.config), args)
    if local_sim:
        host = args.host or LOCAL_STREAM_HOST
        port = args.port if args.port is not None else cfg.port
        cfg = apply_stream_overrides(
            cfg,
            argparse.Namespace(host=host, port=port),
        )
    return cfg


def _start_stream_session(cfg):
    buffer = PacketBuffer(maxlen=max(200, cfg.window_packets * 2))
    client = StreamClient(
        cfg.host,
        cfg.port,
        buffer,
        timeout=cfg.timeout,
        expected_channels=cfg.channels,
        expected_samples=cfg.samples_per_packet,
    )
    client.start()
    return buffer, client


def _stop_stream_session(client: StreamClient) -> None:
    client.stop()
    client.join(timeout=3)


def cmd_stream(args: argparse.Namespace) -> int:
    cfg = _load_stream(args)
    log.info(
        "Stream da %s:%s (%d ch, %d samp/pkt @ %.0f Hz)",
        cfg.host,
        cfg.port,
        cfg.channels,
        cfg.samples_per_packet,
        cfg.sample_hz,
    )
    buffer, client = _start_stream_session(cfg)
    try:
        saved = run_stream_plot(
            buffer,
            channels_to_show=list(cfg.plot_channels),
            sample_hz=cfg.sample_hz,
            window_packets=cfg.window_packets,
            packet_ms=cfg.packet_ms,
            save_path=args.save,
            seconds=args.seconds,
            title=cfg.title,
        )
        if saved:
            log.info("Grafico salvato in %s", saved)
        packets, stats = buffer.snapshot()
        if not packets:
            log.error(
                "Nessun pacchetto ricevuto da %s:%s (err=%s). "
                "Il Cloud Agent NON è il PC con la USB Ethernet: "
                "192.168.2.100 è raggiungibile solo dal PC locale che già fa ping. "
                "Lì esegui: python -m plc_monitor stream. "
                "Qui in cloud usa solo: python -m plc_monitor stream-demo.",
                cfg.host,
                cfg.port,
                stats.last_error or "-",
            )
            return 1
        return 0
    finally:
        _stop_stream_session(client)


def cmd_stream_sim(args: argparse.Namespace) -> int:
    cfg = _load_stream(args, local_sim=True)
    log.info(
        "Avvio simulatore stream su %s:%s (%d ch @ %.0f Hz, ogni %.0f ms)",
        cfg.host,
        cfg.port,
        cfg.channels,
        cfg.sample_hz,
        cfg.packet_ms,
    )
    server = PacketStreamServer(
        host=cfg.host,
        port=cfg.port,
        channels=cfg.channels,
        samples=cfg.samples_per_packet,
        sample_hz=cfg.sample_hz,
        packet_ms=cfg.packet_ms,
    )
    server.start_ready()
    try:
        while server.is_alive():
            server.join(timeout=1.0)
            if not server.is_alive():
                break
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def cmd_stream_demo(args: argparse.Namespace) -> int:
    cfg = _load_stream(args, local_sim=True)
    server = PacketStreamServer(
        host=cfg.host,
        port=cfg.port,
        channels=cfg.channels,
        samples=cfg.samples_per_packet,
        sample_hz=cfg.sample_hz,
        packet_ms=cfg.packet_ms,
    )
    server.start_ready()
    try:
        args.host = cfg.host
        args.port = cfg.port
        return cmd_stream(args)
    finally:
        server.stop()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _setup_logging(args.verbose)
    # Stream subcommands default to config.siemens.yaml even if the parent
    # parser still carries config.yaml from the top-level defaults.
    if args.command in STREAM_COMMANDS and args.config == "config.yaml":
        args.config = DEFAULT_STREAM_CONFIG
    config_path = Path(args.config)
    if not config_path.exists():
        log.error("Config non trovata: %s", config_path)
        return 2
    commands = {
        "test": cmd_test,
        "plot": cmd_plot,
        "simulate": cmd_simulate,
        "demo": cmd_demo,
        "stream": cmd_stream,
        "stream-sim": cmd_stream_sim,
        "stream-demo": cmd_stream_demo,
    }
    try:
        return commands[args.command](args)
    except KeyboardInterrupt:
        log.info("Interrotto")
        return 0
    except Exception as exc:
        log.error("%s", exc)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
