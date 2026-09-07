import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import Relay from './components/Relay'
import BannerAd from './components/BannerAd'
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

      <p className="fine">정보 제공용, 투자 판단 자료 아님</p>

      {/* 고지 아래. 카드→공유 동선은 안 끊고, 고지가 콘텐츠와 광고 사이 완충 */}
      <BannerAd />
    </main>
  )
}
