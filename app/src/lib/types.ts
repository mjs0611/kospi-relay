export type Pair = [number, number] | null

export interface Freq { bin: string; n: number; up: number; flat: number; down: number; years: number }

// 카드 맨 위 한 줄. 렌더: lead + <b class=z-{zone}>num</b> + tail
export interface Head { lead: string; num: string; tail: string; zone: 'up' | 'flat' | 'down' | null }

export interface RelayDay {
  date: string
  status: 'pending' | 'filled' | 'closed'
  prev: { date: string; kospi: number; kosdaq: number | null }
  us: { SOXX: Pair; QQQ: Pair; SPY: Pair }
  vix: Pair
  open: number | null
  freq: Freq | null
  head?: Head | null           // 2026-09-07 이후 JSON에만 있음 — 없으면 미표시
  sentence: string | null
  svg: string
  built_at?: string
}
