import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Zap, Clock, CheckCircle, TrendingUp, Activity } from 'lucide-react'
import { api } from '../services/api'
import { formatDistanceToNow } from 'date-fns'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [active, setActive] = useState([])
  const [health, setHealth] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  async function load() {
    try {
      const [s, a, h, m] = await Promise.allSettled([
        api.getStats(), api.getActive(), api.health(), api.metrics()
      ])
      if (s.status === 'fulfilled') setStats(s.value)
      if (a.status === 'fulfilled') setActive(a.value.incidents || [])
      if (h.status === 'fulfilled') setHealth(h.value)
      if (m.status === 'fulfilled') setMetrics(m.value)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const iv = setInterval(load, 10000) // auto-refresh every 10s
    return () => clearInterval(iv)
  }, [])

  function fmtMttr(secs) {
    if (!secs) return '—'
    if (secs < 60) return `${Math.round(secs)}s`
    if (secs < 3600) return `${Math.round(secs / 60)}m`
    return `${(secs / 3600).toFixed(1)}h`
  }

  return (
    <div className="page">
      <div className="page-header flex justify-between items-center">
        <div>
          <h1 className="page-title">Incident Dashboard</h1>
          <p className="page-subtitle">Real-time overview of active incidents and system health</p>
        </div>
        <div className="flex gap-2 items-center">
          {health && (
            <span className={`status-badge ${health.status === 'healthy' ? 'CLOSED' : 'OPEN'}`}>
              {health.status === 'healthy' ? 'All Systems Operational' : 'System Degraded'}
            </span>
          )}
        </div>
      </div>

      {/* Stats Grid */}
      <div className="stats-grid">
        <div className="stat-card p0">
          <div className="stat-label">P0 Active</div>
          <div className={`stat-value ${stats?.p0_active > 0 ? 'critical' : ''}`}>
            {stats?.p0_active ?? '—'}
          </div>
        </div>
        <div className="stat-card p1">
          <div className="stat-label">P1 Active</div>
          <div className={`stat-value ${stats?.p1_active > 0 ? 'warning' : ''}`}>
            {stats?.p1_active ?? '—'}
          </div>
        </div>
        <div className="stat-card blue">
          <div className="stat-label">Investigating</div>
          <div className="stat-value">{stats?.total_investigating ?? '—'}</div>
        </div>
        <div className="stat-card yellow">
          <div className="stat-label">Open</div>
          <div className="stat-value">{stats?.total_open ?? '—'}</div>
        </div>
        <div className="stat-card green">
          <div className="stat-label">Closed Today</div>
          <div className="stat-value">{stats?.total_closed_today ?? '—'}</div>
        </div>
        <div className="stat-card blue">
          <div className="stat-label">Avg MTTR</div>
          <div className="stat-value" style={{fontSize:22}}>{fmtMttr(stats?.avg_mttr_seconds)}</div>
        </div>
        <div className="stat-card blue">
          <div className="stat-label">Signals / hr</div>
          <div className="stat-value" style={{fontSize:22}}>{stats?.signals_last_hour?.toLocaleString() ?? '—'}</div>
        </div>
        <div className="stat-card green">
          <div className="stat-label">Buffer Depth</div>
          <div className="stat-value" style={{fontSize:22}}>{metrics?.queue_depth ?? '—'}</div>
        </div>
      </div>

      {/* Active Incidents */}
      <div className="card">
        <div className="card-title">⚡ Active Incidents</div>
        {loading ? (
          <div className="loading">Loading incidents...</div>
        ) : active.length === 0 ? (
          <div className="empty-state">
            <CheckCircle size={32} style={{marginBottom:8,color:'var(--p3)'}} />
            <div>No active incidents — all clear!</div>
          </div>
        ) : (
          <table className="incident-table">
            <thead>
              <tr>
                <th>Priority</th>
                <th>Component</th>
                <th>Title</th>
                <th>Status</th>
                <th>Signals</th>
                <th>Age</th>
              </tr>
            </thead>
            <tbody>
              {active.map(inc => (
                <tr key={inc.id} onClick={() => navigate(`/incidents/${inc.id}`)}>
                  <td><span className={`badge ${inc.priority}`}>{inc.priority}</span></td>
                  <td><span className="component-id">{inc.component_id}</span></td>
                  <td>{inc.title}</td>
                  <td><span className={`status-badge ${inc.status}`}>{inc.status}</span></td>
                  <td><span className="signal-count">{inc.signal_count || '—'}</span></td>
                  <td style={{color:'var(--text-muted)',fontSize:12}}>
                    {inc.start_time ? formatDistanceToNow(new Date(inc.start_time), { addSuffix: true }) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Health Status */}
      {health && (
        <div className="card mt-4">
          <div className="card-title">Infrastructure Health</div>
          <div className="grid-3">
            {[['PostgreSQL', health.postgres], ['MongoDB', health.mongodb], ['Redis', health.redis]].map(([name, status]) => (
              <div key={name} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'10px 14px',background:'var(--bg-surface)',borderRadius:'var(--radius)',border:'1px solid var(--border)'}}>
                <span style={{fontFamily:'var(--font-mono)',fontSize:12}}>{name}</span>
                <span className={`status-badge ${status === 'ok' ? 'CLOSED' : 'OPEN'}`}>
                  {status === 'ok' ? 'OK' : 'ERROR'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
