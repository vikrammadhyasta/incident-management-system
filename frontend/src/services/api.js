const BASE = '/api/v1'

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export const api = {
  // Dashboard
  getStats: () => req('/dashboard/stats'),
  getActive: () => req('/dashboard/active'),

  // Work Items
  listWorkItems: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return req(`/work-items${q ? '?' + q : ''}`)
  },
  getWorkItem: (id) => req(`/work-items/${id}`),
  getSignals: (id, params = {}) => {
    const q = new URLSearchParams(params).toString()
    return req(`/work-items/${id}/signals${q ? '?' + q : ''}`)
  },
  transition: (id, new_status, notes, transitioned_by = 'user') =>
    req(`/work-items/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ new_status, notes, transitioned_by }),
    }),
  assign: (id, assignee) =>
    req(`/work-items/${id}/assign`, {
      method: 'POST',
      body: JSON.stringify({ assignee }),
    }),
  getTimeline: (id) => req(`/work-items/${id}/timeline`),

  // RCA
  createRCA: (id, data) =>
    req(`/work-items/${id}/rca`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getRCA: (id) => req(`/work-items/${id}/rca`),

  // Signals ingestion (for demo/testing)
  ingestSignal: (signal) =>
    req('/signals/ingest/single', { method: 'POST', body: JSON.stringify(signal) }),

  // Health
  health: () => fetch('/health').then(r => r.json()),
  metrics: () => req('/signals/metrics'),
}
