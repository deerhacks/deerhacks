'use client'

import { useState, useRef, useEffect } from 'react'

const MONO = "'Barlow Condensed', 'Arial Narrow', sans-serif"
const BODY = "'Inter', -apple-system, 'Segoe UI', sans-serif"

const VIBES = [
  "aesthetic", "cozy", "chill", "trendy", "hipster",
  "romantic", "classy", "upscale", "fancy", "elegant", "modern",
  "rustic", "bohemian", "artsy", "quirky", "retro", "vintage",
  "minimalist", "industrial", "dark academia", "cottagecore",
  "cyberpunk", "neon", "instagrammable", "photogenic", "cute",
  "charming", "intimate", "lively", "energetic", "fun", "exciting",
  "relaxing", "peaceful", "calm", "serene", "warm", "inviting",
  "atmosphere", "ambiance", "mood", "theme", "decor", "design",
  "beautiful", "pretty", "gorgeous", "stunning",
]

function FilterIcon({ size = 14, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0 }}>
      <line x1="1.5" y1="4"   x2="12.5" y2="4"   stroke={color} strokeWidth="1.15" strokeLinecap="round" />
      <line x1="3.5" y1="7"   x2="10.5" y2="7"   stroke={color} strokeWidth="1.15" strokeLinecap="round" />
      <line x1="5.5" y1="10"  x2="8.5"  y2="10"  stroke={color} strokeWidth="1.15" strokeLinecap="round" />
    </svg>
  )
}

export default function VibeFilter({ onVibeSelect, selectedVibe }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleSelect = (index, name) => {
    setOpen(false)
    onVibeSelect?.(index, name)
  }

  const handleClear = (e) => {
    e.stopPropagation()
    setOpen(false)
    onVibeSelect?.(null, null)
  }

  const isActive = selectedVibe !== null

  return (
    <div ref={rootRef} style={{ position: 'relative', flexShrink: 0 }}>

      {/* Square button — matches search bar height (~40px) */}
      <div
        onClick={() => setOpen(v => !v)}
        title={isActive ? `Vibe: ${selectedVibe.name}` : 'Filter by vibe'}
        style={{
          width: 42,
          height: 42,
          borderRadius: 10,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: isActive
            ? 'rgba(140, 80, 255, 0.30)'
            : open
              ? 'rgba(20, 17, 13, 0.84)'
              : 'rgba(20, 17, 13, 0.70)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          border: isActive
            ? '1px solid rgba(180, 120, 255, 0.45)'
            : `1px solid ${open ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.05)'}`,
          cursor: 'pointer',
          transition: 'background 0.18s ease, border 0.18s ease, box-shadow 0.18s ease',
          boxShadow: isActive
            ? '0 0 12px 2px rgba(140,80,255,0.18)'
            : open
              ? '0 8px 40px rgba(0,0,0,0.32)'
              : '0 2px 16px rgba(0,0,0,0.22)',
          position: 'relative',
        }}
      >
        <FilterIcon
          size={14}
          color={isActive ? 'rgba(200, 160, 255, 0.95)' : 'rgba(255,255,255,0.45)'}
        />

        {/* Active dot indicator */}
        {isActive && (
          <span style={{
            position: 'absolute',
            top: 7,
            right: 7,
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: 'rgba(200, 160, 255, 0.95)',
            boxShadow: '0 0 4px rgba(200,160,255,0.8)',
          }} />
        )}
      </div>

      {/* Dropdown — right-aligned to button */}
      {open && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 6px)',
          right: 0,
          width: 336,
          maxHeight: 300,
          overflowY: 'auto',
          background: 'rgba(14, 12, 10, 0.94)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 10,
          boxShadow: '0 10px 40px rgba(0,0,0,0.55)',
          zIndex: 100,
          padding: '6px',
          animation: 'locatr-reveal 0.18s cubic-bezier(0.16,1,0.3,1) forwards',
          scrollbarWidth: 'thin',
          scrollbarColor: 'rgba(255,255,255,0.08) transparent',
          boxSizing: 'border-box',
        }}>

          {/* Header */}
          <div style={{
            padding: '2px 6px 6px',
            fontFamily: MONO,
            fontSize: 12,
            letterSpacing: '0.22em',
            color: 'rgba(255,255,255,0.25)',
            textTransform: 'uppercase',
            borderBottom: '1px solid rgba(255,255,255,0.05)',
            marginBottom: 4,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}>
            <span>Filter by vibe</span>
            {isActive && (
              <span
                onClick={handleClear}
                style={{
                  fontFamily: BODY,
                  fontSize: 10,
                  color: 'rgba(200,160,255,0.65)',
                  cursor: 'pointer',
                  letterSpacing: '0.06em',
                  textTransform: 'none',
                }}
                onMouseEnter={e => e.currentTarget.style.color = 'rgba(200,160,255,1)'}
                onMouseLeave={e => e.currentTarget.style.color = 'rgba(200,160,255,0.65)'}
              >
                clear
              </span>
            )}
          </div>

          {/* 3-column grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr' }}>
            {VIBES.map((vibe, i) => {
              const isSelected = selectedVibe?.index === i
              return (
                <div
                  key={i}
                  onClick={() => handleSelect(i, vibe)}
                  style={{
                    padding: '6px 8px',
                    fontFamily: BODY,
                    fontSize: 12,
                    color: isSelected ? 'rgba(210,170,255,1)' : 'rgba(255,255,255,0.60)',
                    background: isSelected ? 'rgba(160,100,255,0.16)' : 'transparent',
                    cursor: 'pointer',
                    textTransform: 'capitalize',
                    borderRadius: 6,
                    transition: 'background 0.10s ease, color 0.10s ease',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                  onMouseEnter={e => {
                    if (!isSelected) {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                      e.currentTarget.style.color = 'rgba(255,255,255,0.88)'
                    }
                  }}
                  onMouseLeave={e => {
                    if (!isSelected) {
                      e.currentTarget.style.background = 'transparent'
                      e.currentTarget.style.color = 'rgba(255,255,255,0.60)'
                    }
                  }}
                >
                  {vibe}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
