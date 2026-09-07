import seed from '../seed.json'
import type { DayRef, RelayDay } from './types'

export const BASE = 'https://mjs0611.github.io/kospi-relay'
const KEY = 'relay:latest:v1'

// 첫 페인트는 네트워크에 의존하지 않는다: 번들 시드 → localStorage 캐시 → 네트워크 갱신
export function cachedLatest(): RelayDay {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) { const d = JSON.parse(raw) as RelayDay; if (d.date >= (seed as unknown as RelayDay).date) return d }
  } catch { /* storage optional */ }
  return seed as unknown as RelayDay
}

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}/${path}?t=${Math.floor(Date.now() / 60000)}`, { signal: AbortSignal.timeout(8000) })
  if (!r.ok) throw new Error(String(r.status))
  return r.json() as Promise<T>
}

export async function fetchLatest(): Promise<RelayDay> {
  const d = await getJson<RelayDay>('latest.json')
  try { localStorage.setItem(KEY, JSON.stringify(d)) } catch { /* noop */ }
  return d
}

export const fetchDay = (date: string) => getJson<RelayDay>(`days/${date}.json`)
// 옛 index.json은 날짜 문자열 배열이었다. 둘 다 받는다
export const fetchIndex = async (): Promise<DayRef[]> =>
  (await getJson<(string | DayRef)[]>('index.json')).map((x) => (typeof x === 'string' ? { d: x, z: null } : x))

// 딥링크 /d/YYYY-MM-DD → 해당 날짜. 후행 슬래시 정규화 (검수 스킴 게이트)
export function dateFromPath(): string | null {
  const p = location.pathname.replace(/\/+$/, '')
  const m = p.match(/^\/d\/(\d{4}-\d{2}-\d{2})$/)
  return m ? m[1] : null
}
