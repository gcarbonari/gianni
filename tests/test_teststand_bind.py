from __future__ import annotations

import pytest

from data_center.catalog import catalog_from_config, find_tags
from data_center.config import load_datacenter_config
from data_center.models import Quality, TagUpdate
from data_center.teststand_bind import (
    BindError,
    MemoryGlobals,
    bind_profile,
    check_limits,
    load_profile,
)


def test_catalog_from_databases() -> None:
    cfg = load_datacenter_config("config.datacenter.yaml")
    tags = catalog_from_config(cfg)
    names = {t.name for t in tags}
    assert "veh.EEC1.EngineSpeed" in names
    assert "veh.CCVS.WheelBasedSpeed" in names
    assert "avionics.heading" in names
    assert "plc.Temperatura" in names
    assert "siemens.ch00" not in names
    with_disabled = catalog_from_config(cfg, include_disabled=True)
    disabled_names = {t.name for t in with_disabled}
    assert "siemens.ch00" in disabled_names


def test_bind_profile_creates_station_globals() -> None:
    cfg = load_datacenter_config("config.datacenter.yaml")
    catalog = catalog_from_config(cfg)
    profile = load_profile("profiles/vehicle_smoke.yaml")
    bound = bind_profile(catalog, profile)
    paths = {item.ts_path: item.tag for item in bound}
    assert paths["StationGlobals.DC.veh.EEC1.EngineSpeed"] == "veh.EEC1.EngineSpeed"
    assert "StationGlobals.DC.plc.Temperatura" in paths
    tree = MemoryGlobals()
    tree.create_from_bind(bound)
    snap = {
        "veh.EEC1.EngineSpeed": TagUpdate(
            "veh.EEC1.EngineSpeed", 1200.0, 0, "can_vehicle", Quality.GOOD, "rpm"
        ),
        "plc.Temperatura": TagUpdate(
            "plc.Temperatura", 25.0, 0, "plc_modbus", Quality.GOOD, "°C"
        ),
        "veh.CCVS.WheelBasedSpeed": TagUpdate(
            "veh.CCVS.WheelBasedSpeed", 40.0, 0, "can_vehicle", Quality.GOOD, "km/h"
        ),
        "avionics.heading": TagUpdate(
            "avionics.heading", 90.0, 0, "arinc_avionics", Quality.GOOD, "deg"
        ),
    }
    written = tree.sync_snapshot(bound, snap)
    assert written == 4
    assert tree.get_val("StationGlobals.DC.veh.EEC1.EngineSpeed") == 1200.0
    assert check_limits(bound, snap) == []


def test_bind_fails_if_dut_database_changed() -> None:
    cfg = load_datacenter_config("config.datacenter.yaml")
    catalog = catalog_from_config(cfg)
    profile = load_profile("profiles/vehicle_smoke.yaml")
    profile = type(profile)(
        name=profile.name,
        root=profile.root,
        require=profile.require + ("veh.DoesNotExist",),
        patterns=profile.patterns,
        blocks=profile.blocks,
        limits=profile.limits,
    )
    with pytest.raises(BindError) as exc:
        bind_profile(catalog, profile)
    assert "veh.DoesNotExist" in exc.value.missing


def test_pattern_selects_family() -> None:
    cfg = load_datacenter_config("config.datacenter.yaml")
    catalog = catalog_from_config(cfg)
    eec1 = find_tags(catalog, "veh.EEC1.*")
    assert {t.name for t in eec1} == {"veh.EEC1.EngineSpeed", "veh.EEC1.EngineTorque"}
