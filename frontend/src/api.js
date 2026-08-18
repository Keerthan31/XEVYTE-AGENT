import axios from 'axios'

axios.defaults.withCredentials = true;

const BASE = 'http://localhost:8443/api/agent'

export async function exchangeToken(token) {
  try {
    const res = await axios.post(`${BASE}/auth/token`, { token })
    return res.data  // { employee_id, employee_name, role, tenant_name, expires_at }
  } catch (e) {
    console.warn('Failed to exchange token with backend:', e)
    return null
  }
}

export async function fetchSessionMessagesDB(sessionId, token) {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    const res = await axios.get(`${BASE}/sessions/${sessionId}/messages`, { headers })
    return res.data
  } catch (e) {
    console.warn('Failed to fetch session messages from DB:', e)
    return []
  }
}

export async function sendMessage({ message, history, token, employeeId, sessionId, file }) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  if (file) {
    const form = new FormData()
    form.append('message', message)
    if (sessionId) form.append('conversation_id', sessionId)
    form.append('files', file)
    const res = await axios.post(`${BASE}/chat/upload`, form, { headers: { ...headers, 'Content-Type': 'multipart/form-data' } })
    return res.data
  } else {
    const res = await axios.post(
      `${BASE}/chat`,
      {
        message,
        history,
        token,
        employee_id: employeeId,
        session_id: sessionId,
        conversation_id: sessionId,
      },
      { headers }
    )
    return res.data
  }
}

export async function streamMessage({ message, history, token, employeeId, sessionId, file, onResponse, onChunk }) {
  try {
    const res = await sendMessage({ message, history, token, employeeId, sessionId, file })
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

export async function confirmAction({ conversationId, pendingToken, approve, token, employeeId }) {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    const res = await axios.post(
      `${BASE}/confirm`,
      {
        session_id: conversationId,
        token: pendingToken,
        approve,
        employee_id: employeeId
      },
      { headers }
    )
    return res.data
  } catch (e) {
    if (e.response && e.response.data && e.response.data.detail) {
      const detail = e.response.data.detail
      const msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
      throw new Error(msg)
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
