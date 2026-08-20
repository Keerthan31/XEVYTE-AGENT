import React, { useState, useRef, useEffect } from 'react'
import { Send, Trash2, LogOut, Bot, PanelLeftOpen, Sparkles, Download, Calendar, Ticket, Bell, User, Clock, Cpu, Sliders, Paperclip, FileText, Image as ImageIcon, X } from 'lucide-react'
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
  confirmAction,
  fetchSessionsDB,
  fetchSessionMessagesDB,
  createSessionDB,
  pinSessionDB,
  renameSessionDB,
  deleteSessionDB,
  fetchAgentBriefing,
  uploadChatFile,
  exchangeToken
} from './api.js'

const WELCOME = {
  role: 'assistant',
  content:
    "Hi! I'm **Xeva**, your Xevyte HRMS assistant.\n\n" +
    'I can help you with leave management, raising grievances, helpdesk tickets, ' +
    'attendance, and profile updates — all through natural conversation.',
}

function getEmployeeDisplayName(empId) {
  const storedName = localStorage.getItem('xeva_standalone_emp_name');
  if (storedName) return storedName;
  if (!empId) return 'Employee'
  
  // Format the ID dynamically if no name is available
  const clean = empId.replace(/\d+$/g, '').replace(/[._-]/g, ' ').trim()
  return clean.charAt(0).toUpperCase() + clean.slice(1)
}

function getGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Morning'
  if (h < 17) return 'Afternoon'
  return 'Evening'
}

