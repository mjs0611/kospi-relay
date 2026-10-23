# 밤사이 코스피 (kospi-relay)

## 기존 게시 데이터로 UI만 배포하기

공식 `relay` 워크플로의 수동 `phase=restyle`은 최신 `gh-pages` HTML에 새 CSS·공통 탐색·표 조작·공용 방문 통계 로더·favicon 선언·웹 모션을 적용하고 개인정보처리방침에 통계 안내를 추가합니다. 가격 API를 조회하거나 JSON·공유 이미지를 재생성하지 않습니다. 공개된 시장 수치·문구·표를 그대로 보존하며, 기존 게시본이 없거나 템플릿을 해석할 수 없거나 보호 대상 비 HTML 파일 해시가 달라지면 실패합니다. 관리 자산 `favicon.svg`와 `motion.js`를 새 소스로 갱신합니다. 모든 페이지를 먼저 검증한 뒤 쓰며 반복 실행해도 래퍼·스크립트를 중복 삽입하지 않습니다.

`<head>`가 없는 기타 HTML은 경고를 남기고 그대로 둡니다. 홈(`index.html`)·개인정보처리방침(`privacy/index.html`)이나 `site-header`가 있는 페이지에 `<head>`가 없으면 실패하며, HTML 파일을 쓰지 않습니다.

기존 스케줄·기본 `morning` 단계·권한·CNAME·광고 설정과 일반 가격 수집 경로는 변경하지 않습니다. 기존 게시판을 복원한 검토 작업본에서 `python relay.py restyle`로 오프라인 검증할 수 있으며, fixture를 운영 데이터로 게시하지 않습니다.

일일 생성과 `backfill`은 기존 콘텐츠 캡처 `relay.png`를 유지하고 날짜별 `YYYY-MM-DD/og.png`(1200×630)를 같은 Playwright 캡처 경로로 별도 생성합니다. 홈·날짜·월별 기록의 OG/Twitter 이미지가 이 가로 카드를 사용합니다. HTML 재생성은 기존 JSON·`relay.png`·이미 있는 OG 이미지를 보존하고, 빠진 OG 이미지만 게시 JSON과 전달된 가격 이력으로 만듭니다. `regenerate(fixture_history)`로 오프라인 검증할 수 있습니다. `selfcheck`는 실제 가격을 조회하므로 오프라인 검사에서 실행하지 않습니다.

`assets/favicon.svg`와 `assets/motion.js`는 일반 생성·HTML 재생성·`restyle` 모두 `site/`로 복사합니다. 모션은 웹 HTML에서만 실행하며 공유 SVG·PNG·미니앱에는 적용하지 않습니다. JavaScript가 없거나 동작 줄이기를 설정하면 최종 수치를 그대로 표시합니다.

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
