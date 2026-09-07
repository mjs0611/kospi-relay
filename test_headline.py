"""headline()·sentence()·relay_svg() 검증. relay.py는 pandas·yfinance를 import하므로 통째로 못 불러온다.
ast로 필요한 정의만 뽑아 실행한다. 실행: python3 test_headline.py"""
import ast, pathlib, html

src = pathlib.Path(__file__).with_name("relay.py").read_text()
tree = ast.parse(src)
keep = {"FLAT", "US", "LABEL", "NIGHT", "WENT", "LABEL_Z", "tenths", "pct", "color", "zone_of", "headline", "head_html", "sentence", "ny_svg", "kr_svg"}
mod = ast.Module(body=[n for n in tree.body
                       if (isinstance(n, ast.FunctionDef) and n.name in keep)
                       or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in keep for t in n.targets))], type_ignores=[])
ns = {"html": html}; exec(compile(mod, "relay-slice", "exec"), ns)
headline, zone_of, sentence, ny_svg, kr_svg, FLAT = ns["headline"], ns["zone_of"], ns["sentence"], ns["ny_svg"], ns["kr_svg"], ns["FLAT"]

f = {"n": 541, "up": 174, "flat": 277, "down": 90, "bin": "보합", "years": 5.6}
fu = {"n": 277, "up": 222, "flat": 45, "down": 10, "bin": "강한 상승", "years": 5.6}
us = {"SOXX": (0.01, 0.0352, 1), "QQQ": (0.0, 0.0018, 1), "SPY": (0.0, -0.0039, 1)}
h = headline(fu, None, "pending");  assert h == {"cond": "뉴욕이 크게 오른 밤", "claim": "다음 날 코스피는 10번 중 8번 위로 열렸다", "zone": "up"}, h
h = headline(f, 0.0276, "filled");  assert h["cond"] == "뉴욕이 조용했던 밤" and h["claim"] == "다음 날 코스피는 10번 중 5번 거의 그대로 열렸다", h
h = headline({"n": 10, "up": 5, "flat": 3, "down": 2, "bin": "상승", "years": 5.6}, None, "pending"); assert "10번뿐" in h["claim"], h
h = headline(None, None, "pending"); assert h["cond"] == "밤사이 뉴욕은 쉬었다" and h["claim"] == ""
assert sentence(fu) == "뉴욕이 크게 오른 밤. 다음 날 코스피는 10번 중 8번 위로 열렸다"
assert "위로" in sentence(fu)                                   # relay.py selfcheck와 같은 계약
assert zone_of(FLAT) == "flat" and zone_of(FLAT + 1e-9) == "up" and zone_of(-FLAT - 1e-9) == "down"
for s_ in (sentence(f), sentence(fu), h["cond"]):
    assert "—" not in s_ and "·" not in s_ and "습니다" not in s_ and "이런 밤" not in s_, s_
ny = ny_svg(us); assert ny.count("<rect") == 3 and "+3.52%" in ny and "-0.39%" in ny and "mono" not in ny, ny[:200]
assert "뉴욕 휴장" in ny_svg({})
kr = kr_svg(fu, 0.0334, "filled"); assert kr.count("<rect") == 4 and "위" in kr and "80%" in kr and "오늘 " in kr and "+3.34%" in kr, kr[:300]   # 막대 3 + 오늘 행 칠
kr = kr_svg(fu, None, "pending");  assert kr.count("<rect") == 3 and "09:00" in kr and "+3.34%" not in kr
assert "빈도는 생략" in kr_svg(None, None, "pending")
cond, claim = ns["head_html"](headline(fu, None, "pending")); assert cond.startswith('<p class="cond">') and claim.startswith('<p class="claim">')
print("headline ok")
