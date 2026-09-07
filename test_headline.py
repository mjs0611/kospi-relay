"""headline()·sentence() 검증. relay.py는 pandas·yfinance를 import하므로 통째로 못 불러온다.
ast로 필요한 정의만 뽑아 실행한다. 실행: python3 test_headline.py"""
import ast, pathlib, html

src = pathlib.Path(__file__).with_name("relay.py").read_text()
tree = ast.parse(src)
keep = {"FLAT", "OPENED", "SIDE", "pct", "zone_of", "headline", "head_html", "sentence"}
mod = ast.Module(body=[n for n in tree.body
                       if (isinstance(n, ast.FunctionDef) and n.name in keep)
                       or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in keep for t in n.targets))], type_ignores=[])
ns = {"html": html}; exec(compile(mod, "relay-slice", "exec"), ns)
headline, zone_of, sentence, FLAT = ns["headline"], ns["zone_of"], ns["sentence"], ns["FLAT"]

f = {"n": 541, "up": 174, "flat": 277, "down": 90, "bin": "보합", "years": 5.6}
fu = {"n": 277, "up": 222, "flat": 45, "down": 10, "bin": "강한 상승", "years": 5.6}
t = headline(f, None, "pending")["text"];   assert t == "뉴욕이 이렇게 마감한 밤 541번, 코스피 시가는 51%가 ±0.3% 안에서 열렸다", t
t = headline(fu, None, "pending")["text"];  assert "80%가 위로 열렸다" in t, t
h = headline(f, 0.0276, "filled");          assert h["zone"] == "up" and h["text"] == "코스피 시가 +2.76%, 이런 밤 32%만 갔던 위쪽", h
h = headline(f, 0.0026, "filled");          assert h["zone"] == "flat" and "51%가 그랬듯 ±0.3% 안" in h["text"], h
h = headline(f, -0.0052, "filled");         assert h["zone"] == "down" and "17%만 갔던 아래쪽" in h["text"], h
h = headline(f, None, "closed");            assert h["text"].startswith("오늘은 휴장. 뉴욕이"), h
h = headline({"n": 10, "up": 5, "flat": 3, "down": 2, "years": 5.6}, 0.01, "filled"); assert "10번뿐" in h["text"] and h["zone"] == "up", h
assert headline(None, None, "pending")["text"] == "밤사이 뉴욕 휴장"
assert "위로" in sentence(fu)                                   # relay.py selfcheck와 같은 계약
assert zone_of(FLAT) == "flat" and zone_of(FLAT + 1e-9) == "up" and zone_of(-FLAT - 1e-9) == "down"
for s_ in (headline(f, None, "pending")["text"], headline(f, 0.0276, "filled")["text"], sentence(f)):
    assert "—" not in s_ and "·" not in s_ and "습니다" not in s_, s_   # 줄표·중점·합쇼체 금지
out = ns["head_html"](headline(f, 0.0276, "filled")); assert out.startswith('<p class="headline">') and "<b" not in out, out
print("headline ok")
