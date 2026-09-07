#!/bin/sh
# Mac launchd가 06:45·09:06(평일)에 실행. GitHub cron이 4~5시간씩 늦어서(9/7 실측) 정시 트리거를 Mac이 맡는다.
# 시각으로 단계 결정: 8시 전이면 morning(아침 카드), 그 뒤면 open(시가 채움). 워크플로는 멱등이라 중복 실행 무해.
H=$(date +%H)
if [ "$H" -lt 8 ]; then PHASE=morning; else PHASE=open; fi
echo "$(date '+%F %T') dispatch $PHASE"
exec /opt/homebrew/bin/gh workflow run relay.yml -R mjs0611/kospi-relay -f phase=$PHASE
