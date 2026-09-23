import pandas as pd
from evaluate_signal import scores, evaluate

frame = pd.DataFrame({"gap": [.01, -.01, 0], "s": [.01, -.01, 0]},
                     index=pd.to_datetime(["2026-09-03", "2026-09-04", "2026-09-07"]))
result = scores(frame, frame.s)
assert result["mae_percentage_points"] == 0
assert result["direction_accuracy"] == 1 and result["selected_n"] == 2
assert scores(frame, [0, 0, 0])["selected_direction_accuracy"] is None
assert evaluate(frame)["after_original_selection"]["fixed_formula"]["n"] == 1
print("signal evaluation: error units, coverage, empty selection and temporal split passed")
