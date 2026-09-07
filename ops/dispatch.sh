#!/bin/sh
# Mac launchd가 06:45·09:06(평일)에 실행. GitHub cron이 4~5시간씩 늦어서(9/7 실측) 정시 트리거를 Mac이 맡는다.
# 시각으로 단계 결정: 8시 전 morning(아침 카드), 15시 전 open(시가 채움), 그 뒤 close(마감 반영). 워크플로는 멱등이라 중복 실행 무해.
H=$(date +%H)
if [ "$H" -lt 8 ]; then PHASE=morning; elif [ "$H" -lt 15 ]; then PHASE=open; else PHASE=close; fi
echo "$(date '+%F %T') dispatch $PHASE"
exec /opt/homebrew/bin/gh workflow run relay.yml -R mjs0611/kospi-relay -f phase=$PHASE
