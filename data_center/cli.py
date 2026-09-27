"""CLI del data center."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from data_center.runtime import DataCenter

log = logging.getLogger("data_center")
DEFAULT_CONFIG = "config.datacenter.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="data-center",
        description=(
            "Accentratore dati: moduli CAN/J1939, ARINC 429 e PLC pubblicano "
            "tag su un bus comune, visibile ai client HMI/TestStand."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Avvia il data center (adapter + gateway JSON)")
    serve.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    serve.add_argument("--seconds", type=float, default=None, help="Arresto automatico (test)")

    demo = sub.add_parser("demo", help="CAN + ARINC simulati, stampa lo snapshot")
    demo.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    demo.add_argument("--seconds", type=float, default=3.0)

    snap = sub.add_parser("snapshot", help="Avvia, attende tag, stampa JSON e esce")
    snap.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    snap.add_argument("--seconds", type=float, default=2.0)
    snap.add_argument("--pattern", default="*")

    cat = sub.add_parser("catalog", help="Elenca i tag dal DBC/ICD/YAML, senza hardware")
    cat.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    cat.add_argument("--all", action="store_true", help="Include anche adapter disabilitati")

    bind = sub.add_parser(
        "bind",
        help="Applica un profilo TestStand: solo i tag del test, errore se il DUT non li ha",
    )
    bind.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    bind.add_argument("-p", "--profile", default="profiles/vehicle_smoke.yaml")
    bind.add_argument("--all", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.command == "serve":
        return _serve(args.config, args.seconds)
    if args.command == "demo":
        return _demo(args.config, args.seconds)
    if args.command == "snapshot":
        return _snapshot(args.config, args.seconds, args.pattern)
    if args.command == "catalog":
        return _catalog(args.config, args.all)
    if args.command == "bind":
        return _bind(args.config, args.profile, args.all)
    return 1


def _boot(config_path: str) -> DataCenter:
    path = Path(config_path)
    if not path.exists():
        raise SystemExit(f"Config non trovata: {path}")
    dc = DataCenter.from_file(str(path))
    dc.start()
    return dc


def _serve(config_path: str, seconds: float | None) -> int:
    dc = _boot(config_path)
    gw = dc.gateway
    log.info(
        "Data center '%s' avviato, %d adapter, gateway %s:%s",
        dc.config.name,
        len(dc.adapters),
        gw.host if gw else "-",
        gw.port if gw else "-",
    )
    try:
        if seconds is None:
            while True:
                time.sleep(1)
        else:
            time.sleep(seconds)
    except KeyboardInterrupt:
        log.info("Arresto")
    finally:
        dc.stop()
    return 0


def _demo(config_path: str, seconds: float) -> int:
    dc = _boot(config_path)
    try:
        dc.wait_tags(count=3, timeout=max(seconds, 2.0))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            _print_snapshot(dc, "*")
            time.sleep(0.5)
    finally:
        dc.stop()
    return 0


def _snapshot(config_path: str, seconds: float, pattern: str) -> int:
    dc = _boot(config_path)
    try:
        dc.wait_tags(count=1, timeout=seconds)
        payload = [upd.as_dict() for upd in dc.bus.snapshot(pattern).values()]
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    finally:
        dc.stop()
    return 0


def _catalog(config_path: str, include_disabled: bool) -> int:
    from data_center.catalog import catalog_from_config
    from data_center.config import load_datacenter_config

    cfg = load_datacenter_config(config_path)
    tags = catalog_from_config(cfg, include_disabled=include_disabled)
    json.dump([t.as_dict() for t in tags], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _bind(config_path: str, profile_path: str, include_disabled: bool) -> int:
    from data_center.catalog import catalog_from_config
    from data_center.config import load_datacenter_config
    from data_center.teststand_bind import BindError, MemoryGlobals, bind_profile, load_profile

    cfg = load_datacenter_config(config_path)
    catalog = catalog_from_config(cfg, include_disabled=include_disabled)
    profile = load_profile(profile_path)
    try:
        bound = bind_profile(catalog, profile)
    except BindError as exc:
        json.dump({"ok": False, "missing": exc.missing}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2
    globals_tree = MemoryGlobals()
    globals_tree.create_from_bind(bound)
    json.dump(
        {
            "ok": True,
            "profile": profile.name,
            "root": profile.root,
            "signals": [item.as_dict() for item in bound],
            "station_globals": globals_tree.as_dict(),
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


def _print_snapshot(dc: DataCenter, pattern: str) -> None:
    tags = dc.bus.snapshot(pattern)
    print(f"-- {len(tags)} tag --")
    for name in sorted(tags):
        upd = tags[name]
        value = upd.value
        if isinstance(value, float):
            text = f"{value:10.4f}"
        else:
            text = f"{value!s:>10}"
        print(f"  {name:32} {text} {upd.unit:6} {upd.quality.value:9} {upd.source}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
