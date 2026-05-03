import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import { formatDistanceToNow } from 'date-fns'
import { Search, Filter } from 'lucide-react'

const STATUSES = ['', 'OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED']
const PRIORITIES = ['', 'P0', 'P1', 'P2', 'P3']

export default function WorkItems() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  async function load() {
    setLoading(true)
    try {
      const params = { page, page_size: 25 }
      if (status) params.status = status
      if (priority) params.priority = priority
      const data = await api.listWorkItems(params)
      setItems(data.items)
      setTotal(data.total)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [page, status, priority])

  const totalPages = Math.ceil(total / 25)

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">All Incidents</h1>
        <p className="page-subtitle">{total} total incidents</p>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select className="form-control" style={{width:160}} value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
          <option value="">All Statuses</option>
          {STATUSES.filter(Boolean).map(s => <option key={s}>{s}</option>)}
        </select>
        <select className="form-control" style={{width:140}} value={priority} onChange={e => { setPriority(e.target.value); setPage(1) }}>
          <option value="">All Priorities</option>
          {PRIORITIES.filter(Boolean).map(p => <option key={p}>{p}</option>)}
        </select>
        <button className="btn btn-ghost" onClick={load}>Refresh</button>
      </div>

      <div className="card">
        {loading ? (
          <div className="loading">Loading incidents...</div>
        ) : items.length === 0 ? (
          <div className="empty-state">No incidents found</div>
        ) : (
          <table className="incident-table">
            <thead>
              <tr>
                <th>Priority</th>
                <th>Component</th>
                <th>Title</th>
                <th>Type</th>
                <th>Status</th>
                <th>Signals</th>
                <th>RCA</th>
                <th>Age</th>
              </tr>
            </thead>
            <tbody>
              {items.map(wi => (
                <tr key={wi.id} onClick={() => navigate(`/incidents/${wi.id}`)}>
                  <td><span className={`badge ${wi.priority}`}>{wi.priority}</span></td>
                  <td><span className="component-id">{wi.component_id}</span></td>
                  <td style={{maxWidth:280, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{wi.title}</td>
                  <td><span style={{fontFamily:'var(--font-mono)',fontSize:11,color:'var(--text-secondary)'}}>{wi.component_type}</span></td>
                  <td><span className={`status-badge ${wi.status}`}>{wi.status}</span></td>
                  <td><span className="signal-count">{wi.signal_count}</span></td>
                  <td>
                    {wi.has_rca
                      ? <span style={{color:'var(--p3)',fontSize:12}}>✓</span>
                      : <span style={{color:'var(--text-muted)',fontSize:12}}>—</span>
                    }
                  </td>
                  <td style={{color:'var(--text-muted)',fontSize:12,whiteSpace:'nowrap'}}>
                    {formatDistanceToNow(new Date(wi.created_at), { addSuffix: true })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex gap-2 items-center mt-4" style={{justifyContent:'center'}}>
            <button className="btn btn-ghost" onClick={() => setPage(p => Math.max(1, p-1))} disabled={page === 1}>Previous</button>
            <span style={{color:'var(--text-secondary)',fontSize:13}}>{page} / {totalPages}</span>
            <button className="btn btn-ghost" onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page === totalPages}>Next</button>
          </div>
        )}
      </div>
    </div>
  )
}
