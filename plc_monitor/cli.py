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

log = logging.getLogger("plc_monitor")

LOCAL_SIM_HOST = "127.0.0.1"
LOCAL_SIM_PORT = 5020


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="File YAML di configurazione (default: config.yaml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log più dettagliati")


def _add_connection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="IP del PLC (sovrascrive la config)")
    parser.add_argument("--port", type=int, help="Porta TCP (sovrascrive la config, di solito 502)")
    parser.add_argument("--unit-id", type=int, dest="unit_id", help="Unit ID / slave Modbus")
    parser.add_argument("--poll-ms", type=int, dest="poll_ms", help="Intervallo di lettura in ms")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plc-monitor",
        description="Legge segnali da un PLC via Modbus TCP e li graficizza in tempo reale.",
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _setup_logging(args.verbose)
    config_path = Path(args.config)
    if not config_path.exists():
        log.error("Config non trovata: %s", config_path)
        return 2
    commands = {
        "test": cmd_test,
        "plot": cmd_plot,
        "simulate": cmd_simulate,
        "demo": cmd_demo,
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
