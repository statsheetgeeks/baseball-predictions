import { useState, useEffect } from 'react'

/**
 * usePredictions
 *
 * Fetches a prediction JSON file from /data/<filename>.json
 * The JSON file is written by your Python models and committed to the repo.
 *
 * Expected JSON shape:
 * {
 *   "updated": "2025-04-20T10:00:00Z",   ← ISO timestamp
 *   "predictions": [ ...rows... ]          ← array of prediction objects
 * }
 *
 * Returns: { data, updated, loading, error }
 */
export function usePredictions(filename) {
  const [data,    setData]    = useState([])
  const [updated, setUpdated] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    if (!filename) return
    setLoading(true)
    setError(null)

    fetch(`/data/${filename}.json`)
      .then(res => {
        if (!res.ok) throw new Error(`Could not load ${filename}.json (${res.status})`)
        return res.json()
      })
      .then(json => {
        setData(json.predictions ?? [])
        setUpdated(json.updated ?? null)
      })
      .catch(err => {
        setError(`${err.message}. Make sure your Python model has run and committed this file.`)
      })
      .finally(() => setLoading(false))
  }, [filename])

  return { data, updated, loading, error }
}
