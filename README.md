# 밤사이 코스피 (kospi-relay)

전일 코스피 마감 → 밤사이 뉴욕(SOXX·QQQ·SPY·VIX) → 오늘 코스피 시가. 매일 아침 한 장 + 조건부 빈도 한 줄.
예측·판정 없음. 과거 빈도 서술만. 설계: `docs/superpowers/specs/2026-09-05-kospi-relay-design.md`

```
pip install -r requirements.txt && playwright install chromium
python relay.py selfcheck
python test_missing_prices.py && python test_headline.py
RELAY_DATE=2026-09-04 python relay.py open   # 로컬 재현
```

정시 트리거는 Mac launchd(`ops/com.junseungmo.kospi-relay.plist` → `ops/dispatch.sh`)가 평일 06:45(`morning`)·09:06(`open`)·15:40(`close`)에 `gh workflow run`으로 쏜다. GitHub cron은 백업 — 4~5시간 늦게 도는 걸 실측해서 정시는 Mac이 맡는다. 빌드는 GitHub Actions, 배포는 `gh-pages`.

조회는 종목별 최대 3회(15초 제한, 2초·5초 간격) 시도한다. 빈 가격은 이전 날짜의 값으로 채우지 않는다. 같은 날짜·같은 기준일에 이미 확인한 값은 보존하고, 사용할 값이 없으면 자료 대기로 표시한다. 휴장 캘린더가 없으므로 자료 누락만으로 휴장을 확정하지 않는다.

오늘 작업은 실제 KST 시각으로 보정하며 15:40 전에는 마감으로 표시하지 않는다. 이미 발행한 거래일이 원본에서 사라지거나 과거 날짜 작업이 늦게 실행되면 기존 게시물을 유지한다. 원본 조회가 계속 실패하거나 이전 게시물 복원에 실패하면 배포를 중단한다. 경고·실패 사유는 Actions 로그에서 확인한다.

검증한 직접 의존성 버전을 고정했다. 가격 결측·조회 실패·데이터 보존·시간 경계 검사는 코드 push/PR과 매 배포에서 실행한다. 버전 변경 시에도 이 검사를 통과해야 한다.

```
cp ops/com.junseungmo.kospi-relay.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.junseungmo.kospi-relay.plist
tail -f ~/Library/Logs/kospi-relay.log
```
