import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import Relay from './components/Relay'
import { cachedLatest, dateFromPath, fetchDay, fetchIndex, fetchLatest } from './lib/data'
import { haptic, shareRelay } from './lib/ait'
import type { RelayDay } from './lib/types'

const TdsButton = lazy(() => import('./components/TdsButton'))

// TDS 청크가 어떤 이유로든 죽어도 앱 전체가 백지가 되지 않게 — 같은 치수의 일반 버튼으로 강등
class Guard extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}

function fmt(d: string) { return `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}` }

export default function App() {
  const [latest, setLatest] = useState<RelayDay>(() => cachedLatest())
  const [day, setDay] = useState<RelayDay | null>(null)          // 지난 날짜 선택 시
  const [dates, setDates] = useState<string[]>([])
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const preloaded = useRef(false)

  useEffect(() => {
    fetchLatest().then(setLatest).catch(() => setStale(true))
    const want = dateFromPath()
    if (want) fetchDay(want).then(setDay).catch(() => {})
    // 첫 페인트 뒤에 목록·TDS 청크
    const t = setTimeout(() => {
      fetchIndex().then(setDates).catch(() => {})
      if (!preloaded.current) { preloaded.current = true; void import('./components/TdsButton') }
    }, 1200)
    return () => clearTimeout(t)
  }, [])

  const shown = day ?? latest
  const pick = async (d: string) => {
    haptic('tickWeak')
    if (d === latest.date) { setDay(null); return }
    setBusy(d)
    try { setDay(await fetchDay(d)) } catch { /* 유지 */ } finally { setBusy(null) }
  }

  return (
    <main className="app">
      <Relay day={shown} />
      {stale && <p className="note">최신 데이터를 못 받아 마지막으로 본 릴레이를 보여드려요.</p>}

      <div className="actions">
        <Guard fallback={<button className="btn-fallback" onClick={() => void shareRelay(shown.sentence ?? `${fmt(shown.date)} 밤사이 코스피`)}>공유하기</button>}>
          <Suspense fallback={<button className="btn-fallback" disabled>공유하기</button>}>
            <TdsButton color="dark" display="full" size="xlarge"
              onClick={() => { haptic('tap'); void shareRelay(shown.sentence ?? `${fmt(shown.date)} 밤사이 코스피`) }}>
              공유하기
            </TdsButton>
          </Suspense>
        </Guard>
      </div>

      {dates.length > 0 && (
        <section className="past">
          <h2>지난 밤들</h2>
          <div className="chips">
            {dates.slice(0, 15).map((d) => (
              <button key={d} className={`chip ${d === shown.date ? 'on' : ''}`} onClick={() => void pick(d)} disabled={busy === d}>
                {busy === d ? '…' : fmt(d)}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="about">
        <h2>릴레이 카드</h2>
        <p>전날 15:30 코스피 마감에서 밤사이 뉴욕 세션(반도체 SOXX · 나스닥100 QQQ · S&amp;P500 SPY, 공포지수 VIX)을 거쳐 09:00 오늘 코스피 시가까지, 바통이 어떻게 넘어왔는지 시간 순서 그대로 그립니다. 매일 06:45에 밤사이 부분이, 09:06에 시가가 채워집니다.</p>
        <p>빈도 문장은 예측이 아닙니다. 2021년부터 뉴욕이 비슷하게 마감한 밤들을 모아, 그 다음 날 코스피 시가가 어느 쪽으로 열렸는지 세어 보여드릴 뿐입니다. 표본 수(n)를 함께 표시합니다.</p>
        <p className="fine">정보 제공 목적이며 투자 판단 자료가 아닙니다. 특정 종목·매매를 안내하지 않습니다. 변화율은 전일 종가 대비, 뉴욕은 ETF 일별 시가·종가. 상승 빨강·하락 파랑. 데이터 Yahoo Finance.</p>
      </section>
    </main>
  )
}
