import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import Relay from './components/Relay'
import BannerAd from './components/BannerAd'
import { cachedLatest, dateFromPath, fetchDay, fetchIndex, fetchLatest } from './lib/data'
import { haptic, shareRelay } from './lib/ait'
import type { DayRef, RelayDay } from './lib/types'

const TdsButton = lazy(() => import('./components/TdsButton'))

// TDS 청크가 어떤 이유로든 죽어도 앱 전체가 백지가 되지 않게 — 같은 치수의 일반 버튼으로 강등
class Guard extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}

function fmt(d: string) { return `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}` }
function fullDate(d: string) { return `${d.slice(0, 4)}년 ${Number(d.slice(5, 7))}월 ${Number(d.slice(8, 10))}일` }
const direction = { up: '상승', flat: '보합', down: '하락' }

export default function App() {
  const initialDate = useRef(dateFromPath())
  const [latest, setLatest] = useState<RelayDay>(() => cachedLatest())
  const [day, setDay] = useState<RelayDay | null>(null)
  const [dates, setDates] = useState<DayRef[]>([])
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState<string | null>(initialDate.current)
  const [dateError, setDateError] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState(false)
  const [historyBusy, setHistoryBusy] = useState(true)
  const [sharing, setSharing] = useState(false)
  const [shareNote, setShareNote] = useState<string | null>(null)
  const preloaded = useRef(false)
  const dateRequest = useRef(0)
  const shareInFlight = useRef(false)

  useEffect(() => {
    let active = true
    const request = ++dateRequest.current
    fetchLatest().then(data => { if (active) setLatest(data) }).catch(() => { if (active) setStale(true) })
    const want = initialDate.current
    if (want) {
      fetchDay(want).then(data => {
        if (active && request === dateRequest.current) setDay(data)
      }).catch(() => {
        if (active && request === dateRequest.current) setDateError(want)
      }).finally(() => {
        if (active && request === dateRequest.current) setBusy(null)
      })
    }
    // 첫 페인트 뒤에 목록·TDS 청크
    const timer = setTimeout(() => {
      setHistoryBusy(true)
      fetchIndex().then(data => { if (active) setDates(data) }).catch(() => {
        if (active) setHistoryError(true)
      }).finally(() => { if (active) setHistoryBusy(false) })
      if (!preloaded.current) {
        preloaded.current = true
        void import('./components/TdsButton').catch(() => { /* Guard의 일반 버튼 사용 */ })
      }
    }, 1200)
    return () => { active = false; clearTimeout(timer); ++dateRequest.current }
  }, [])

  const shown = day ?? latest
  const shownDate = useRef(shown.date)
  shownDate.current = shown.date
  useEffect(() => { setShareNote(null) }, [shown.date])

  const doShare = async () => {
    if (busy || shareInFlight.current) return
    haptic('tap')
    shareInFlight.current = true
    setSharing(true)
    setShareNote(null)
    const request = dateRequest.current
    try {
      const result = await shareRelay(shown)
      if (request === dateRequest.current && shown.date === shownDate.current) {
        setShareNote(result === 'copied' ? '공유 문구를 복사했어요. 붙여넣어 보내세요.' : result === 'failed' ? '공유가 안 됐어요. 다시 눌러 주세요.' : '공유 화면을 열었어요')
      }
    } finally { shareInFlight.current = false; setSharing(false) }
  }

  const pick = async (date: string) => {
    haptic('tickWeak')
    const request = ++dateRequest.current
    setShareNote(null)
    setDateError(null)
    if (date === latest.date) { setDay(null); setBusy(null); return }
    setBusy(date)
    try {
      const data = await fetchDay(date)
      if (request === dateRequest.current) setDay(data)
    } catch {
      if (request === dateRequest.current) setDateError(date)
    } finally {
      if (request === dateRequest.current) setBusy(null)
    }
  }

  const retryHistory = async () => {
    setHistoryBusy(true)
    setHistoryError(false)
    try { setDates(await fetchIndex()) } catch { setHistoryError(true) } finally { setHistoryBusy(false) }
  }
  const shareDisabled = Boolean(busy) || sharing
  const shareLabel = sharing ? '공유 준비 중' : '공유하기'
  const shareFallback = <button type="button" className="btn-fallback" disabled={shareDisabled} onClick={() => void doShare()}>{shareLabel}</button>

  return (
    <main className="app">
      <div className="view-status">
        <p role="status">{busy ? `${fmt(busy)} 자료를 불러오고 있어요` : day && shown.date !== latest.date ? `${fmt(shown.date)} 지난 자료를 보고 있어요` : '최근 자료를 보고 있어요'}</p>
        {(day || busy || dateError) && <button type="button" className="text-button" onClick={() => void pick(latest.date)}>최근 자료 보기</button>}
      </div>
      {dateError && <div className="date-error">
        <p className="note" role="alert">{fullDate(dateError)} 자료를 불러오지 못했어요. 현재 표시된 자료를 유지했어요.</p>
        <button type="button" className="text-button" onClick={() => void pick(dateError)}>다시 불러오기</button>
      </div>}
      <div aria-busy={Boolean(busy)}><Relay day={shown} /></div>
      {stale && !day && <p className="note" role="status">최신 데이터를 못 받아 마지막으로 본 릴레이를 보여드려요.</p>}

      <div className="actions">
        <Guard fallback={shareFallback}>
          <Suspense fallback={shareFallback}>
            <TdsButton color="dark" display="full" size="xlarge" disabled={shareDisabled} onClick={() => void doShare()}>
              {shareLabel}
            </TdsButton>
          </Suspense>
        </Guard>
        <div className="share-feedback" role="status"><p className="note" key={shareNote}>{shareNote}</p></div>
      </div>

      <section className="past" aria-labelledby="past-title">
        <h2 id="past-title">지난 밤들</h2>
        <div className="history-dates">
        {dates.length > 0 ? <div className="chips">
          {dates.slice(0, 15).map(({ d, z }) => (
            <button type="button" key={d} className={`chip ${d === shown.date ? 'on' : ''} ${z ?? ''}`}
              aria-label={`${fullDate(d)}${z ? `, 시가 ${direction[z]}` : ''}${busy === d ? ', 불러오는 중' : ''}`}
              aria-pressed={d === shown.date} aria-busy={busy === d} onClick={() => void pick(d)} disabled={busy === d}>
              {z && <i className="dot" aria-hidden="true" />}
              {fmt(d)}
            </button>
          ))}
        </div> : historyBusy ? <div className="chips history-placeholder" aria-hidden="true"><span /><span /><span /></div> : null}
        </div>
        <p className="note history-feedback" role="status">{historyBusy ? '지난 날짜를 불러오고 있어요' : historyError ? '지난 날짜 목록을 불러오지 못했어요' : dates.length === 0 ? '아직 지난 자료가 없어요' : null}</p>
        {historyError && <button type="button" className="text-button" disabled={historyBusy} onClick={() => void retryHistory()}>목록 다시 불러오기</button>}
      </section>

      <p className="fine">정보 제공용, 투자 판단 자료 아님</p>

      {/* 고지 아래. 카드→공유 동선은 안 끊고, 고지가 콘텐츠와 광고 사이 완충 */}
      <BannerAd />
    </main>
  )
}
