import { useState } from 'react'
import { api } from '../services/api'
import { Zap, Play, RefreshCw } from 'lucide-react'

const COMPONENT_TYPES = ['RDBMS', 'NOSQL', 'CACHE', 'ASYNC_QUEUE', 'API', 'MCP_HOST', 'UNKNOWN']
const SEVERITIES = ['ERROR', 'CRITICAL', 'WARN']

const PRESETS = [
  {
    label: '🔴 RDBMS Outage (P0)',
    signal: {
      component_id: 'POSTGRES_PRIMARY_01',
      component_type: 'RDBMS',
      error_code: 'PG_CONN_REFUSED',
      message: 'Connection refused: Primary PostgreSQL node unreachable after 3 retries',
      severity: 'CRITICAL',
      latency_ms: null,
      source_host: 'db-host-01',
    }
  },
  {
    label: '🟠 MCP Host Failure (P0)',
    signal: {
      component_id: 'MCP_HOST_CLUSTER_02',
      component_type: 'MCP_HOST',
      error_code: 'MCP_TIMEOUT',
      message: 'MCP Host unresponsive — service mesh health check failed',
      severity: 'CRITICAL',
      source_host: 'mcp-node-02',
    }
  },
  {
    label: '🟡 Cache Degraded (P2)',
    signal: {
      component_id: 'CACHE_CLUSTER_01',
      component_type: 'CACHE',
      error_code: 'CACHE_MISS_SPIKE',
      message: 'Cache miss rate at 87% — possible eviction storm',
      severity: 'ERROR',
      latency_ms: 450,
      source_host: 'redis-node-01',
    }
  },
  {
    label: '🟠 Queue Consumer Lag (P1)',
    signal: {
      component_id: 'EVENT_QUEUE_PAYMENTS',
      component_type: 'ASYNC_QUEUE',
      error_code: 'CONSUMER_LAG_CRITICAL',
      message: 'Consumer lag at 48,220 messages — processing delay 3m12s',
      severity: 'ERROR',
      source_host: 'kafka-broker-03',
    }
  },
  {
    label: '🟠 API 5xx Spike (P1)',
    signal: {
      component_id: 'API_GATEWAY_PROD',
      component_type: 'API',
      error_code: 'HTTP_500',
      message: 'HTTP 500 error rate: 12.4% (threshold: 1%)',
      severity: 'ERROR',
      latency_ms: 8200,
      source_host: 'api-gw-01',
    }
  },
]

