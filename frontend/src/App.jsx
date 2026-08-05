import React, { useState, useRef, useEffect } from 'react'
import { Send, Trash2, LogOut, Bot, PanelLeftOpen, Sparkles, Download, Calendar, Ticket, Bell, User, Clock, Cpu, Sliders } from 'lucide-react'
import logoUrl from '../assests/image.png'
import MessageBubble from './components/MessageBubble.jsx'
import TypingIndicator from './components/TypingIndicator.jsx'
import Login from './components/Login.jsx'
import Sidebar from './components/Sidebar.jsx'
import ThoughtProcess from './components/ThoughtProcess.jsx'
import AgentInspector from './components/AgentInspector.jsx'
import EnterpriseCapabilityGrid from './components/EnterpriseCapabilityGrid.jsx'
import { getThoughtText } from './utils/formatters.js'
import { 
  streamMessage, 
  fetchSessionsDB, 
  createSessionDB, 
  pinSessionDB, 
  renameSessionDB, 
  deleteSessionDB 
} from './api.js'

const WELCOME = {
  role: 'assistant',
  content:
    "Hi! I'm **Xeva**, your Xevyte HRMS assistant.\n\n" +
    'I can help you with leave management, raising grievances, helpdesk tickets, ' +
    'attendance, and more — all through natural conversation.',
}

const ACTION_TILES = [
  { icon: Calendar, label: 'Leave Balance', prompt: 'Show me my current leave balance', color: 'text-teal-600 bg-teal-50' },
  { icon: Calendar, label: 'Apply Leave', prompt: 'I want to apply for leave', color: 'text-cyan-600 bg-cyan-50' },
  { icon: Ticket, label: 'Raise IT Ticket', prompt: 'I want to raise an IT helpdesk ticket', color: 'text-blue-600 bg-blue-50' },
  { icon: User, label: 'My Profile', prompt: 'Show me my employee profile', color: 'text-indigo-600 bg-indigo-50' },
  { icon: Bell, label: 'Notifications', prompt: 'Do I have any new notifications?', color: 'text-amber-600 bg-amber-50' },
]

function getGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Morning'
  if (h < 17) return 'Afternoon'
  return 'Evening'
}

