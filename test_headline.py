"""headline()·sentence()·freq_svg() 검증. relay.py는 pandas·yfinance를 import하므로 통째로 못 불러온다.
ast로 필요한 정의만 뽑아 실행한다. 실행: python3 test_headline.py"""
import ast, pathlib, html

src = pathlib.Path(__file__).with_name("relay.py").read_text()
tree = ast.parse(src)
keep = {"FLAT", "NIGHT", "WENT", "LABEL_Z", "tenths", "pct", "zone_of", "headline", "head_html", "sentence", "freq_svg"}
mod = ast.Module(body=[n for n in tree.body
                       if (isinstance(n, ast.FunctionDef) and n.name in keep)
                       or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in keep for t in n.targets))], type_ignores=[])
ns = {"html": html}; exec(compile(mod, "relay-slice", "exec"), ns)
headline, zone_of, sentence, freq_svg, FLAT = ns["headline"], ns["zone_of"], ns["sentence"], ns["freq_svg"], ns["FLAT"]

f = {"n": 541, "up": 174, "flat": 277, "down": 90, "bin": "보합", "years": 5.6}
fu = {"n": 277, "up": 222, "flat": 45, "down": 10, "bin": "강한 상승", "years": 5.6}
t = headline(f, None, "pending")["text"];   assert t == "뉴욕이 조용했던 밤. 다음 날 코스피는 10번 중 5번 거의 그대로 열렸다", t
t = headline(fu, None, "pending")["text"];  assert t == "뉴욕이 크게 오른 밤. 다음 날 코스피는 10번 중 8번 위로 열렸다", t
h = headline(fu, 0.0334, "filled");         assert h["zone"] == "up" and h["text"] == "뉴욕이 크게 오른 밤 다음 날, 코스피는 +3.34%로 열렸다. 10번 중 8번 있는 일", h
h = headline(f, 0.0276, "filled");          assert h["text"].endswith("+2.76%로 열렸다. 10번 중 3번뿐인 일"), h
h = headline(fu, -0.009, "filled");         assert h["zone"] == "down" and h["text"].endswith("100번 중 4번 있는 일"), h
h = headline(f, None, "closed");            assert h["text"] == "뉴욕이 조용했던 밤. 오늘 코스피는 휴장", h
h = headline({"n": 10, "up": 5, "flat": 3, "down": 2, "bin": "상승", "years": 5.6}, 0.01, "filled"); assert h["text"] == "뉴욕이 오른 밤 다음 날, 코스피는 +1.00%로 열렸다", h
assert headline(None, None, "pending")["text"] == "밤사이 뉴욕은 쉬었다"
assert "위로" in sentence(fu)                                   # relay.py selfcheck와 같은 계약
assert zone_of(FLAT) == "flat" and zone_of(FLAT + 1e-9) == "up" and zone_of(-FLAT - 1e-9) == "down"
for s_ in (headline(f, None, "pending")["text"], headline(fu, 0.0334, "filled")["text"], sentence(f)):
    assert "—" not in s_ and "·" not in s_ and "습니다" not in s_ and "이런 밤" not in s_, s_   # 줄표·중점·합쇼체·'이런 밤' 금지
svg = freq_svg(fu, 0.0334, "filled");  assert svg.count("<rect") == 3 and "<path" in svg and "+3.34%" in svg and "위 80%" in svg, svg[:200]
svg = freq_svg(fu, None, "pending");   assert "<path" not in svg and "09:00" in svg
assert freq_svg({"n": 10, "up": 5, "flat": 3, "down": 2, "bin": "상승", "years": 5.6}, None, "pending") == ""
print("headline ok")