export default function IngestDemo() {
  const [form, setForm] = useState({
    component_id: 'CACHE_CLUSTER_01',
    component_type: 'CACHE',
    error_code: 'CACHE_MISS',
    message: 'High cache miss rate detected',
    severity: 'ERROR',
    latency_ms: '',
    source_host: '',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [burstCount, setBurstCount] = useState(100)
  const [burstRunning, setBurstRunning] = useState(false)
  const [burstResult, setBurstResult] = useState(null)

  function update(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function sendSignal() {
    setError(''); setResult(null); setSubmitting(true)
    try {
      const payload = { ...form }
      if (payload.latency_ms) payload.latency_ms = parseFloat(payload.latency_ms)
      else delete payload.latency_ms
      if (!payload.source_host) delete payload.source_host
      const r = await api.ingestSignal(payload)
      setResult(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  function loadPreset(preset) {
    setForm({ ...form, ...preset.signal, latency_ms: preset.signal.latency_ms || '' })
    setResult(null); setError('')
  }

  async function runBurst() {
    setBurstRunning(true); setBurstResult(null)
    const component_id = form.component_id
    let queued = 0, dropped = 0, errors = 0
    const batchSize = 50
    const batches = Math.ceil(burstCount / batchSize)
    try {
      for (let b = 0; b < batches; b++) {
        const n = Math.min(batchSize, burstCount - b * batchSize)
        const signals = Array.from({ length: n }, (_, i) => ({
          component_id,
          component_type: form.component_type,
          message: `Burst signal ${b * batchSize + i + 1} of ${burstCount}`,
          severity: form.severity,
          error_code: form.error_code || 'BURST_TEST',
        }))
        try {
          const r = await fetch('/api/v1/signals/ingest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signals }),
          })
          const d = await r.json()
          queued += d.queued || 0
          dropped += d.dropped || 0
        } catch { errors++ }
      }
      setBurstResult({ total: burstCount, queued, dropped, errors })
    } finally {
      setBurstRunning(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Signal Injector</h1>
        <p className="page-subtitle">Simulate infrastructure failures for testing</p>
      </div>

      {/* Presets */}
      <div className="card mb-4">
        <div className="card-title">Quick Presets</div>
        <div className="flex gap-2" style={{flexWrap:'wrap'}}>
          {PRESETS.map((p, i) => (
            <button key={i} className="btn btn-ghost" style={{fontSize:12}} onClick={() => loadPreset(p)}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid-2">
        {/* Signal Form */}
        <div className="card">
          <div className="card-title">Custom Signal</div>
          {error && <div className="error-msg">{error}</div>}
          {result && <div className="success-msg">✓ Queued {result.queued} signal(s). {result.dropped > 0 && `Dropped: ${result.dropped}`}</div>}

          <div className="form-group">
            <label className="form-label">Component ID</label>
            <input type="text" className="form-control" value={form.component_id}
              onChange={e => update('component_id', e.target.value)} />
          </div>

          <div className="grid-2">
            <div className="form-group">
              <label className="form-label">Component Type</label>
              <select className="form-control" value={form.component_type}
                onChange={e => update('component_type', e.target.value)}>
                {COMPONENT_TYPES.map(t => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Severity</label>
              <select className="form-control" value={form.severity}
                onChange={e => update('severity', e.target.value)}>
                {SEVERITIES.map(s => <option key={s}>{s}</option>)}
              </select>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Error Code</label>
            <input type="text" className="form-control" value={form.error_code}
              onChange={e => update('error_code', e.target.value)} placeholder="e.g. PG_CONN_REFUSED" />
          </div>

          <div className="form-group">
            <label className="form-label">Message</label>
            <textarea className="form-control" rows={3} value={form.message}
              onChange={e => update('message', e.target.value)} />
          </div>

          <div className="grid-2">
            <div className="form-group">
              <label className="form-label">Latency (ms)</label>
              <input type="number" className="form-control" value={form.latency_ms}
                onChange={e => update('latency_ms', e.target.value)} placeholder="optional" />
            </div>
            <div className="form-group">
              <label className="form-label">Source Host</label>
              <input type="text" className="form-control" value={form.source_host}
                onChange={e => update('source_host', e.target.value)} placeholder="optional" />
            </div>
          </div>

          <button className="btn btn-primary" onClick={sendSignal} disabled={submitting} style={{width:'100%'}}>
            <Zap size={14} /> {submitting ? 'Sending...' : 'Send Signal'}
          </button>
        </div>

        {/* Burst Test */}
        <div className="card">
          <div className="card-title">Burst / Debounce Test</div>
          <p style={{color:'var(--text-secondary)',fontSize:13,marginBottom:16}}>
            Send {burstCount} signals for the same Component ID within seconds.
            The debounce engine should create exactly <strong style={{color:'var(--accent)'}}>1 Work Item</strong> and link all signals to it.
          </p>
          <div className="form-group">
            <label className="form-label">Signal Count</label>
            <input type="number" className="form-control" value={burstCount}
              onChange={e => setBurstCount(parseInt(e.target.value) || 100)}
              min={1} max={5000} />
          </div>
          <p style={{fontSize:12,color:'var(--text-muted)',marginBottom:16,fontFamily:'var(--font-mono)'}}>
            Using component: {form.component_id}
          </p>
          <button className="btn btn-primary" onClick={runBurst} disabled={burstRunning} style={{width:'100%',marginBottom:12}}>
            <Play size={14} /> {burstRunning ? `Sending burst...` : `Send ${burstCount} Signals`}
          </button>

          {burstResult && (
            <div className="success-msg">
              <div style={{fontFamily:'var(--font-mono)',fontSize:12}}>
                <div>Total: {burstResult.total}</div>
                <div>Queued: {burstResult.queued}</div>
                <div>Dropped: {burstResult.dropped}</div>
                <div style={{marginTop:8,color:'var(--p3)'}}>
                  ✓ Check the Incidents page — should show 1 Work Item for {form.component_id}
                </div>
              </div>
            </div>
          )}

          <div className="card" style={{marginTop:16,background:'var(--bg-surface)'}}>
            <div className="card-title">How Debouncing Works</div>
            <div style={{fontSize:12,color:'var(--text-secondary)',lineHeight:1.8,fontFamily:'var(--font-mono)'}}>
              <div>• Window: 10 seconds per component</div>
              <div>• All signals → MongoDB (Data Lake)</div>
              <div>• Only 1 WorkItem → PostgreSQL</div>
              <div>• Signal count updated every 10 signals</div>
              <div>• New window starts after 10s expiry</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