export default function App() {
  // Safely read from localStorage
  const getInitialToken = () => {
    try { return localStorage.getItem('xeva_standalone_token') || '' } catch { return '' }
  }
  const getInitialEmp = () => {
    try { return localStorage.getItem('xeva_standalone_emp') || '' } catch { return '' }
  }

  const [token, setToken] = useState(getInitialToken)
  const [employeeId, setEmployeeId] = useState(getInitialEmp)
  const [configured, setConfigured] = useState(() => Boolean(getInitialEmp()))
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isInspectorOpen, setIsInspectorOpen] = useState(true)

  // Sessions management
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState('')

  const [input, setInput] = useState('')
  const [loadingMap, setLoadingMap] = useState({})
  const [thoughtsMap, setThoughtsMap] = useState({})
  const loading = loadingMap[activeSessionId] || false
  const [error, setError] = useState('')
  const [imgError, setImgError] = useState(false)

  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  // Fetch sessions from PostgreSQL database on login
  useEffect(() => {
    if (!configured || !employeeId) return

    async function loadDBSessions() {
      const dbSessions = await fetchSessionsDB(employeeId)
      if (Array.isArray(dbSessions) && dbSessions.length > 0) {
        // Ensure welcome message is prepended if empty
        const formatted = dbSessions.map(s => ({
          ...s,
          messages: s.messages && s.messages.length > 0 ? s.messages : [WELCOME]
        }))
        setSessions(formatted)
        setActiveSessionId(formatted[0].id)
      } else {
        // Create initial default session in DB
        const defaultId = Date.now().toString()
        const initialSess = {
          id: defaultId,
          title: 'New Chat',
          messages: [WELCOME],
          history: [],
          isPinned: false,
          createdAt: Date.now()
        }
        setSessions([initialSess])
        setActiveSessionId(defaultId)
        createSessionDB(defaultId, employeeId, 'New Chat', false)
      }
    }

    loadDBSessions()
  }, [configured, employeeId])

  // Current session object
  const currentSession = sessions.find(s => s.id === activeSessionId) || sessions[0]
  const messages = currentSession ? currentSession.messages : [WELCOME]
  const history = currentSession ? currentSession.history : []
  const chatStarted = history.length > 0 || messages.length > 1

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const handleLoginSuccess = ({ token: t, employeeId: e }) => {
    setToken(t)
    setEmployeeId(e)
    setConfigured(true)
    setError('')
    try {
      localStorage.setItem('xeva_standalone_token', t)
      localStorage.setItem('xeva_standalone_emp', e)
    } catch (err) {
      console.warn('LocalStorage save failed:', err)
    }
  }

  const handleLogout = () => {
    setToken('')
    setEmployeeId('')
    setConfigured(false)
    try {
      localStorage.removeItem('xeva_standalone_token')
      localStorage.removeItem('xeva_standalone_emp')
    } catch (err) {
      console.warn('LocalStorage clear failed:', err)
    }
  }

  // Export Thread Handler
  const handleExportThread = () => {
    if (!messages || messages.length === 0) return
    const formatted = messages
      .map(m => `**${m.role === 'user' ? 'User' : 'Xeva Agent'}**: ${m.content}`)
      .join('\n\n---\n\n')
    const blob = new Blob([formatted], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `xeva-chat-export-${activeSessionId}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  // Session handlers (database synced)
  const handleNewChat = async () => {
    const newId = Date.now().toString()
    const newSession = {
      id: newId,
      title: 'New Chat',
      messages: [WELCOME],
      history: [],
      isPinned: false,
      createdAt: Date.now()
    }
    setSessions(prev => [newSession, ...prev])
    setActiveSessionId(newId)
    setError('')

    // Save to PostgreSQL DB
    await createSessionDB(newId, employeeId, 'New Chat', false)
  }

  const handlePinSession = async (sessionId) => {
    const target = sessions.find(s => s.id === sessionId)
    const newPinState = !target?.isPinned

    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, isPinned: newPinState } : s))
    await pinSessionDB(sessionId, newPinState)
  }

  const handleRenameSession = async (sessionId, newTitle) => {
    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title: newTitle } : s))
    await renameSessionDB(sessionId, newTitle)
  }

  const handleDeleteSession = async (sessionId) => {
    setSessions(prev => {
      const filtered = prev.filter(s => s.id !== sessionId)
      if (filtered.length === 0) {
        const newId = Date.now().toString()
        const freshSession = {
          id: newId,
          title: 'New Chat',
          messages: [WELCOME],
          history: [],
          isPinned: false,
          createdAt: Date.now()
        }
        setActiveSessionId(newId)
        createSessionDB(newId, employeeId, 'New Chat', false)
        return [freshSession]
      }
      if (activeSessionId === sessionId) {
        setActiveSessionId(filtered[0].id)
      }
      return filtered
    })

    await deleteSessionDB(sessionId)
  }

  const handleSend = async (text) => {
    const msg = (text || input).trim()
    if (!msg) return
    if (!configured) {
      setError('Please log in first.')
      return
    }

    setInput('')
    setError('')

    const currentId = activeSessionId

    // Update current session title & user message
    setSessions(prev => prev.map(s => {
      if (s.id === currentId) {
        const title = s.title === 'New Chat' ? (msg.length > 28 ? msg.slice(0, 28) + '...' : msg) : s.title
        const updatedMsgs = [...s.messages, { role: 'user', content: msg, ts: Date.now() }]
        return { ...s, title, messages: updatedMsgs }
      }
      return s
    }))

    setLoadingMap(prev => ({ ...prev, [currentId]: true }))
    setThoughtsMap(prev => ({ ...prev, [currentId]: [{ text: 'Analyzing request...', status: 'loading' }] }))

    try {
      // Append initial assistant placeholder
      setSessions(prev => prev.map(s => {
        if (s.id === currentId) {
          return { ...s, messages: [...s.messages, { role: 'assistant', content: '', ts: Date.now() }] }
        }
        return s
      }))

      let fullReply = ''
      let lastUpdateTime = 0
      let pendingUpdate = null

      await streamMessage({
        message: msg,
        history,
        token,
        employeeId,
        sessionId: currentId,
        onChunk: (chunk) => {
          if (chunk.includes('__TOKEN_EXPIRED__')) {
            handleLogout()
            setError('Your session has expired. Please log in again.')
            if (pendingUpdate) clearTimeout(pendingUpdate)
            throw new Error('Session Expired')
          }
          fullReply += chunk
          
          // Throttle updates to at most once every 50ms to prevent massive React re-render lag
          const now = Date.now()
          if (now - lastUpdateTime < 50) {
             if (pendingUpdate) clearTimeout(pendingUpdate)
             pendingUpdate = setTimeout(() => {
                applyChunkUpdate(fullReply)
             }, 50)
             return
          }
          
          lastUpdateTime = now
          applyChunkUpdate(fullReply)
        }
      })
      
      if (pendingUpdate) clearTimeout(pendingUpdate)

      function applyChunkUpdate(currentReply) {
          setLoadingMap(prev => ({ ...prev, [currentId]: false }))
          
          let displayReply = currentReply
          
          const startMatches = [...currentReply.matchAll(/__TOOL_START:([\s\S]*?)__/g)]
          const endMatches = [...currentReply.matchAll(/__TOOL_END__/g)]
          
          let thoughts = [{ text: 'Analyzing request...', status: startMatches.length > 0 ? 'done' : 'loading' }]
          for (let i = 0; i < startMatches.length; i++) {
            const toolName = startMatches[i][1] || 'tool'
            const isDone = i < endMatches.length
            thoughts.push({
              text: getThoughtText(toolName),
              status: isDone ? 'done' : 'loading'
            })
          }
          
          displayReply = displayReply.replace(/__TOOL_START:[\s\S]*?__/g, '').replace(/__TOOL_END__/g, '')
          
          setThoughtsMap(prev => ({ ...prev, [currentId]: thoughts }))

          setSessions(prev => prev.map(s => {
            if (s.id === currentId) {
              const newMsgs = [...s.messages]
              newMsgs[newMsgs.length - 1] = { role: 'assistant', content: displayReply, ts: Date.now() }
              return { ...s, messages: newMsgs }
            }
            return s
          }))
      }

      // Update history and messages in current session
      setSessions(prev => prev.map(s => {
        if (s.id === currentId) {
          const cleanReply = fullReply.replace(/__TOOL_START:[\s\S]*?__/g, '').replace(/__TOOL_END__/g, '')
          
          // Hide the thoughts when the final response is complete
          setThoughtsMap(prevStatus => {
            const newMap = { ...prevStatus }
            delete newMap[currentId]
            return newMap
          })
          
          const newMsgs = [...s.messages]
          newMsgs[newMsgs.length - 1] = { role: 'assistant', content: cleanReply, ts: Date.now() }
          
          return {
            ...s,
            messages: newMsgs,
            history: [
              ...s.history,
              { role: 'user', content: msg },
              { role: 'assistant', content: cleanReply }
            ]
          }
        }
        return s
      }))
    } catch (err) {
      if (err.message === 'Session Expired') {
        // We already handled logout and set error in onChunk
        return
      }
      const detail = err.response?.data?.detail || err.message || 'Unknown error'
      setSessions(prev => prev.map(s => {
        if (s.id === currentId) {
          return {
            ...s,
            messages: [...s.messages.slice(0, -1), { role: 'assistant', content: `Error: ${detail}`, ts: Date.now() }]
          }
        }
        return s
      }))
    } finally {
      setLoadingMap(prev => ({ ...prev, [currentId]: false }))
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleClear = () => {
    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        return { ...s, messages: [WELCOME], history: [] }
      }
      return s
    }))
    setError('')
  }

  // Render Login component if not logged in
  if (!configured) {
    return <Login onLoginSuccess={handleLoginSuccess} />
  }

  return (
    <div className="flex h-screen w-screen bg-slate-50 overflow-hidden font-sans">
      
      {/* ── CHATGPT-STYLE SIDEBAR ── */}
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={(id) => { setActiveSessionId(id); setError(''); }}
        onNewChat={handleNewChat}
        onPinSession={handlePinSession}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
        onLogout={handleLogout}
        employeeId={employeeId}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
      />

      {/* ── MAIN CHAT AREA (WIDE FULL-SCREEN CANVAS) ── */}
      <div className="flex-1 flex flex-col h-full overflow-hidden bg-slate-50 relative">

        {/* ── TOP HEADER BAR ── */}
        <header className="sticky top-0 z-20 flex-shrink-0 h-16 border-b border-slate-200/80 bg-white/90 backdrop-blur-md px-6 flex items-center justify-between shadow-sm">
          <div className="flex items-center gap-3">
            {isSidebarCollapsed && (
              <button
                onClick={() => setIsSidebarCollapsed(false)}
                className="p-2 rounded-xl text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-all cursor-pointer mr-1"
                title="Expand Sidebar"
              >
                <PanelLeftOpen size={18} />
              </button>
            )}

            {!imgError ? (
              <img
                src={logoUrl}
                alt="Scaloz AI"
                className="h-8 w-auto object-contain"
                onError={() => setImgError(true)}
              />
            ) : (
              <div className="flex items-center gap-2 text-teal-600 font-bold text-lg">
                <Bot className="w-6 h-6" />
                <span>Xeva</span>
              </div>
            )}
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-teal-50 text-teal-700 border border-teal-200">
              Xeva Agent
            </span>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2 px-3 py-1 rounded-full border border-teal-500/20 bg-teal-500/10 text-teal-800 text-xs font-semibold">
              <span className="w-2 h-2 rounded-full bg-teal-500 animate-pulse" />
              <span>{employeeId}</span>
            </div>

            <button
              onClick={() => setIsInspectorOpen(!isInspectorOpen)}
              title="Toggle Agent Operations & Telemetry"
              className={`p-2 rounded-xl flex items-center gap-1.5 text-xs font-bold transition-all cursor-pointer border ${
                isInspectorOpen 
                  ? 'bg-teal-500/10 text-teal-700 border-teal-500/30 shadow-xs' 
                  : 'text-slate-500 border-slate-200 hover:bg-slate-100'
              }`}
            >
              <Cpu size={15} />
              <span className="hidden md:inline">Operations</span>
            </button>

            <button
              onClick={handleExportThread}
              title="Export Thread (.md)"
              className="p-2 rounded-xl text-slate-400 hover:text-teal-600 hover:bg-teal-50 transition-all cursor-pointer"
            >
              <Download size={16} />
            </button>

            <button
              onClick={handleClear}
              title="Clear Thread Messages"
              className="p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all cursor-pointer"
            >
              <Trash2 size={16} />
            </button>

            <button
              onClick={handleLogout}
              title="Sign Out"
              className="p-2 rounded-xl text-slate-400 hover:text-red-500 hover:bg-red-50 transition-all flex items-center gap-1.5 text-xs font-medium cursor-pointer"
            >
              <LogOut size={16} />
              <span className="hidden sm:inline">Sign Out</span>
            </button>
          </div>
        </header>

        {/* ── WORKSPACE CONTENT WRAPPER (CANVAS + OPERATIONS INSPECTOR) ── */}
        <div className="flex-1 flex overflow-hidden">
          {/* ── MESSAGES CANVAS (WIDE FULL-WIDTH DISPLAY) ── */}
          <main className="flex-1 overflow-y-auto w-full px-6 lg:px-12 py-6">
          <div className="max-w-full mx-auto w-full space-y-6">

            {!chatStarted && (
              <div className="space-y-6 my-4">
                <div className="hero-card p-8 bg-gradient-to-br from-white to-slate-50 border border-slate-200/80 rounded-2xl shadow-sm">
                  <div className="flex items-start justify-between gap-6 flex-wrap">
                    <div>
                      <p className="text-xs text-teal-600 font-semibold uppercase tracking-widest mb-2 flex items-center gap-1.5">
                        <Sparkles size={14} /> HRMS AI Assistant
                      </p>
                      <h1 className="text-3xl font-bold text-slate-900 mb-3">
                        Good {getGreeting()},{' '}
                        <span className="text-teal-600">{employeeId}</span> 👋
                      </h1>
                      <p className="text-sm text-slate-600 leading-relaxed max-w-3xl">
                        Ask me anything about your leave balance, attendance, grievances, or HR policies.
                        I can perform tasks directly on your behalf.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Enterprise HRMS Capability Grid */}
                <EnterpriseCapabilityGrid onSelectPrompt={handleSend} />
              </div>
            )}

            {/* Render Chat Messages */}
            {messages.map((m, i) => (
              <React.Fragment key={i}>
                {/* If this is the active loading message, render the thoughts above it */}
                {i === messages.length - 1 && thoughtsMap[activeSessionId] && thoughtsMap[activeSessionId].length > 0 && (
                  <ThoughtProcess thoughts={thoughtsMap[activeSessionId]} />
                )}
                
                <MessageBubble role={m.role} content={m.content} ts={m.ts} onSend={handleSend} />
              </React.Fragment>
            ))}

            <div ref={bottomRef} />
          </div>
        </main>

        {/* Right-side Agent Operations Panel */}
        <AgentInspector 
          isOpen={isInspectorOpen} 
          onClose={() => setIsInspectorOpen(false)} 
          thoughts={thoughtsMap[activeSessionId]} 
        />
      </div>

        {/* ── BOTTOM FLOATING INPUT BAR (MIC REMOVED) ── */}
        <div className="sticky bottom-0 flex-shrink-0 z-20 border-t border-slate-200/80 bg-white/90 backdrop-blur-md px-6 py-4">
          <div className="max-w-full mx-auto w-full space-y-2">
            {error && <p className="text-xs text-red-500 px-1 font-medium">⚠ {error}</p>}
            
            <div className="flex items-end gap-3">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                placeholder="Ask Xeva anything about your HRMS..."
                disabled={loading}
                className="flex-1 px-4 py-3 text-sm text-slate-800 placeholder-slate-400 bg-slate-100/90 border border-slate-300 rounded-2xl resize-none max-h-36 leading-relaxed focus:outline-none focus:ring-2 focus:ring-teal-500 focus:bg-white transition-all disabled:opacity-50 shadow-inner"
                style={{ height: 'auto' }}
                onInput={e => {
                  e.target.style.height = 'auto'
                  e.target.style.height = Math.min(e.target.scrollHeight, 144) + 'px'
                }}
              />

              {/* Send Button */}
              <button
                onClick={() => handleSend()}
                disabled={loading || !input.trim()}
                className="flex-shrink-0 w-11 h-11 bg-gradient-to-r from-teal-500 to-cyan-500 hover:from-teal-600 hover:to-cyan-600 text-white rounded-2xl shadow-lg shadow-teal-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center justify-center cursor-pointer"
              >
                <Send size={16} />
              </button>
            </div>
            
            <p className="text-[11px] text-center text-slate-400 pt-1">
              Xeva HRMS Assistant • Powered by Scaloz AI
            </p>
          </div>
        </div>

      </div>
    </div>
  )
}
