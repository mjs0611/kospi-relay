"""Reproducible descriptive evaluation; never publishes or changes the signal."""
import datetime as dt
import json
from pathlib import Path
import sys
import relay as r


def scores(frame, prediction):
    actual = frame.gap.to_numpy()
    predicted = r.np.asarray(prediction)
    selected = r.np.abs(predicted) >= r.FLAT
    direction = r.np.sign(actual) == r.np.sign(predicted)
    return {"n": len(frame), "mae_percentage_points": float(r.np.mean(r.np.abs(actual - predicted)) * 100),
            "direction_accuracy": float(direction.mean()), "coverage_at_0_3pct": float(selected.mean()),
            "selected_n": int(selected.sum()),
            "selected_direction_accuracy": float(direction[selected].mean()) if selected.any() else None}


def evaluate(frame):
    # Coefficients were previously selected using data through 2026-09-04.
    sections = {"exploratory_history": frame, "after_original_selection": frame[frame.index > "2026-09-04"]}
    if 'us_sessions' in frame:
        sections.update({"single_us_session": frame[frame.us_sessions == 1], "multiple_us_sessions": frame[frame.us_sessions > 1]})
    sections.update({str(year): part for year, part in frame.groupby(frame.index.year)})
    return {name: {"fixed_formula": scores(part, part.s), "zero_gap": scores(part, r.np.zeros(len(part))),
                   **({"spy_only_scaled": scores(part, 0.4 * part.spy)} if "spy" in part else {}),
                   "start": str(part.index.min().date()), "end": str(part.index.max().date())}
            for name, part in sections.items() if len(part)}


if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/evaluation-20260923")
    folder.mkdir(parents=True, exist_ok=True)
    csv = folder / "aligned.csv"
    if csv.exists():
        frame = r.pd.read_csv(csv, index_col="D", parse_dates=["D"])
    else:
        raw = r.fetch()
        frame = r.align(raw)
        today = r.pd.Timestamp(dt.datetime.now(r.KST).date())
        frame = frame[frame.index < today]  # Exclude the incomplete current day.
        for key, prices in raw.items():
            prices.to_csv(folder / f"{key}.csv", index_label="date")
        frame.to_csv(csv)
    # Reuse the frozen source files; do not mix a new download into this evaluation.
    if 'spy' not in frame:
        raw = {key: r.pd.read_csv(folder / f"{key}.csv", index_col='date', parse_dates=['date']) for key in r.TICK}
        raw = r.known_us_sessions(raw)
        for D in frame.index:
            previous = raw['KOSPI'].index[raw['KOSPI'].index < D][-1]
            window = r.us_window(raw['SPY'], previous, D)
            frame.loc[D, 'spy'] = window[1]
            frame.loc[D, 'us_sessions'] = window[2]
        frame.to_csv(csv)
    if frame.empty:
        raise ValueError("No complete aligned observations")
    result = {"evaluated_at": dt.datetime.now(r.KST).isoformat(), "source_snapshot": str(folder),
              "exclusions": "Current KST day, missing/invalid endpoint prices and missing known peer sessions are excluded by align(). Raw CSVs preserved for audit.", "source": "yfinance unadjusted daily Open/Close",
              "formula": "0.4 * (SPY + SOXX) / 2", "target": "KOSPI open / previous KOSPI session close - 1",
              "interpretation": "Historical description; no trading recommendation. Post-selection sample may be too small.",
              "results": evaluate(frame)}
    (folder / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))
