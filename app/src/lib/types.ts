export type Pair = [number, number] | null

export interface Freq { bin: string; n: number; up: number; flat: number; down: number; years: number }

export interface RelayDay {
  date: string
  status: 'pending' | 'filled' | 'closed'
  prev: { date: string; kospi: number; kosdaq: number | null }
  us: { SOXX: Pair; QQQ: Pair; SPY: Pair }
  vix: Pair
  open: number | null
  freq: Freq | null
  sentence: string | null
  svg: string
  built_at?: string
}