export default function App() {
  // Safely read from localStorage and URL
  const getInitialToken = () => {
    try {
      const params = new URLSearchParams(window.location.search);
      const tokenFromURL = params.get('scaloz_token');
      if (tokenFromURL) {
        localStorage.setItem('xeva_standalone_token', tokenFromURL);
        sessionStorage.setItem('token', tokenFromURL);
        
        // Decode JWT to extract details
        try {
          const payload = JSON.parse(atob(tokenFromURL.split('.')[1]));
          const empId = payload.employeeId || payload.sub || payload.loginId || payload.email || 'User';
          if (empId) {
            localStorage.setItem('xeva_standalone_emp', empId);
            sessionStorage.setItem('employeeId', empId);
          }
          if (payload.name || payload.employeeName) {
            localStorage.setItem('xeva_standalone_emp_name', payload.name || payload.employeeName);
          }
        } catch (e) {
          console.error('Failed to parse SSO token', e);
        }
        
        // Clean URL
        params.delete('scaloz_token');
        const newUrl = window.location.pathname + (params.toString() ? `?${params.toString()}` : '');
        window.history.replaceState({}, document.title, newUrl);
        return tokenFromURL;
      }
      
      const stored = localStorage.getItem('xeva_standalone_token') || '';
      // Force clear old dev tokens to log the user out automatically
      if (stored && stored.includes('xeva_dev_token')) {
        localStorage.removeItem('xeva_standalone_token');
        localStorage.removeItem('xeva_standalone_emp');
        localStorage.removeItem('xeva_standalone_emp_name');
        sessionStorage.clear();
        return '';
      }
      return stored;
    } catch { return '' }
  }
  const getInitialEmp = () => {
    try { 
      const token = localStorage.getItem('xeva_standalone_token') || '';
      if (token.includes('xeva_dev_token')) return ''; // ignore dev emp
      return localStorage.getItem('xeva_standalone_emp') || '';
    } catch { return '' }
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

  // ── File attachments (PDF / images) — uploaded ahead of send, then
  // referenced by file_id in the message so the agent can read/attach them ──
  const [pendingAttachment, setPendingAttachment] = useState(null) // { file_id, filename, content_type } | null
  const [attachError, setAttachError] = useState('')
  const [uploadingFile, setUploadingFile] = useState(false)
  const fileInputRef = useRef(null)

  // ── Autonomous session-start briefing: on login, the agent proactively
  // checks pending approvals / unread notifications / today's attendance
  // (read-only tools only — no side effects) and surfaces what needs
  // attention, instead of waiting to be asked. ──
  const [briefing, setBriefing] = useState([])
  const [briefingLoading, setBriefingLoading] = useState(false)

  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  // Fetch sessions from PostgreSQL database on login
  useEffect(() => {
    if (!configured || !employeeId) return

    async function loadDBSessions() {
      await exchangeToken(token)
      const dbSessions = await fetchSessionsDB(employeeId, token)
      if (Array.isArray(dbSessions) && dbSessions.length > 0) {
        const formatted = await Promise.all(dbSessions.map(async s => {
          const rawMsgs = await fetchSessionMessagesDB(s.id, token)
          let parsedMsgs = []
          if (Array.isArray(rawMsgs)) {
            parsedMsgs = rawMsgs.map(m => ({
              role: m.role,
              content: m.content,
              ts: new Date(m.created_at).getTime()
            }))
          }
          
          return {
            ...s,
            isPinned: !!s.is_pinned,
            messages: parsedMsgs.length > 0 ? parsedMsgs : [WELCOME],
            history: parsedMsgs.map(m => ({ role: m.role, content: m.content }))
          }
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
        createSessionDB(defaultId, employeeId, token, 'New Chat', false)
      }
    }

    loadDBSessions()
  }, [configured, employeeId])

  // Fire the proactive briefing once per login (not per chat switch)
  useEffect(() => {
    if (!configured || !employeeId || !token) return
    let cancelled = false
    setBriefingLoading(true)
    fetchAgentBriefing({ token, employeeId })
      .then(items => { if (!cancelled) setBriefing(items) })
      .catch(() => { if (!cancelled) setBriefing([]) })
      .finally(() => { if (!cancelled) setBriefingLoading(false) })
    return () => { cancelled = true }
  }, [configured, employeeId, token])

  // Current session object
  const currentSession = sessions.find(s => s.id === activeSessionId) || sessions[0]
  const messages = currentSession ? currentSession.messages : [WELCOME]
  const history = currentSession ? currentSession.history : []
  const chatStarted = history.length > 0 || messages.length > 1

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const handleLoginSuccess = async ({ token: t, employeeId: e }) => {
    await exchangeToken(t)
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

  useEffect(() => {
    const onUnauthorized = () => {
      handleLogout();
    };
    window.addEventListener('auth:unauthorized', onUnauthorized);
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized);
  }, []);

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
    await createSessionDB(newId, employeeId, token, 'New Chat', false)
  }

  const handlePinSession = async (sessionId) => {
    const target = sessions.find(s => s.id === sessionId)
    const newPinState = !target?.isPinned

    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, isPinned: newPinState } : s))
    await pinSessionDB(sessionId, newPinState, token)
  }

  const handleRenameSession = async (sessionId, newTitle) => {
    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title: newTitle } : s))
    await renameSessionDB(sessionId, newTitle, token)
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
        createSessionDB(newId, employeeId, token, 'New Chat', false)
        return [freshSession]
      }
      if (activeSessionId === sessionId) {
        setActiveSessionId(filtered[0].id)
      }
      return filtered
    })

    await deleteSessionDB(sessionId, token)
  }

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file later
    if (!file) return

    setAttachError('')
    setPendingAttachment({
      filename: file.name,
      content_type: file.type,
      file: file
    })
  }

  const handleSend = async (text) => {
    const msg = (text || input).trim()
    if (!msg && !pendingAttachment) return
    if (!configured) {
      setError('Please log in first.')
      return
    }

    let outgoingMsg = msg || 'Attached file.'
    let attachmentForDisplay = pendingAttachment
    let fileToUpload = null
    if (pendingAttachment) {
      outgoingMsg = `${outgoingMsg}\n\n[Attached file: ${pendingAttachment.filename}]`
      fileToUpload = pendingAttachment.file
    }
    setPendingAttachment(null)
    setAttachError('')

    setInput('')
    setError('')

    const currentId = activeSessionId

    // Update current session title & user message
    setSessions(prev => prev.map(s => {
      if (s.id === currentId) {
        const title = s.title === 'New Chat' ? (msg.length > 28 ? msg.slice(0, 28) + '...' : msg) : s.title
        const displayMsg = attachmentForDisplay ? `${msg}\n\n📎 ${attachmentForDisplay.filename}` : msg
        const updatedMsgs = [...s.messages, { role: 'user', content: displayMsg, ts: Date.now() }]
        return { ...s, title, messages: updatedMsgs }
      }
      return s
    }))

    const lastMsg = currentSession?.messages?.[currentSession.messages.length - 1]
    const pendingToken = lastMsg?.pending_confirmation_token

    setLoadingMap(prev => ({ ...prev, [currentId]: true }))
    setThoughtsMap(prev => ({ ...prev, [currentId]: [{ text: 'Analyzing request...', status: 'loading' }] }))

    // Helper to process response chunking
    const processStreamResponse = async (apiCallPromise) => {
      let fullReply = ''
      let lastUpdateTime = 0
      let pendingUpdate = null
      let newPendingToken = null

      try {
        setSessions(prev => prev.map(s => {
          if (s.id === currentId) {
            return { ...s, messages: [...s.messages, { role: 'assistant', content: '', ts: Date.now() }] }
          }
          return s
        }))

        await apiCallPromise({
          onResponse: (res) => {
            if (res.pending_confirmation_token) newPendingToken = res.pending_confirmation_token
          },
          onChunk: (chunk) => {
            if (chunk.includes('__TOKEN_EXPIRED__')) {
              handleLogout()
              setError('Your session has expired. Please log in again.')
              if (pendingUpdate) clearTimeout(pendingUpdate)
              throw new Error('Session Expired')
            }
            fullReply += chunk

            const now = Date.now()
            if (now - lastUpdateTime < 50) {
              if (pendingUpdate) clearTimeout(pendingUpdate)
              pendingUpdate = setTimeout(() => applyChunkUpdate(fullReply), 50)
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
              newMsgs[newMsgs.length - 1] = { role: 'assistant', content: displayReply, ts: Date.now(), pending_confirmation_token: newPendingToken }
              return { ...s, messages: newMsgs }
            }
            return s
          }))
        }

        setSessions(prev => prev.map(s => {
          if (s.id === currentId) {
            const cleanReply = fullReply.replace(/__TOOL_START:[\s\S]*?__/g, '').replace(/__TOOL_END__/g, '')
            setThoughtsMap(prevStatus => {
              const newMap = { ...prevStatus }
              delete newMap[currentId]
              return newMap
            })
            const newMsgs = [...s.messages]
            newMsgs[newMsgs.length - 1] = { role: 'assistant', content: cleanReply, ts: Date.now(), pending_confirmation_token: newPendingToken }
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
        if (err.message === 'Session Expired') return
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

    const lowerMsg = msg.toLowerCase().trim()
    const isApproval = ['yes', 'y', 'sure', 'ok', 'go ahead', 'approve', 'confirm'].includes(lowerMsg)
    const isDecline = ['no', 'n', 'cancel', 'stop', 'decline'].includes(lowerMsg)

    if (pendingToken && (isApproval || isDecline)) {
      await processStreamResponse(async ({ onResponse, onChunk }) => {
        const res = await confirmAction({
          conversationId: currentId,
          pendingToken,
          approve: isApproval,
          token,
          employeeId,
        })
        if (onResponse) onResponse(res)
        onChunk(res.reply)
      })
    } else {
      await processStreamResponse(async ({ onResponse, onChunk }) => {
        await streamMessage({
          message: outgoingMsg,
          history,
          token,
          employeeId,
          sessionId: currentId,
          file: fileToUpload,
          onResponse,
          onChunk
        })
      })
    }
  }

  const handleConfirmBtn = async (pendingToken, approve) => {
    if (!configured) return
    const currentId = activeSessionId
    setLoadingMap(prev => ({ ...prev, [currentId]: true }))
    setThoughtsMap(prev => ({ ...prev, [currentId]: [{ text: approve ? 'Approving action...' : 'Declining action...', status: 'loading' }] }))

    // Add a fake user message reflecting the button click
    const msg = approve ? 'Approve action' : 'Decline action'
    setSessions(prev => prev.map(s => {
      if (s.id === currentId) {
        return { ...s, messages: [...s.messages, { role: 'user', content: msg, ts: Date.now() }] }
      }
      return s
    }))

    try {
      setSessions(prev => prev.map(s => {
        if (s.id === currentId) {
          return { ...s, messages: [...s.messages, { role: 'assistant', content: '', ts: Date.now() }] }
        }
        return s
      }))

      const res = await confirmAction({ conversationId: currentId, pendingToken, approve, token, employeeId })
      const cleanReply = res.reply
      setThoughtsMap(prevStatus => {
        const newMap = { ...prevStatus }
        delete newMap[currentId]
        return newMap
      })

      setSessions(prev => prev.map(s => {
        if (s.id === currentId) {
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
      const detail = err.response?.data?.detail || err.message || 'Unknown error'
      setSessions(prev => prev.map(s => {
        if (s.id === currentId) {
          return { ...s, messages: [...s.messages.slice(0, -1), { role: 'assistant', content: `Error: ${detail}`, ts: Date.now() }] }
        }
        return s
      }))
    } finally {
      setLoadingMap(prev => ({ ...prev, [currentId]: false }))
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
    <div className="flex h-screen w-screen agent-canvas-bg overflow-hidden font-sans">

      {/* ── SIDEBAR ── */}
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

      {/* ── MAIN CHAT AREA ── */}
      <div className="flex-1 flex flex-col h-full overflow-hidden agent-canvas-bg relative">

        {/* ── TOP HEADER BAR ── */}
        <header className="sticky top-0 z-20 flex-shrink-0 h-16 border-b border-slate-200 bg-white/90 backdrop-blur-md px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {isSidebarCollapsed && (
              <button
                onClick={() => setIsSidebarCollapsed(false)}
                className="p-2 rounded-xl text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition-all cursor-pointer mr-1"
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
              <div className="flex items-center gap-2 text-agent-accent font-bold text-lg">
                <Bot className="w-6 h-6" />
                <span>Xeva</span>
              </div>
            )}
            <span className="text-[10px] font-agent-mono font-bold px-2.5 py-1 rounded-full bg-agent-accent/10 text-agent-accent border border-agent-accent/25 flex items-center gap-1.5">
              <span className="status-dot" /> AUTONOMOUS AGENT
            </span>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2 px-3 py-1 rounded-full border border-white/8 bg-white/[0.03] text-slate-700 text-xs font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-agent-accent" />
              <span>{getEmployeeDisplayName(employeeId)}</span>
            </div>

            <button
              onClick={handleExportThread}
              title="Export Thread (.md)"
              className="p-2 rounded-xl text-slate-600 hover:text-agent-accent hover:bg-slate-100 transition-all cursor-pointer"
            >
              <Download size={16} />
            </button>

            <button
              onClick={handleClear}
              title="Clear Thread Messages"
              className="p-2 rounded-xl text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition-all cursor-pointer"
            >
              <Trash2 size={16} />
            </button>

            <button
              onClick={handleLogout}
              title="Sign Out"
              className="p-2 rounded-xl text-slate-600 hover:text-agent-red hover:bg-agent-red/10 transition-all flex items-center gap-1.5 text-xs font-medium cursor-pointer"
            >
              <LogOut size={16} />
              <span className="hidden sm:inline">Sign Out</span>
            </button>
          </div>
        </header>

        {/* ── WORKSPACE CONTENT WRAPPER (CANVAS + OPERATIONS RAIL) ── */}
        <div className="flex-1 flex overflow-hidden">
          {/* ── MESSAGES CANVAS ── */}
          <main className="flex-1 overflow-y-auto w-full px-6 lg:px-12 py-6">
            <div className="max-w-4xl mx-auto w-full space-y-6">

              {!chatStarted && (
                <div className="space-y-6 my-4">
                  <div className="hero-card p-8 panel rounded-2xl relative overflow-hidden">
                    <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-agent-accent/[0.06] blur-3xl pointer-events-none" />
                    <div className="flex items-start justify-between gap-6 flex-wrap relative">
                      <div>
                        <p className="text-[10px] text-agent-accent font-agent-mono font-bold uppercase tracking-widest mb-3 flex items-center gap-1.5">
                          <Sparkles size={12} /> Enterprise HRMS Agent
                        </p>
                        <h1 className="text-3xl font-bold text-slate-800 mb-3">
                          Good {getGreeting()},{' '}
                          <span className="text-agent-accent">{getEmployeeDisplayName(employeeId)}</span> 👋
                        </h1>

                        {briefingLoading ? (
                          <div className="flex items-center gap-2 text-xs text-slate-500 font-agent-mono">
                            <Cpu size={12} className="spin-slow text-agent-accent" />
                            Checking pending approvals, notifications, attendance…
                          </div>
                        ) : briefing.length > 0 ? (
                          <div className="space-y-1.5 mt-3">
                            {briefing.map((item, i) => (
                              <div key={i} className="flex items-center gap-2 text-sm text-slate-700">
                                <span className={`chip ${item.tier === 'confirm' ? 'chip-confirm' : 'chip-safe'}`}>{item.tag}</span>
                                <span>{item.text}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-slate-600 leading-relaxed max-w-3xl">
                            All clear — no pending approvals or unread alerts. Ask me anything about leave,
                            attendance, grievances, or profile updates and I'll act on it directly.
                          </p>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Enterprise HRMS Capability Grid */}
                  <EnterpriseCapabilityGrid onSelectPrompt={handleSend} />
                </div>
              )}

              {messages.map((m, i) => {
                const isLast = i === messages.length - 1
                return (
                  <React.Fragment key={i}>
                    {/* Main chat bubble */}
                    <MessageBubble 
                      role={m.role} 
                      content={m.content} 
                      ts={m.ts} 
                      onSend={handleSend}
                      pendingToken={m.pending_confirmation_token}
                      isLast={isLast}
                      onConfirmBtn={handleConfirmBtn}
                    />
                  </React.Fragment>
                )
              })}

              <div ref={bottomRef} />
            </div>
          </main>
        </div>

        {/* ── BOTTOM FLOATING INPUT BAR ── */}
        <div className="sticky bottom-0 flex-shrink-0 z-20 border-t border-slate-200 bg-white/90 backdrop-blur-md px-6 py-4">
          <div className="max-w-4xl mx-auto w-full space-y-2">
            {error && <p className="text-xs text-agent-red px-1 font-medium">⚠ {error}</p>}
            {attachError && <p className="text-xs text-agent-red px-1 font-medium">⚠ {attachError}</p>}

            {pendingAttachment && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl panel-inset w-fit">
                {pendingAttachment.content_type === 'application/pdf'
                  ? <FileText size={13} className="text-agent-accent" />
                  : <ImageIcon size={13} className="text-agent-accent" />}
                <span className="text-xs text-slate-700 font-agent-mono max-w-[220px] truncate">{pendingAttachment.filename}</span>
                <button
                  onClick={() => setPendingAttachment(null)}
                  className="text-slate-500 hover:text-agent-red transition-colors"
                  title="Remove attachment"
                >
                  <X size={13} />
                </button>
              </div>
            )}

            <div className="flex items-end gap-3">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"
                onChange={handleFileSelect}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={loading || uploadingFile}
                title="Attach a PDF or image (medical certificate, receipt, ID proof, etc.)"
                className="flex-shrink-0 w-11 h-11 rounded-2xl panel-inset hover:border-agent-accent/40 text-slate-600 hover:text-agent-accent disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center justify-center cursor-pointer"
              >
                {uploadingFile ? <Cpu size={16} className="spin-slow" /> : <Paperclip size={16} />}
              </button>

              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                placeholder="Ask Xeva anything about your HRMS..."
                disabled={loading}
                className="flex-1 px-4 py-3 text-sm command-input resize-none max-h-36 leading-relaxed disabled:opacity-50"
                style={{ height: 'auto' }}
                onInput={e => {
                  e.target.style.height = 'auto'
                  e.target.style.height = Math.min(e.target.scrollHeight, 144) + 'px'
                }}
              />

              {/* Send Button */}
              <button
                onClick={() => handleSend()}
                disabled={loading || (!input.trim() && !pendingAttachment)}
                className="flex-shrink-0 w-11 h-11 btn-accent rounded-2xl disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center justify-center cursor-pointer"
              >
                <Send size={16} />
              </button>
            </div>

            <p className="text-[11px] text-center text-slate-600 pt-1 font-agent-mono">
              Xeva HRMS Agent • Powered by Scaloz AI
            </p>
          </div>
        </div>

      </div>
    </div>
  )
}
