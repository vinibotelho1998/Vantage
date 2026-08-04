from dbxstats.core import units


def test_rate_scales():
    assert units.rate(500) == "500 B/s"
    assert units.rate(2048) == "2 KB/s"
    assert units.rate(5 * 1024 ** 2) == "5.0 MB/s"
    assert units.rate(None) == units.DASH


def test_size_scales():
    assert units.size(1536) == "2 KB"
    assert units.size(3 * 1024 ** 3) == "3.0 GB"


def test_clock_switches_unit():
    assert units.clock(800) == "800 MHz"
    assert units.clock(4800) == "4.80 GHz"
    assert units.clock(None) == units.DASH


def test_mhz_has_no_thousand_separator():
    assert units.mhz(10501) == "10501 MHz"


def test_temp_watts_percent():
    assert units.temp(62.4) == "62 °C"
    assert units.watts(180.25) == "180.2 W"
    assert units.percent(42.6) == "43%"


def test_duration_formats():
    assert units.duration(0) == "00:00:00"
    assert units.duration(3661) == "01:01:01"
    assert units.duration(90000) == "1d 01:00"


def test_compact():
    assert units.compact(950) == "950"
    assert units.compact(1500) == "1.5k"
    assert units.compact(2_500_000) == "2.5M"


def test_mib_pair():
    assert units.mib_pair(4096, 8192) == "4.0 / 8.0 GB"
    assert units.mib_pair(None, 8192) == units.DASH


def test_sensor_value_precision_by_unit():
    assert units.sensor_value(1.23456, "V") == "1.235 V"
    assert units.sensor_value(2745.0, "MHz") == "2745 MHz"
    assert units.sensor_value(None, "°C") == units.DASH
