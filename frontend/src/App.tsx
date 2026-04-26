import { useEffect, useState } from 'react'
import DevConsole from './DevConsole'
import HomePulseDashboard from './pages/HomePulseDashboard'

function isDevHash(): boolean {
  return typeof window !== 'undefined' && window.location.hash.replace(/^#/, '') === 'dev'
}

export default function App() {
  const [dev, setDev] = useState(isDevHash)

  useEffect(() => {
    const onHash = () => setDev(isDevHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return dev ? <DevConsole /> : <HomePulseDashboard />
}
