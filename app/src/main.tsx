import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

// TDS provider는 ~1MB를 끌어오므로 루트에서 감싸지 않는다. TDS 버튼만 lazy 청크(components/TdsButton)에서 자체 provider.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
