"""실행: python test_missing_prices.py — 최신 종가 결측 시에도 시가 카드와 유효 JSON을 발행한다."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import relay as r


def check():
    dates = r.pd.to_datetime(["2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10"])
    prices = r.pd.DataFrame({"Open": [100, 101, 102, 103, 104, 105], "Close": [101, 102, 103, 104, 105, 106]}, index=dates, dtype=float)
    raw = {k: prices.copy() for k in r.TICK}
    D, P = dates[-1], dates[-2]
    baseline = r.align(raw)
    for bad in (r.np.nan, r.np.inf, 0.0):
        for k in (*r.US, "VIX"):
            raw[k].loc[P, "Close"] = bad
        raw["KOSPI"].loc[D, "Close"] = r.np.nan  # 종가 없이 오늘 시가만 도착한 경우
        hist = r.align(raw)
        assert D not in hist.index and len(hist) < len(baseline)
        prev, us, vix, opened, closed = r.today_nodes(raw, D)
        assert us["SPY"] == (None, None, 1)  # 전날 종가로 대체하거나 휴장으로 처리하지 않음
        assert opened == 0.0 and closed is None and vix is None
        f = r.frequency(hist, r.signal(us["SPY"][1], us["SOXX"][1]))
        assert f["bin"] == "자료 대기" and f["n"] == 0
        assert r.headline(f, opened, "filled")["claim"] == "코스피는 +0.00%로 시작했어요"
        assert r.ny_svg(us).count("종가 대기") == 3
        assert "휴장" not in r.ny_svg(us) and "자료가 채워지면" in r.kr_svg(f, opened, "filled")

    def screenshot(_, png):
        png.write_bytes(b"test")

    with tempfile.TemporaryDirectory() as tmp, patch.object(r, "SITE", Path(tmp)), patch.object(r, "fetch", return_value=raw), patch.object(r, "screenshot", side_effect=screenshot), patch.dict(r.os.environ, {"RELAY_DATE": "2026-09-10"}):
        for phase in ("morning", "open", "close"):
            r.build(phase)
            payload = (Path(tmp) / "latest.json").read_text()
            assert "NaN" not in payload and "Infinity" not in payload
            day = json.loads(payload)
            assert day["us"]["SPY"] is None and day["freq"]["bin"] == "자료 대기"
            assert day["status"] == ("pending" if phase == "morning" else "filled")
        r.backfill(1)
        assert json.loads((Path(tmp) / "days/2026-09-10.json").read_text())["freq"]["n"] == 0

    # 실제 휴장과 정상 자료는 기존 표시를 유지한다.
    assert r.us_window(prices.loc[prices.index < P], P, D) is None
    assert "휴장" in r.headline(None, None, "pending")["cond"]
    assert r.frequency(baseline, 0.006)["bin"] == "강한 상승"
    print("missing prices ok")


if __name__ == "__main__":
    check()
