import React, { useState } from 'react'
import {
  Plus,
  MessageSquare,
  Pin,
  PinOff,
  Edit2,
  Trash2,
  MoreVertical,
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  Bot,
  Check,
  X
} from 'lucide-react'

function getEmployeeDisplayName(empId) {
  if (!empId) return 'User'
  if (empId.toLowerCase().includes('koushik')) return 'Koushik Viswanadha'
  if (empId.toLowerCase() === 'scaloz_admin' || empId.toLowerCase() === 'admin') return 'Koushik Viswanadha'
  const clean = empId.replace(/\d+$/g, '').replace(/[._-]/g, ' ').trim()
  return clean.charAt(0).toUpperCase() + clean.slice(1)
}

export default function Sidebar({
  sessions = [],
  activeSessionId,
  onSelectSession,
  onNewChat,
  onPinSession,
  onRenameSession,
  onDeleteSession,
  onLogout,
  employeeId,
  isCollapsed,
  onToggleCollapse
}) {
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const [menuOpenId, setMenuOpenId] = useState(null)

  const handleStartRename = (session, e) => {
    e.stopPropagation()
    setEditingId(session.id)
    setEditTitle(session.title || 'New Chat')
    setMenuOpenId(null)
  }

  const handleSaveRename = (sessionId, e) => {
    e.stopPropagation()
    if (editTitle.trim()) {
      onRenameSession(sessionId, editTitle.trim())
    }
    setEditingId(null)
  }

  const handleCancelRename = (e) => {
    e.stopPropagation()
    setEditingId(null)
  }

  const pinnedSessions = sessions.filter(s => s.isPinned)
  const recentSessions = sessions.filter(s => !s.isPinned)

  if (isCollapsed) {
    return (
      <div className="w-16 h-screen bg-slate-50 border-r border-slate-200 flex flex-col items-center py-4 justify-between z-30 shrink-0 select-none">
        <div className="flex flex-col items-center gap-4 w-full">
          <button
            onClick={onToggleCollapse}
            title="Expand Sidebar"
            className="p-2.5 rounded-xl text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition-all cursor-pointer"
          >
            <PanelLeftOpen size={20} />
          </button>
          
          <button
            onClick={onNewChat}
            title="New Chat"
            className="w-10 h-10 rounded-xl bg-agent-accent/10 border border-agent-accent/30 text-agent-accent hover:bg-agent-accent/20 flex items-center justify-center transition-all cursor-pointer"
          >
            <Plus size={18} />
          </button>
        </div>

        <button
          onClick={onLogout}
          title="Sign Out"
          className="p-2.5 rounded-xl text-slate-600 hover:text-agent-red hover:bg-slate-100 transition-all cursor-pointer"
        >
          <LogOut size={18} />
        </button>
      </div>
    )
  }

  return (
    <aside className="w-64 h-screen bg-slate-50 border-r border-slate-200 text-slate-700 flex flex-col justify-between z-30 shrink-0 select-none font-sans">
      {/* ── TOP HEADER & NEW CHAT ── */}
      <div className="p-3.5 space-y-3">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-agent-accent/10 border border-agent-accent/25 flex items-center justify-center text-agent-accent">
              <Bot size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-800 tracking-tight leading-none">Xeva Agent</h2>
              <span className="text-[10px] text-agent-accent font-agent-mono">HRMS Assistant</span>
            </div>
          </div>

          <button
            onClick={onToggleCollapse}
            title="Close Sidebar"
            className="p-1.5 rounded-lg text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition-all cursor-pointer"
          >
            <PanelLeftClose size={18} />
          </button>
        </div>

        <button
          onClick={onNewChat}
          className="w-full py-2.5 px-3.5 btn-accent text-xs rounded-xl transition-all flex items-center justify-center gap-2 cursor-pointer"
        >
          <Plus size={16} />
          <span>New Chat</span>
        </button>
      </div>

      {/* ── SESSIONS LIST (PINNED & RECENTS) ── */}
      <div className="flex-1 overflow-y-auto px-2.5 py-2 space-y-4 custom-scrollbar">
        {/* Pinned Section */}
        {pinnedSessions.length > 0 && (
          <div>
            <div className="px-2 mb-1.5 flex items-center gap-1.5 text-[10px] font-bold text-slate-600 uppercase tracking-wider">
              <Pin size={11} className="text-agent-accent" />
              <span>Pinned</span>
            </div>
            <div className="space-y-1">
              {pinnedSessions.map(session => renderChatItem(session))}
            </div>
          </div>
        )}

        {/* Recents Section */}
        <div>
          <div className="px-2 mb-1.5 text-[10px] font-bold text-slate-600 uppercase tracking-wider">
            Recents
          </div>
          {recentSessions.length === 0 && pinnedSessions.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-slate-500">
              No conversations yet.
            </div>
          ) : (
            <div className="space-y-1">
              {recentSessions.map(session => renderChatItem(session))}
            </div>
          )}
        </div>
      </div>

      {/* ── USER FOOTER ── */}
      <div className="p-3 border-t border-slate-200 bg-slate-50/60">
        <div className="flex items-center justify-between p-2 rounded-xl bg-white border border-slate-200">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-full bg-agent-accent/15 border border-agent-accent/35 text-agent-accent font-bold text-xs flex items-center justify-center shrink-0">
              {getEmployeeDisplayName(employeeId)[0]}
            </div>
            <span className="text-xs font-semibold text-slate-800 truncate">
              {getEmployeeDisplayName(employeeId)}
            </span>
          </div>

          <button
            onClick={onLogout}
            title="Sign Out"
            className="p-1.5 rounded-lg text-slate-600 hover:text-agent-red hover:bg-slate-100 transition-all cursor-pointer shrink-0"
          >
            <LogOut size={15} />
          </button>
        </div>
      </div>
    </aside>
  )

  function renderChatItem(session) {
    const isActive = session.id === activeSessionId
    const isEditing = editingId === session.id
    const isMenuOpen = menuOpenId === session.id

    return (
      <div
        key={session.id}
        onClick={() => !isEditing && onSelectSession(session.id)}
        className={`group relative flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-all cursor-pointer ${
          isActive
            ? 'bg-white text-slate-800 font-medium shadow-sm border border-agent-accent/20'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-800'
        }`}
      >
        <div className="flex items-center gap-2.5 min-w-0 flex-1 pr-2">
          <MessageSquare size={14} className={`shrink-0 ${isActive ? 'text-agent-accent' : 'text-slate-500'}`} />

          {isEditing ? (
            <div className="flex items-center gap-1 w-full" onClick={e => e.stopPropagation()}>
              <input
                type="text"
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') handleSaveRename(session.id, e)
                  if (e.key === 'Escape') handleCancelRename(e)
                }}
                autoFocus
                className="w-full px-1.5 py-0.5 bg-slate-50 border border-agent-accent rounded text-slate-800 text-xs focus:outline-none"
              />
              <button onClick={e => handleSaveRename(session.id, e)} className="text-agent-accent hover:text-agent-accent/80">
                <Check size={13} />
              </button>
              <button onClick={handleCancelRename} className="text-slate-600 hover:text-slate-700">
                <X size={13} />
              </button>
            </div>
          ) : (
            <span className="truncate">{session.title || 'New Chat'}</span>
          )}
        </div>

        {/* Action Menu (Pin, Rename, Delete) */}
        {!isEditing && (
          <div className="relative shrink-0 flex items-center">
            <button
              onClick={e => {
                e.stopPropagation()
                setMenuOpenId(isMenuOpen ? null : session.id)
              }}
              className={`p-1 rounded-lg text-slate-600 hover:text-slate-800 hover:bg-slate-200 transition-all ${
                isMenuOpen || isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
              }`}
            >
              <MoreVertical size={13} />
            </button>

            {isMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={e => { e.stopPropagation(); setMenuOpenId(null); }} />
                <div className="absolute right-0 top-6 w-32 bg-white border border-slate-300 rounded-xl shadow-xl py-1 z-50 text-[11px] space-y-0.5">
                  <button
                    onClick={e => {
                      e.stopPropagation()
                      onPinSession(session.id)
                      setMenuOpenId(null)
                    }}
                    className="w-full px-3 py-1.5 text-left text-slate-700 hover:bg-slate-100 flex items-center gap-2"
                  >
                    {session.isPinned ? <PinOff size={13} className="text-amber-400" /> : <Pin size={13} />}
                    <span>{session.isPinned ? 'Unpin' : 'Pin'}</span>
                  </button>

                  <button
                    onClick={e => handleStartRename(session, e)}
                    className="w-full px-3 py-1.5 text-left text-slate-700 hover:bg-slate-100 flex items-center gap-2"
                  >
                    <Edit2 size={13} />
                    <span>Rename</span>
                  </button>

                  <button
                    onClick={e => {
                      e.stopPropagation()
                      onDeleteSession(session.id)
                      setMenuOpenId(null)
                    }}
                    className="w-full px-3 py-1.5 text-left text-red-400 hover:bg-red-500/10 flex items-center gap-2"
                  >
                    <Trash2 size={13} />
                    <span>Delete</span>
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    )
  }
}
