'use client'

import { useEffect, useState } from 'react'
import { useUser } from '@auth0/nextjs-auth0/client'

const MONO = "'Barlow Condensed', 'Arial Narrow', sans-serif"
const BODY = "'Inter', -apple-system, 'Segoe UI', sans-serif"
const API = (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000').replace('ws://', 'http://').replace('wss://', 'https://')

const PREFS_META = [
  {
    key: 'budget_sensitive',
    label: 'Budget-Sensitive',
    description: 'Boosts Cost Analyst weight — favours cheaper venues',
    color: '#60a8e0',
  },
  {
    key: 'vibe_first',
    label: 'Vibe First',
    description: 'Boosts Vibe Matcher weight — prioritises aesthetics & atmosphere',
    color: '#b06ee0',
  },
  {
    key: 'risk_averse',
    label: 'Risk-Averse',
    description: 'Boosts Critic weight — flags crowding, weather, and closures',
    color: '#60e0c8',
  },
]

function Toggle({ checked, onChange, color }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      style={{
        width: 36, height: 20,
        borderRadius: 10,
        border: 'none',
        background: checked ? color : 'rgba(255,255,255,0.10)',
        position: 'relative',
        cursor: 'pointer',
        transition: 'background 0.2s ease',
        flexShrink: 0,
      }}
    >
      <div style={{
        position: 'absolute',
        top: 3, left: checked ? 18 : 3,
        width: 14, height: 14,
        borderRadius: '50%',
        background: 'white',
        transition: 'left 0.2s ease',
        boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
      }} />
    </button>
  )
}

export default function PreferencesPanel({ onClose }) {
  const { user } = useUser()
  const [prefs, setPrefs] = useState({ budget_sensitive: false, vibe_first: false, risk_averse: false })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!user?.sub) return
    fetch(`${API}/api/user/preferences?auth_user_id=${encodeURIComponent(user.sub)}`)
      .then(r => r.json())
      .then(data => {
        if (data.preferences) setPrefs(p => ({ ...p, ...data.preferences }))
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [user?.sub])

  const toggle = async (key, val) => {
    const next = { ...prefs, [key]: val }
    setPrefs(next)
    setSaving(true)
    setSaved(false)
    try {
      await fetch(`${API}/api/user/preferences`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auth_user_id: user.sub, preferences: next }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {}
    setSaving(false)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 200,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(0,0,0,0.55)',
      backdropFilter: 'blur(4px)',
    }}>
      <div style={{
        background: '#1a1814',
        border: '1px solid rgba(255,255,255,0.09)',
        borderRadius: 14,
        padding: '28px 28px 24px',
        width: 360,
        maxWidth: '90vw',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontFamily: MONO, fontSize: 20, letterSpacing: '0.22em', color: 'rgba(255,255,255,0.88)', textTransform: 'uppercase' }}>
            Personalization
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'rgba(255,255,255,0.35)', fontSize: 18, lineHeight: 1 }}
          >
            ×
          </button>
        </div>

        {/* Sub-header */}
        <p style={{ fontFamily: BODY, fontSize: 12, color: 'rgba(255,255,255,0.35)', margin: '0 0 20px', lineHeight: 1.5 }}>
          Stored in your Auth0 profile. Affects agent weights on every search.
        </p>

        {user && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20, padding: '8px 12px', background: 'rgba(255,255,255,0.04)', borderRadius: 8 }}>
            {user.picture && <img src={user.picture} alt="" style={{ width: 24, height: 24, borderRadius: '50%', objectFit: 'cover' }} />}
            <span style={{ fontFamily: BODY, fontSize: 12, color: 'rgba(255,255,255,0.50)' }}>{user.email}</span>
          </div>
        )}

        {/* Divider */}
        <div style={{ height: 1, background: 'rgba(255,255,255,0.06)', marginBottom: 16 }} />

        {/* Toggles */}
        {loading ? (
          <div style={{ fontFamily: BODY, fontSize: 18, color: 'rgba(255,255,255,0.30)', textAlign: 'center', padding: '12px 0' }}>
            Loading...
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {PREFS_META.map(({ key, label, description, color }) => (
              <div key={key} style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: MONO, fontSize: 16, letterSpacing: '0.10em', color: prefs[key] ? color : 'rgba(255,255,255,0.65)', marginBottom: 2 }}>
                    {label}
                  </div>
                  <div style={{ fontFamily: BODY, fontSize: 13, color: 'rgba(255,255,255,0.30)', lineHeight: 1.45 }}>
                    {description}
                  </div>
                </div>
                <Toggle checked={!!prefs[key]} onChange={(v) => toggle(key, v)} color={color} />
              </div>
            ))}
          </div>
        )}

        {/* Save status */}
        <div style={{
          marginTop: 20,
          fontFamily: BODY,
          fontSize: 11,
          color: saved ? '#6ee06e' : 'rgba(255,255,255,0)',
          textAlign: 'center',
          transition: 'color 0.3s ease',
          height: 16,
        }}>
          {saved ? '✓ Saved to Auth0' : saving ? 'Saving...' : ''}
        </div>
      </div>
    </div>
  )
}
