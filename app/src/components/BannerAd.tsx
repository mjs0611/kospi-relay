import { useEffect, useRef, useState } from 'react'
import { TossAds } from '@apps-in-toss/web-framework'

// 맨 아래 배너 하나. 검수 규칙상 인트로·로딩·팝업엔 넣지 않음(fx-signal 선례).
// 구좌 ID는 앱인토스 콘솔에서 발급 → .env 의 VITE_BANNER_AD_GROUP_ID. 없으면 테스트 배너.
// SDK 3.x는 토스 웹뷰 밖에서 동기 throw → 전부 try/catch (lib/ait.ts와 같은 규칙).
const AD_GROUP_ID = import.meta.env.VITE_BANNER_AD_GROUP_ID || 'ait-ad-test-banner-id'

export default function BannerAd() {
  const ref = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)
  const [hidden, setHidden] = useState(false)   // 노필·렌더 실패 시 빈 칸을 남기지 않는다

  useEffect(() => {
    let cancelled = false
    try {
      if (!TossAds?.initialize?.isSupported?.()) return
      TossAds.initialize({ callbacks: { onInitialized: () => { if (!cancelled) setReady(true) } } })
    } catch { /* 브라우저·구버전 토스앱 → 광고 없이 정상 */ }
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!ready || !ref.current) return
    let attached: { destroy?: () => void } | undefined
    try {
      attached = TossAds.attachBanner(AD_GROUP_ID, ref.current, {
        theme: 'dark',
        callbacks: { onNoFill: () => setHidden(true), onAdFailedToRender: () => setHidden(true) },
      })
    } catch { /* noop */ }
    return () => attached?.destroy?.()
  }, [ready])

  return hidden ? null : <div ref={ref} className="ad-banner" />
}
