import { TDSMobileAITProvider } from '@toss/tds-mobile-ait'
import { Button } from '@toss/tds-mobile'
import type { ComponentProps } from 'react'

// TDS는 모놀리식 ~1MB — 이 파일만 lazy 청크로 떼어 첫 페인트 경로에서 제외 (fx-signal 반려 대응 패턴)
export default function TdsButton(props: ComponentProps<typeof Button>) {
  return (
    <TDSMobileAITProvider>
      <Button {...props} />
    </TDSMobileAITProvider>
  )
}
