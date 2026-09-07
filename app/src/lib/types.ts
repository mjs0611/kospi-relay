export type Pair = [number, number] | null

export interface Freq { bin: string; n: number; up: number; flat: number; down: number; years: number }

// 제목 두 줄. cond = 조건('뉴욕이 크게 오른 밤'), claim = 규칙('다음 날 코스피는 10번 중 8번 위로 열렸다')
export interface Head { cond: string; claim: string; zone: 'up' | 'flat' | 'down' | null }

export interface RelayDay {
  date: string
  status: 'pending' | 'filled' | 'closed'
  prev: { date: string; kospi: number; kosdaq: number | null }
  us: { SOXX: Pair; QQQ: Pair; SPY: Pair }
  vix: Pair
  open: number | null
  freq: Freq | null
  head?: Head | null           // 없으면 미표시
  sentence: string | null
  ny?: string                  // 밤사이 뉴욕 SVG
  kr?: string                  // 다음 날 코스피 시가 SVG
  built_at?: string
}
