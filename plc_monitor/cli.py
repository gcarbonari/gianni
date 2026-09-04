"""Interfaccia a riga di comando."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from plc_monitor.client import PlcClient
from plc_monitor.config import load_config
from plc_monitor.plotter import run_plot
from plc_monitor.sampler import CsvLogger, Poller, SampleBuffer
from plc_monitor.simulator import SimulatorThread, run_simulator

log = logging.getLogger("plc_monitor")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="File YAML di configurazione (default: config.yaml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log più dettagliati")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plc-monitor",
        description="Legge segnali da un PLC via Modbus TCP e li graficizza.",
    )
    _add_common(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    plot = sub.add_parser("plot", help="Connetti al PLC e mostra il grafico live")
    _add_common(plot)
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

    demo = sub.add_parser("demo", help="Simulatore + grafico, senza hardware")
    _add_common(demo)
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
    # pymodbus e matplotlib sono molto verbosi in DEBUG
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def _start_session(config_path: str, csv_override: str | None):
    config = load_config(config_path)
    names = tuple(signal.name for signal in config.signals)
    buffer = SampleBuffer(names, config.plot.window_seconds)
    csv_path = csv_override or (config.csv.path if config.csv.enabled else None)
    csv_logger = CsvLogger(csv_path, names) if csv_path else None
    client = PlcClient(config)
    client.connect()
    poller = Poller(client, config, buffer, csv_logger)
    poller.start()
    return config, client, buffer, poller, csv_logger


def _stop_session(client: PlcClient, poller: Poller, csv_logger: CsvLogger | None) -> None:
    poller.stop()
    poller.join(timeout=2)
    client.close()
    if csv_logger:
        csv_logger.close()


def cmd_plot(args: argparse.Namespace) -> int:
    config, client, buffer, poller, csv_logger = _start_session(args.config, args.csv)
    try:
        saved = run_plot(config, buffer, save_path=args.save, seconds=args.seconds)
        if saved:
            log.info("Grafico salvato in %s", saved)
        return 0
    finally:
        _stop_session(client, poller, csv_logger)


def cmd_simulate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    log.info("Avvio simulatore su %s:%s", config.plc.host, config.plc.port)
    run_simulator(config.plc.host, config.plc.port)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    sim = SimulatorThread(host=config.plc.host, port=config.plc.port)
    sim.start()
    try:
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
