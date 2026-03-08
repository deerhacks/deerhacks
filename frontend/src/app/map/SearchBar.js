'use client'

import { useState, useEffect } from 'react'

const MONO = "'Barlow Condensed', 'Arial Narrow', sans-serif"
const BODY = "'Inter', -apple-system, 'Segoe UI', sans-serif"

const MAX_HISTORY = 5
const HISTORY_KEY = 'locatr_search_history'

const SEARCHBAR_STYLES = `
  .locatr-search-input::placeholder {
    font-family: 'Barlow Condensed', 'Arial Narrow', sans-serif;
    font-weight: 300;
    letter-spacing: 0.04em;
    color: rgba(255,255,255,0.30);
  }
  .locatr-search-input:focus { outline: none; }
  .locatr-search-form:focus-within {
    outline: 2px solid rgba(255,255,255,0.20);
    outline-offset: 2px;
  }
  @keyframes history-reveal {
    from { opacity: 0; transform: translateY(-4px); }
    to   { opacity: 1; transform: translateY(0); }
  }
`

function SearchIcon({ size = 13, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 13 13" fill="none" style={{ flexShrink: 0 }} aria-hidden="true">
      <circle cx="5.5" cy="5.5" r="4" stroke={color} strokeWidth="1.15" />
      <line x1="8.8" y1="8.8" x2="12.2" y2="12.2" stroke={color} strokeWidth="1.15" strokeLinecap="round" />
    </svg>
  )
}

function getHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  } catch {
    return []
  }
}

function saveHistory(query) {
  try {
    const prev = getHistory().filter(q => q !== query)
    const next = [query, ...prev].slice(0, MAX_HISTORY)
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  } catch {}
}

export default function SearchBar({
  onSearch = () => {},
  placeholder = "search 'open recreation basketball court in downtown toronto for 5 people'",
  disabled = false,
}) {
  const [query, setQuery] = useState('')
  const [focused, setFocused] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory] = useState([])

  useEffect(() => {
    setHistory(getHistory())
  }, [])

  const handleSubmit = (e) => {
    e?.preventDefault()
    if (disabled) return
    const trimmed = query.trim()
    if (trimmed) {
      saveHistory(trimmed)
      setHistory(getHistory())
      setShowHistory(false)
      onSearch(trimmed)
    }
  }

  const handleFocus = () => {
    setFocused(true)
    setHistory(getHistory())
    setShowHistory(true)
  }

  const handleBlur = () => {
    setFocused(false)
    // Delay hiding so click events on history items register
    setTimeout(() => setShowHistory(false), 150)
  }

  const handleHistoryClick = (q) => {
    setQuery(q)
    setShowHistory(false)
    if (!disabled) {
      saveHistory(q)
      onSearch(q)
    }
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: SEARCHBAR_STYLES }} />
      <div style={{ position: 'relative' }}>
        <form
          onSubmit={handleSubmit}
          className="ui-reveal locatr-search-form"
          role="search"
          aria-label="Search for venues"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            background: focused ? 'rgba(20, 17, 13, 0.84)' : 'rgba(20, 17, 13, 0.70)',
            backdropFilter: 'blur(20px)',
            WebkitBackdropFilter: 'blur(20px)',
            borderRadius: 10,
            height: 42,
            boxSizing: 'border-box',
            padding: '0 16px',
            width: 580,
            maxWidth: 'calc(100vw - 48px)',
            border: `1px solid ${focused ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.05)'}`,
            boxShadow: focused
              ? '0 8px 40px rgba(0,0,0,0.32), 0 1px 0 rgba(255,255,255,0.04) inset'
              : '0 2px 16px rgba(0,0,0,0.22)',
            transition: 'background 0.22s cubic-bezier(0.16,1,0.3,1), border 0.22s cubic-bezier(0.16,1,0.3,1), box-shadow 0.22s cubic-bezier(0.16,1,0.3,1)',
            opacity: disabled ? 0.5 : 1,
            pointerEvents: disabled ? 'none' : 'auto',
          }}
        >
          <SearchIcon
            size={13}
            color={focused ? 'rgba(255,255,255,0.52)' : 'rgba(255,255,255,0.28)'}
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={handleFocus}
            onBlur={handleBlur}
            placeholder={placeholder}
            aria-label="Search query"
            className="locatr-search-input"
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              outline: 'none',
              padding: 0,
              fontFamily: MONO,
              fontWeight: 300,
              fontSize: 16,
              letterSpacing: '0.04em',
              color: 'rgba(255,255,255,0.88)',
              caretColor: 'rgba(255,255,255,0.65)',
              minWidth: 0,
            }}
          />
        </form>

        {/* Search history dropdown */}
        {showHistory && history.length > 0 && !disabled && (
          <div style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            left: 0,
            right: 0,
            background: 'rgba(14, 12, 10, 0.94)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(255,255,255,0.07)',
            borderRadius: 8,
            boxShadow: '0 8px 32px rgba(0,0,0,0.40)',
            zIndex: 100,
            overflow: 'hidden',
            animation: 'history-reveal 0.15s ease forwards',
          }}>
            <div style={{
              padding: '6px 12px 4px',
              fontFamily: MONO,
              fontSize: 10,
              letterSpacing: '0.20em',
              color: 'rgba(255,255,255,0.20)',
              textTransform: 'uppercase',
            }}>
              Recent
            </div>
            {history.map((q, i) => (
              <div
                key={i}
                onMouseDown={() => handleHistoryClick(q)}
                style={{
                  padding: '8px 12px',
                  fontFamily: BODY,
                  fontSize: 13,
                  color: 'rgba(255,255,255,0.55)',
                  cursor: 'pointer',
                  transition: 'background 0.1s ease',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              >
                {q}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
