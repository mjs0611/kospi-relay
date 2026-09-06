"""headline() 단위 검증. relay.py는 pandas·yfinance를 import하므로 통째로 못 불러온다 —
ast로 필요한 정의만 뽑아 실행한다. 실행: python3 test_headline.py"""
import ast, pathlib, html

src = pathlib.Path(__file__).with_name("relay.py").read_text()
tree = ast.parse(src)
keep = {"FLAT", "ZONE_WORD", "pct", "zone_of", "headline", "head_html"}
mod = ast.Module(body=[n for n in tree.body
                       if (isinstance(n, ast.FunctionDef) and n.name in keep)
                       or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in keep for t in n.targets))], type_ignores=[])
ns = {"html": html}; exec(compile(mod, "relay-slice", "exec"), ns)
headline, zone_of, FLAT = ns["headline"], ns["zone_of"], ns["FLAT"]

f = {"n": 541, "up": 174, "flat": 277, "down": 90, "bin": "보합", "years": 5.6}
h = headline(f, None, "pending");            assert h["num"] == "51%" and h["zone"] == "flat" and "09:00" in h["tail"], h
h = headline(f, 0.0276, "filled");           assert h["zone"] == "up" and "32%만" in h["tail"] and h["num"] == "+2.76%", h
h = headline(f, 0.0026, "filled");           assert h["zone"] == "flat" and "51%가 그랬듯" in h["tail"], h
h = headline(f, -0.0052, "filled");          assert h["zone"] == "down" and "17%만" in h["tail"], h
h = headline(f, None, "closed");             assert h["lead"].startswith("오늘 휴장") and h["num"] == "51%", h
h = headline({"n": 10, "up": 5, "flat": 3, "down": 2}, 0.01, "filled"); assert "생략" in h["tail"] and h["zone"] == "up", h
h = headline(None, None, "pending");         assert h["num"] == "" and "생략" in h["tail"], h
assert zone_of(FLAT) == "flat" and zone_of(FLAT + 1e-9) == "up" and zone_of(-FLAT - 1e-9) == "down"   # frequency()의 g > FLAT 와 같은 경계
out = ns["head_html"](headline(f, 0.0276, "filled")); assert 'class="z-up"' in out and "&lt;" not in out and "+2.76%" in out, out
print("headline ok")
