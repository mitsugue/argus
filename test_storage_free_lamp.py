"""2026-10-20 (owner: 恒久性): the system state shows the persistent disk's free space against the start's need."""
import scanner

MIB = 1024 * 1024


def lamp(monkeypatch, free, required=111 * MIB):
    monkeypatch.setattr(scanner, "_storage_capacity_measurement",
                        lambda: {"freeBytes": free, "requiredFreeBytes": required, "totalBytes": 15 * 1024 * MIB})
    return {l["key"]: l for l in scanner._system_health(allow_provider_fetch=False)["lamps"]}["storage"]


def test_plenty_of_space_is_green(monkeypatch):
    out = lamp(monkeypatch, 12 * 1024 * MIB)
    assert out["status"] == "ok" and "空き 12.0GiB" in out["detailJa"] and "111MiB" in out["detailJa"]


def test_below_ten_times_the_need_warns(monkeypatch):
    out = lamp(monkeypatch, 900 * MIB)
    assert out["status"] == "warning" and "10倍" in out["detailJa"]


def test_below_twice_the_need_is_red_before_the_start_stops(monkeypatch):
    out = lamp(monkeypatch, 150 * MIB)
    assert out["status"] == "stopped" and "次の起動が止まる" in out["detailJa"]


def test_unmeasurable_space_is_unconfirmed(monkeypatch):
    monkeypatch.setattr(scanner, "_storage_capacity_measurement", lambda: {})
    out = {l["key"]: l for l in scanner._system_health(allow_provider_fetch=False)["lamps"]}["storage"]
    assert out["status"] == "warning" and "未確認" in out["detailJa"]


def test_a_red_storage_lamp_does_not_degrade_the_analysis():
    import inspect
    import argus_visibility
    assert '"storage"' not in inspect.getsource(argus_visibility)
