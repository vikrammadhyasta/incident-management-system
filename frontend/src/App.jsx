import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { Activity, AlertTriangle, LayoutDashboard, Radio, Zap } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import WorkItems from './pages/WorkItems'
import IncidentDetail from './pages/IncidentDetail'
import IngestDemo from './pages/IngestDemo'
import './styles.css'

function Sidebar() {
  const location = useLocation()
  const links = [
    { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/incidents', icon: AlertTriangle, label: 'Incidents' },
    { to: '/ingest', icon: Radio, label: 'Signal Injector' },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <Zap size={22} className="logo-icon" />
        <span className="logo-text">IMS</span>
        <span className="logo-sub">SRE Console</span>
      </div>
      <nav className="sidebar-nav">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
            <Icon size={16} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">
        <Activity size={12} className="pulse-dot" />
        <span>System Operational</span>
      </div>
    </aside>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/incidents" element={<WorkItems />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
            <Route path="/ingest" element={<IngestDemo />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
