"""실행: python test_missing_prices.py — 최신 종가 결측 시에도 시가 카드와 유효 JSON을 발행한다."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import relay as r


class Clock(r.dt.datetime):
    at = r.dt.datetime(2026, 9, 11, 16, tzinfo=r.KST)

    @classmethod
    def now(cls, tz=None):
        return cls.at


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

    # 자료 부재와 정상 자료를 구분하고, 유한하지만 비정상적으로 큰 신호도 처리한다.
    assert r.us_window(prices.loc[prices.index < P], P, D) is None
    assert "자료가 없어요" in r.headline(None, None, "pending")["cond"]
    assert r.frequency(baseline, 0.006)["bin"] == "강한 상승"
    assert r.frequency(baseline, 10)["bin"] == "자료 대기"

    # 빈 응답·통신 예외는 총 3번까지만 재조회한다. 가격 결측의 날짜는 지우지 않는다.
    with patch.object(r, "TICK", {"KOSPI": "^KS11"}), patch.object(r.yf, "Ticker") as ticker, patch.object(r.time, "sleep") as sleep:
        history = ticker.return_value.history
        history.side_effect = [prices.iloc[:0], TimeoutError("temporary"), prices.copy()]
        assert r.fetch()["KOSPI"].equals(prices)
        assert history.call_count == 3 and [c.args[0] for c in sleep.call_args_list] == [2, 5]
        history.reset_mock()
        history.side_effect = [TimeoutError("offline")] * 3
        try:
            r.fetch()
            raise AssertionError("persistent outage must block publication")
        except RuntimeError:
            assert history.call_count == 3
        incomplete = prices.copy()
        incomplete.loc[D, "Close"] = r.np.inf
        history.side_effect = [incomplete.copy() for _ in range(3)]
        got = r.fetch()["KOSPI"]
        assert D in got.index and r.pd.isna(got.loc[D, "Close"])

    raw = {k: prices.copy() for k in r.TICK}
    with tempfile.TemporaryDirectory() as tmp, patch.object(r, "SITE", Path(tmp)), patch.object(r, "fetch", return_value=raw) as fetch, patch.object(r, "screenshot", side_effect=screenshot), patch.dict(r.os.environ, {"RELAY_DATE": "2026-09-10", "RELAY_FINAL": "1"}):
        latest = Path(tmp) / "latest.json"
        r.build("close")
        good = json.loads(latest.read_text())
        for k in r.US:
            raw[k].loc[P, "Close"] = r.np.nan
        raw["KOSPI"].loc[D, ["Open", "Close"]] = r.np.nan
        r.build("morning")
        recovered = json.loads(latest.read_text())
        assert recovered["status"] == "done"
        for key in ("us", "open", "close"):
            assert recovered[key] == good[key], key
        r.backfill(1)
        archive = Path(tmp) / "days/2026-09-10.json"
        recovered_archive = json.loads(archive.read_text())
        for key in ("status", "us", "open", "close"):
            assert recovered_archive[key] == good[key], key
        archive_snapshot = archive.read_bytes()
        snapshot = latest.read_bytes()
        raw["KOSPI"] = raw["KOSPI"].drop(P)
        r.build("open")
        assert latest.read_bytes() == snapshot
        r.backfill(1)
        assert archive.read_bytes() == archive_snapshot
        older = dict(recovered, date="2026-09-09")
        latest.write_text(json.dumps(older))
        older_snapshot = latest.read_bytes()
        r.build("open")
        assert latest.read_bytes() == older_snapshot  # 새 날짜에서도 이미 확인된 거래일 누락을 감지한다.
        latest.write_bytes(snapshot)
        raw["KOSPI"] = prices.loc[[D]]
        try:
            r.build("open")
            raise AssertionError("insufficient history must block publication")
        except RuntimeError:
            assert latest.read_bytes() == snapshot

        # 늦게 들어온 과거 날짜 작업은 최신 화면을 덮지 않는다.
        with patch.dict(r.os.environ, {"RELAY_DATE": "2026-09-09"}):
            fetch.reset_mock()
            r.build("open")
            fetch.assert_not_called()
            assert latest.read_bytes() == snapshot

        # 15:39까지는 장중. 명시적 close나 지연된 open도 실제 시각을 따른다.
        raw.update({k: prices.copy() for k in r.TICK})
        for hour, minute, phase, expected in [(8, 59, "close", "pending"), (9, 0, "morning", "filled"), (15, 39, "close", "filled"), (15, 40, "open", "done")]:
            latest.unlink(missing_ok=True)
            Clock.at = Clock(2026, 9, 10, hour, minute, tzinfo=r.KST)
            r.build(phase)
            result = json.loads(latest.read_text())
            assert result["status"] == expected
            assert (result["close"] is not None) == (expected == "done")
        Clock.at = Clock(2026, 9, 10, 11, tzinfo=r.KST)
        latest.unlink()
        raw["KOSPI"] = prices.drop(D)
        r.build("open")
        assert json.loads(latest.read_text())["status"] == "pending"  # 최종 재시도도 결측≠휴장
        # 당일 backfill은 장중 Close를 확정 마감으로 발행하지 않는다.
        day = Path(tmp) / "days/2026-09-10.json"
        snapshot = day.read_bytes()
        raw["KOSPI"] = prices.copy()
        r.backfill(1)
        assert day.read_bytes() == snapshot
        Clock.at = Clock(2026, 9, 11, 16, tzinfo=r.KST)

        # 보조 지수 기준행 부족·국내 이전 종가 결측도 잘못된 숫자로 발행하지 않는다.
        latest.unlink()
        raw["KOSDAQ"] = prices.loc[[P]]
        raw["KOSPI"].loc[P, "Close"] = 0
        r.build("open")
        result = json.loads(latest.read_text())
        assert result["prev"]["kospi"] is None and result["prev"]["kosdaq"] is None
        assert result["open"] is None and result["status"] == "pending"

    # Mac 정시 트리거도 같은 시간 경계. gh 실행을 출력으로 치환해 실제 dispatch를 막는다.
    script = Path(__file__).with_name("ops").joinpath("dispatch.sh").read_text()
    assert script.count("exec /opt/homebrew/bin/gh") == 1
    script = script.replace("exec /opt/homebrew/bin/gh", "printf '%s\\n'")
    with tempfile.TemporaryDirectory() as tmp:
        fake_date = Path(tmp) / "date"
        fake_date.write_text('#!/bin/sh\nprintf "%s\\n" "$RELAY_TEST_HM"\n')
        fake_date.chmod(0o755)
        for hm, phase in [("0859", "morning"), ("0900", "open"), ("1539", "open"), ("1540", "close")]:
            output = subprocess.check_output(["sh", "-c", script], env={**os.environ, "PATH": tmp + ":" + os.environ["PATH"], "RELAY_TEST_HM": hm}, text=True)
            assert output.splitlines()[-1] == "phase=" + phase
    print("missing prices ok")


if __name__ == "__main__":
    with patch.object(r.dt, "datetime", Clock), contextlib.redirect_stdout(io.StringIO()):
        check()
    print("missing prices ok")
