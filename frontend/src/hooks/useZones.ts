import { useState, useEffect } from 'react'
import type { ZoneMap } from '../types'
import { fetchZones } from '../api/homepulse'

export function useZones(userId: string) {
  const [zones, setZones]     = useState<ZoneMap>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!userId) return
    fetchZones(userId)
      .then(setZones)
      .catch(() => setZones({}))
      .finally(() => setLoading(false))
  }, [userId])

  return { zones, loading }
}
