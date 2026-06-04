from dbxstats.ui.fpspick import pick, pid_of


def _entry(fps: int, app: str):
    return (fps, app, 0.0, fps, fps, 0, 0)


def test_pick_by_pin():
    by = {1: _entry(60, "a.exe"), 2: _entry(120, "game.exe")}
    assert pick(by, 0, "game.exe")[1] == "game.exe"


def test_pin_not_found_returns_none():
    by = {1: _entry(60, "a.exe")}
    assert pick(by, 0, "missing.exe") is None


def test_pick_foreground():
    by = {1: _entry(60, "a.exe"), 2: _entry(120, "b.exe")}
    assert pick(by, 1, "")[1] == "a.exe"


def test_pick_best_non_system():
    by = {1: _entry(200, "dwm.exe"), 2: _entry(90, "game.exe")}
    assert pick(by, 0, "")[1] == "game.exe"


def test_pick_empty():
    assert pick({}, 0, "") is None


def test_pid_of():
    e = _entry(60, "a.exe")
    assert pid_of({5: e}, e) == 5
