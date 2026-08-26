import axios from 'axios'

axios.defaults.withCredentials = true;

axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      window.dispatchEvent(new Event('auth:unauthorized'));
    }
    return Promise.reject(error);
  }
);

const BASE = '/api/agent'

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
    if (sessionId) form.append('session_id', sessionId)
    if (employeeId) form.append('employee_id', employeeId)
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
    return null
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
    
    // Fetch notifications, task counts (approvals), and pending policies in parallel
    const [notifsResult, tasksResult, policiesResult] = await Promise.allSettled([
      axios.get(`${BASE}/notifications/${employeeId}`, { headers }),
      axios.get(`${BASE}/task-counts/${employeeId}`, { headers }),
      axios.get(`${BASE}/policies/pending`, { headers })
    ])
    
    const briefing = []

    // 1. Process Task Counts / Pending Manager & HR Approvals
    if (tasksResult.status === 'fulfilled' && tasksResult.value?.data) {
      const counts = tasksResult.value.data
      if (counts.leaves > 0) {
        briefing.push({
          tag: 'Pending Approvals',
          tier: 'confirm',
          text: `You have ${counts.leaves} leave request(s) awaiting your approval.`
        })
      }
      if (counts.claims > 0) {
        briefing.push({
          tag: 'Pending Claims',
          tier: 'confirm',
          text: `You have ${counts.claims} expense claim(s) awaiting your review.`
        })
      }
      if (counts.helpdesk > 0) {
        briefing.push({
          tag: 'Pending Tickets',
          tier: 'confirm',
          text: `You have ${counts.helpdesk} helpdesk change request(s) assigned for action.`
        })
      }
      if (counts.travel > 0) {
        briefing.push({
          tag: 'Pending Travel',
          tier: 'confirm',
          text: `You have ${counts.travel} travel request(s) awaiting your approval.`
        })
      }
      if (counts.regularization > 0) {
        briefing.push({
          tag: 'Regularization',
          tier: 'confirm',
          text: `You have ${counts.regularization} attendance regularization request(s) pending.`
        })
      }
      if (counts.exit > 0) {
        briefing.push({
          tag: 'Exit Management',
          tier: 'confirm',
          text: `You have ${counts.exit} resignation/exit request(s) pending your review.`
        })
      }
    }

    // 2. Process Notifications & System Alerts
    if (notifsResult.status === 'fulfilled' && Array.isArray(notifsResult.value?.data)) {
      const notifications = notifsResult.value.data
      const unread = notifications.filter(n => !n.read && !n.is_read)
      
      if (unread.length === 1) {
        briefing.push({
          tag: 'Notification',
          tier: 'safe',
          text: unread[0].message
        })
      } else if (unread.length > 1) {
        briefing.push({
          tag: 'Notifications',
          tier: 'safe',
          text: `You have ${unread.length} unread notification alerts.`
        })
        for (let i = 0; i < Math.min(3, unread.length); i++) {
          briefing.push({
            tag: 'Alert',
            tier: 'safe',
            text: unread[i].message
          })
        }
      }
    }

    // 3. Process Pending Policies
    if (policiesResult.status === 'fulfilled' && Array.isArray(policiesResult.value?.data) && policiesResult.value.data.length > 0) {
      briefing.push({
        tag: 'Policy Review',
        tier: 'confirm',
        text: `You have ${policiesResult.value.data.length} company policy/policies pending acknowledgment.`
      })
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
