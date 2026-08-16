import axios from 'axios'

axios.defaults.withCredentials = true;

// Same-origin when UI is served from the agent (:8443); absolute URL for Vite dev (:3000).
const BASE = import.meta.env.VITE_API_BASE || (
  typeof window !== 'undefined' && window.location.port === '3000'
    ? 'http://localhost:8443/api/agent'
    : '/api/agent'
)

export async function exchangeToken(token) {
  try {
    const res = await axios.post(`${BASE}/auth/token`, { token })
    return res.data  // { employee_id, employee_name, role, tenant_name, expires_at }
  } catch (e) {
    console.warn('Failed to exchange token with backend:', e)
    return null
  }
}

export async function sendMessage({ message, history, token, employeeId, sessionId }) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  // Backend ChatRequest only accepts message + conversation_id (auth via cookie/Bearer).
  // Extra fields were previously sent and silently ignored / could confuse proxies.
  const res = await axios.post(
    `${BASE}/chat`,
    {
      message,
      conversation_id: sessionId || undefined,
    },
    { headers }
  )
  return res.data
}

export async function streamMessage({ message, history, token, employeeId, sessionId, onResponse, onChunk }) {
  try {
    const res = await sendMessage({ message, history, token, employeeId, sessionId })
    if (onResponse) onResponse(res)
    if (res && res.reply) {
      onChunk(res.reply)
    } else {
      onChunk(JSON.stringify(res))
    }
  } catch (e) {
    if (e.response && e.response.data && e.response.data.detail) {
      throw new Error(e.response.data.detail)
    }
    throw e;
  }
}

export async function confirmAction({ conversationId, pendingToken, approve, token }) {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    const res = await axios.post(
      `${BASE}/confirm`,
      {
        conversation_id: conversationId,
        pending_confirmation_token: pendingToken,
        approve,
      },
      { headers }
    )
    return res.data
  } catch (e) {
    if (e.response && e.response.data && e.response.data.detail) {
      throw new Error(e.response.data.detail)
    }
    throw e;
  }
}

// ── Database Chat Session Endpoints ──

export async function fetchSessionsDB(employeeId, token) {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    const res = await axios.get(`${BASE}/sessions/${employeeId}`, { headers })
    return res.data
  } catch (e) {
    console.warn('Failed to fetch sessions from DB:', e)
    return []
  }
}

export async function createSessionDB(id, employeeId, token, title = 'New Chat', isPinned = false) {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    await axios.post(`${BASE}/sessions`, { id, employee_id: employeeId, title, is_pinned: isPinned }, { headers })
  } catch (e) {
    console.warn('Failed to save session to DB:', e)
  }
}

export async function pinSessionDB(sessionId, isPinned, token) {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    await axios.put(`${BASE}/sessions/${sessionId}/pin`, { is_pinned: isPinned }, { headers })
  } catch (e) {
    console.warn('Failed to pin session in DB:', e)
  }
}

export async function renameSessionDB(sessionId, title, token) {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    await axios.put(`${BASE}/sessions/${sessionId}/rename`, { title }, { headers })
  } catch (e) {
    console.warn('Failed to rename session in DB:', e)
  }
}

export async function deleteSessionDB(sessionId, token) {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    await axios.delete(`${BASE}/sessions/${sessionId}`, { headers })
  } catch (e) {
    console.warn('Failed to delete session in DB:', e)
  }
}

// ── Security & Audit Endpoints ──

export async function fetchAuditTrail(employeeId = '', limit = 100) {
  return []
}

export async function fetchSecurityEvents(limit = 100) {
  return []
}

// ── Autonomous session-start briefing ──

export async function fetchAgentBriefing({ token, employeeId }) {
  if (!employeeId || !token) return []
  
  try {
    const headers = { Authorization: `Bearer ${token}` }
    const res = await axios.get(`http://localhost:8082/api/notifications/${employeeId}`, { headers })
    const notifications = Array.isArray(res.data) ? res.data : []
    
    // Filter unread notifications
    const unread = notifications.filter(n => !n.read)
    
    if (unread.length === 0) return []
    
    const briefing = []
    
    // Group or summarize them. If there's just a few, show them, otherwise summarize.
    if (unread.length === 1) {
      briefing.push({
        tag: 'Notification',
        tier: 'safe',
        text: unread[0].message
      })
    } else {
      briefing.push({
        tag: 'Notifications',
        tier: 'safe',
        text: `You have ${unread.length} unread notifications.`
      })
      
      // Optionally show the first one or two
      for (let i = 0; i < Math.min(2, unread.length); i++) {
        briefing.push({
          tag: 'Alert',
          tier: 'safe',
          text: unread[i].message
        })
      }
    }
    
    return briefing
  } catch (e) {
    console.warn('Failed to fetch agent briefing:', e)
    return []
  }
}

// ── File attachments (PDF / images) ──

export async function uploadChatFile(file, employeeId) {
  const form = new FormData()
  form.append('file', file)
  form.append('employee_id', employeeId)
  try {
    const res = await axios.post(`${BASE}/api/files/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return { ok: true, ...res.data }
  } catch (e) {
    const detail = e?.response?.data?.detail || 'Upload failed.'
    return { ok: false, error: detail }
  }
}
