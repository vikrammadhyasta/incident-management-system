import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import { format, formatDistanceToNow } from 'date-fns'
import { ArrowLeft, FileText, Activity, User, Clock } from 'lucide-react'

const RCA_CATEGORIES = [
  'Infrastructure Failure', 'Software Bug', 'Configuration Error',
  'Capacity Issue', 'Network Issue', 'Human Error', 'Third Party', 'Unknown'
]

const VALID_TRANSITIONS = {
  OPEN: ['INVESTIGATING'],
  INVESTIGATING: ['RESOLVED', 'OPEN'],
  RESOLVED: ['CLOSED', 'INVESTIGATING'],
  CLOSED: [],
}

function RCAModal({ workItemId, onClose, onSuccess }) {
  const [form, setForm] = useState({
    incident_start: '',
    incident_end: '',
    root_cause_category: 'Infrastructure Failure',
    root_cause_detail: '',
    fix_applied: '',
    prevention_steps: '',
    impact_summary: '',
    created_by: 'engineer',
  })
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  function update(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function submit() {
    setError('')
    setSubmitting(true)
    try {
      await api.createRCA(workItemId, form)
      onSuccess()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <h2 className="modal-title">📋 Submit Root Cause Analysis</h2>
        {error && <div className="error-msg">{error}</div>}

        <div className="grid-2">
          <div className="form-group">
            <label className="form-label">Incident Start *</label>
            <input type="datetime-local" className="form-control" value={form.incident_start}
              onChange={e => update('incident_start', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Incident End *</label>
            <input type="datetime-local" className="form-control" value={form.incident_end}
              onChange={e => update('incident_end', e.target.value)} />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">Root Cause Category *</label>
          <select className="form-control" value={form.root_cause_category}
            onChange={e => update('root_cause_category', e.target.value)}>
            {RCA_CATEGORIES.map(c => <option key={c}>{c}</option>)}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">Root Cause Detail * (min 10 chars)</label>
          <textarea className="form-control" rows={3} value={form.root_cause_detail}
            onChange={e => update('root_cause_detail', e.target.value)}
            placeholder="Describe the root cause in detail..." />
        </div>

        <div className="form-group">
          <label className="form-label">Fix Applied * (min 10 chars)</label>
          <textarea className="form-control" rows={3} value={form.fix_applied}
            onChange={e => update('fix_applied', e.target.value)}
            placeholder="What was done to fix the incident?" />
        </div>

        <div className="form-group">
          <label className="form-label">Prevention Steps * (min 10 chars)</label>
          <textarea className="form-control" rows={3} value={form.prevention_steps}
            onChange={e => update('prevention_steps', e.target.value)}
            placeholder="How will we prevent this from happening again?" />
        </div>

        <div className="form-group">
          <label className="form-label">Impact Summary (optional)</label>
          <textarea className="form-control" rows={2} value={form.impact_summary}
            onChange={e => update('impact_summary', e.target.value)}
            placeholder="Services affected, user impact, data loss..." />
        </div>

        <div className="form-group">
          <label className="form-label">Submitted By</label>
          <input type="text" className="form-control" value={form.created_by}
            onChange={e => update('created_by', e.target.value)} />
        </div>

        <div className="flex gap-3" style={{justifyContent:'flex-end'}}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={submitting}>
            {submitting ? 'Submitting...' : 'Submit RCA'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function IncidentDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [wi, setWi] = useState(null)
  const [signals, setSignals] = useState([])
  const [timeline, setTimeline] = useState([])
  const [rca, setRca] = useState(null)
  const [showRcaModal, setShowRcaModal] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [tab, setTab] = useState('signals')

  async function load() {
    try {
      const [w, s, t] = await Promise.allSettled([
        api.getWorkItem(id),
        api.getSignals(id, { limit: 50 }),
        api.getTimeline(id),
      ])
      if (w.status === 'fulfilled') setWi(w.value)
      if (s.status === 'fulfilled') setSignals(s.value.signals || [])
      if (t.status === 'fulfilled') setTimeline(t.value || [])

      // Load RCA if exists
      try {
        const r = await api.getRCA(id)
        setRca(r)
      } catch {}
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [id])

  async function doTransition(newStatus) {
    setError(''); setSuccess('')
    try {
      const updated = await api.transition(id, newStatus)
      setWi(updated)
      setSuccess(`Status updated to ${newStatus}`)
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  if (loading) return <div className="loading">Loading incident...</div>
  if (!wi) return <div className="page"><div className="error-msg">Incident not found</div></div>

  const transitions = VALID_TRANSITIONS[wi.status] || []

  return (
    <div className="page">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button className="btn btn-ghost" onClick={() => navigate(-1)}>
          <ArrowLeft size={14} /> Back
        </button>
        <span className={`badge ${wi.priority}`}>{wi.priority}</span>
        <span className={`status-badge ${wi.status}`}>{wi.status}</span>
      </div>

      <div className="page-header">
        <h1 className="page-title" style={{fontSize:20}}>{wi.title}</h1>
        <p className="page-subtitle" style={{fontFamily:'var(--font-mono)',fontSize:12}}>
          {wi.component_id} · {wi.component_type} · {wi.signal_count} signals
        </p>
      </div>

      {error && <div className="error-msg">{error}</div>}
      {success && <div className="success-msg">{success}</div>}

      {/* Meta + Actions */}
      <div className="grid-2 mb-4">
        <div className="card">
          <div className="card-title">Incident Info</div>
          <div style={{display:'flex',flexDirection:'column',gap:10}}>
            {[
              ['Component', wi.component_id],
              ['Type', wi.component_type],
              ['Started', format(new Date(wi.start_time), 'MMM dd, yyyy HH:mm')],
              ['Age', formatDistanceToNow(new Date(wi.start_time), { addSuffix: true })],
              ['Assignee', wi.assignee || 'Unassigned'],
              ['MTTR', wi.mttr_seconds ? `${Math.round(wi.mttr_seconds / 60)}m` : '—'],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between" style={{fontSize:13}}>
                <span style={{color:'var(--text-muted)',fontFamily:'var(--font-mono)',fontSize:11}}>{k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-title">Actions</div>
          <div style={{display:'flex',flexDirection:'column',gap:10}}>
            {transitions.map(s => (
              <button key={s} className={`btn ${s === 'CLOSED' ? 'btn-danger' : 'btn-primary'}`}
                onClick={() => doTransition(s)}>
                Move to {s}
                {s === 'CLOSED' && !rca && <span style={{fontSize:11,opacity:0.7}}> (needs RCA)</span>}
              </button>
            ))}
            {!rca && wi.status !== 'CLOSED' && (
              <button className="btn btn-ghost" onClick={() => setShowRcaModal(true)}>
                <FileText size={14} /> Add RCA
              </button>
            )}
            {transitions.length === 0 && (
              <p style={{color:'var(--text-muted)',fontSize:13}}>Incident is CLOSED — no further transitions available.</p>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-4">
        {['signals', 'timeline', 'rca'].map(t => (
          <button key={t} className={`btn ${tab === t ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setTab(t)} style={{textTransform:'capitalize'}}>
            {t === 'rca' ? '📋 RCA' : t === 'signals' ? '📡 Signals' : '🕐 Timeline'}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === 'signals' && (
        <div className="card">
          <div className="card-title">Raw Signals ({signals.length})</div>
          {signals.length === 0
            ? <div className="empty-state">No signals linked yet</div>
            : signals.map(s => (
              <div key={s._id} className="signal-item">
                <div className="signal-ts">{s.timestamp ? format(new Date(s.timestamp), 'MMM dd HH:mm:ss.SSS') : '—'}</div>
                <div className="signal-msg">[{s.severity}] {s.message}</div>
                <div className="signal-meta">{s.component_id} · {s.error_code || 'no-code'} · {s.source_host || 'unknown-host'}</div>
              </div>
            ))
          }
        </div>
      )}

      {tab === 'timeline' && (
        <div className="card">
          <div className="card-title">Status Timeline</div>
          {timeline.length === 0
            ? <div className="empty-state">No transitions yet</div>
            : <div className="timeline">
              {timeline.map((t, i) => (
                <div key={i} className="timeline-item">
                  <div className="timeline-time">{format(new Date(t.timestamp), 'MMM dd, HH:mm:ss')}</div>
                  <div className="timeline-content">
                    <strong>{t.from_status || 'Created'}</strong>
                    {t.from_status && <> → <strong>{t.to_status}</strong></>}
                    {' '}<span>by {t.transitioned_by}</span>
                    {t.notes && <div style={{marginTop:4,color:'var(--text-muted)',fontSize:12}}>{t.notes}</div>}
                  </div>
                </div>
              ))}
            </div>
          }
        </div>
      )}

      {tab === 'rca' && (
        <div className="card">
          <div className="card-title">Root Cause Analysis</div>
          {!rca ? (
            <div style={{textAlign:'center',padding:'32px'}}>
              <p style={{color:'var(--text-muted)',marginBottom:16}}>No RCA submitted yet.</p>
              <button className="btn btn-primary" onClick={() => setShowRcaModal(true)}>
                <FileText size={14} /> Submit RCA
              </button>
            </div>
          ) : (
            <div style={{display:'flex',flexDirection:'column',gap:18}}>
              <div className="grid-2">
                <div>
                  <div className="form-label">Incident Start</div>
                  <div>{format(new Date(rca.incident_start), 'MMM dd, yyyy HH:mm')}</div>
                </div>
                <div>
                  <div className="form-label">Incident End</div>
                  <div>{format(new Date(rca.incident_end), 'MMM dd, yyyy HH:mm')}</div>
                </div>
              </div>
              <div>
                <div className="form-label">Root Cause Category</div>
                <span className="badge P1" style={{background:'rgba(59,130,246,0.1)',color:'var(--accent)',borderColor:'rgba(59,130,246,0.3)'}}>
                  {rca.root_cause_category}
                </span>
              </div>
              {[
                ['Root Cause Detail', rca.root_cause_detail],
                ['Fix Applied', rca.fix_applied],
                ['Prevention Steps', rca.prevention_steps],
                rca.impact_summary && ['Impact Summary', rca.impact_summary],
              ].filter(Boolean).map(([k, v]) => (
                <div key={k}>
                  <div className="form-label">{k}</div>
                  <p style={{color:'var(--text-secondary)',fontSize:13,lineHeight:1.7}}>{v}</p>
                </div>
              ))}
              <div style={{fontSize:11,color:'var(--text-muted)',fontFamily:'var(--font-mono)'}}>
                Submitted by {rca.created_by} · {format(new Date(rca.created_at), 'MMM dd, yyyy HH:mm')}
              </div>
            </div>
          )}
        </div>
      )}

      {showRcaModal && (
        <RCAModal
          workItemId={id}
          onClose={() => setShowRcaModal(false)}
          onSuccess={() => { setShowRcaModal(false); setSuccess('RCA submitted successfully!'); load() }}
        />
      )}
    </div>
  )
}
