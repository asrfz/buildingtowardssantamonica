import { useState, useEffect, useCallback } from 'react'
import type { HomePulseEvent } from '../types'
import { fetchEvents } from '../api/homepulse'

const POLL_INTERVAL_MS = 5000

export function useEvents(userId: string) {
  const [events, setEvents]   = useState<HomePulseEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!userId) return
    try {
      const data = await fetchEvents(userId)
      setEvents(data)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [refresh])

  return { events, loading, error, refresh }
}
