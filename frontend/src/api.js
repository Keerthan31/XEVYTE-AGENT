import axios from 'axios'

const BASE = import.meta.env.VITE_AGENT_API || 'http://localhost:8001'

export async function sendMessage({ message, history, token, employeeId, sessionId }) {
  const res = await axios.post(`${BASE}/chat`, {
    message,
    history,
    token,
    employee_id: employeeId,
    session_id: sessionId
  })
  return res.data
}

export async function streamMessage({ message, history, token, employeeId, sessionId, onChunk }) {
  const response = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      history,
      token,
      employee_id: employeeId,
      session_id: sessionId
    }),
  });

  if (!response.ok) {
    throw new Error(`Server error (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const dataStr = line.slice(6).trim();
        if (dataStr) {
          let data;
          try {
            data = JSON.parse(dataStr);
          } catch (e) {
            console.error('Failed to parse SSE data', e);
            continue;
          }
          if (data && data.error) {
            throw new Error(data.error);
          }
          onChunk(data);
        }
      }
    }
  }

  if (buffer.trim().startsWith('data: ')) {
    const dataStr = buffer.trim().slice(6).trim();
    if (dataStr) {
      try {
        const data = JSON.parse(dataStr);
        if (data && data.error) throw new Error(data.error);
        onChunk(data);
      } catch (e) {
        console.error('Failed to parse remaining SSE data', e);
      }
    }
  }
}

// ── Database Chat Session Endpoints ──

export async function fetchSessionsDB(employeeId) {
  try {
    const res = await axios.get(`${BASE}/api/chats/sessions/${employeeId}`)
    return res.data
  } catch (e) {
    console.warn('Failed to fetch sessions from DB:', e)
    return []
  }
}

export async function createSessionDB(id, employeeId, title = 'New Chat', isPinned = false) {
  try {
    await axios.post(`${BASE}/api/chats/sessions`, { id, employee_id: employeeId, title, is_pinned: isPinned })
  } catch (e) {
    console.warn('Failed to save session to DB:', e)
  }
}

export async function pinSessionDB(sessionId, isPinned) {
  try {
    await axios.put(`${BASE}/api/chats/sessions/${sessionId}/pin`, { is_pinned: isPinned })
  } catch (e) {
    console.warn('Failed to pin session in DB:', e)
  }
}

export async function renameSessionDB(sessionId, title) {
  try {
    await axios.put(`${BASE}/api/chats/sessions/${sessionId}/rename`, { title })
  } catch (e) {
    console.warn('Failed to rename session in DB:', e)
  }
}

export async function deleteSessionDB(sessionId) {
  try {
    await axios.delete(`${BASE}/api/chats/sessions/${sessionId}`)
  } catch (e) {
    console.warn('Failed to delete session in DB:', e)
  }
}
