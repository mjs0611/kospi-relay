// 배포 전 실행: 라이브 latest.json을 번들 시드로 — 첫 페인트가 네트워크에 의존하지 않게
import { writeFileSync } from 'node:fs'
const r = await fetch('https://mjs0611.github.io/kospi-relay/latest.json')
if (!r.ok) throw new Error(`latest.json ${r.status}`)
const d = await r.json()
writeFileSync(new URL('../src/seed.json', import.meta.url), JSON.stringify(d))
console.log('seed', d.date, d.status, `${JSON.stringify(d).length}B`)
