# 2026-09-07 앱인토스 배포 — 답을 차트 안에

- deploymentId: `01a079d6-f414-7d02-b972-91894d211fc3`
- 테스트: `intoss-private://kospi-relay?_deploymentId=01a079d6-f414-7d02-b972-91894d211fc3&host=appsInTossHost`
- 시드: `2026-09-07 filled` (head 포함, 오늘 시가 +3.34%)
- 코드: `790dfe0` + 이 커밋(시가 행 2단 배치)
- 차트 SVG는 미니앱이 매번 latest.json에서 받아 그리므로, 이 커밋의 배치 수정은 재배포 없이 반영된다. 시드(첫 페인트)만 이전 배치.

## 스케줄 관찰 (9/7)

새 cron 5개(06:47/07:20/09:09/09:40/10:30)가 오늘 **하나도 실행되지 않았다**. 워크플로 state는 active, main의 relay.yml에 cron 5개 확인됨.
9/6 23:13Z에 옛 cron이 1시간 28분 늦게 돈 기록은 있음. 오늘 낮 12시에 수동 morning을 돌려 filled가 pending으로 덮였고, open을 다시 돌려 복구함.
판단 보류: 워크플로 변경 직후 첫날인지, GitHub 스케줄 지연·누락인지 내일(9/8) 실행 로그로 확인. 이틀 연속 누락이면 외부 트리거(launchd → `gh workflow run`)를 붙인다.
