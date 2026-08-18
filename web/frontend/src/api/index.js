import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 300000 })

export async function uploadFiles(pcapFile, arxmlFile, keepTemp = false) {
  const form = new FormData()
  form.append('pcap_file', pcapFile)
  form.append('arxml_file', arxmlFile)
  form.append('keep_temp', keepTemp)
  const { data } = await api.post('/upload', form)
  return data
}

export async function fetchSessions() {
  const { data } = await api.get('/sessions')
  return data.sessions || []
}

export function cleanupSessions() {
  const url = '/api/sessions/cleanup'
  if (navigator.sendBeacon) {
    navigator.sendBeacon(url, new Blob([], { type: 'application/json' }))
    return Promise.resolve()
  }
  return api.post('/sessions/cleanup')
}

export async function fetchMessages(sessionId) {
  const { data } = await api.get(`/messages/${sessionId}`)
  return data
}

export async function fetchMessageDetail(sessionId, index) {
  const { data } = await api.get(`/message/${sessionId}/${index}`)
  return data
}

export async function deleteSession(sessionId) {
  return api.delete(`/session/${sessionId}`)
}

export async function persistSession(sessionId) {
  const { data } = await api.post(`/session/${sessionId}/persist`)
  return data.session
}

export async function unpersistSession(sessionId) {
  const { data } = await api.post(`/session/${sessionId}/unpersist`)
  return data.session
}

export async function fetchSignalMeta(sessionId) {
  const { data } = await api.get(`/signal/meta/${sessionId}`)
  return data
}

export async function fetchSignalData(sessionId, serviceId, eventId, fieldPath) {
  const { data } = await api.get(`/signal/data/${sessionId}`, {
    params: { service_id: serviceId, event_id: eventId, field_path: fieldPath },
  })
  return data
}

export async function fetchSubscriptionReport(sessionId) {
  const { data } = await api.get('/analysis/subscription-report', {
    params: { session_id: sessionId },
  })
  return data
}

export async function fetchAssistantStatus() {
  const { data } = await api.get('/assistant/status')
  return data
}

export async function configureAssistant(config) {
  const { data } = await api.post('/assistant/config', config)
  return data
}

export async function probeAssistant() {
  const { data } = await api.post('/assistant/probe')
  return data
}

export async function fetchAssistantConversation(sessionId) {
  const { data } = await api.get(`/session/${sessionId}/assistant/conversations`)
  return data
}

export async function setAssistantPersistence(sessionId, enabled) {
  const { data } = await api.put(`/session/${sessionId}/assistant/persistence`, { enabled })
  return data
}

export async function cancelAssistantRequest(sessionId, requestId) {
  const { data } = await api.post(`/session/${sessionId}/assistant/cancel/${requestId}`)
  return data
}

export async function askAssistant(sessionId, question, conversationId = null) {
  const { data } = await api.post(`/session/${sessionId}/assistant/chat`, {
    question,
    conversation_id: conversationId,
  })
  return data
}

export async function askAssistantStream(
  sessionId,
  question,
  conversationId = null,
  onEvent = () => {},
  options = {},
) {
  const response = await fetch(`/api/session/${sessionId}/assistant/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      conversation_id: conversationId,
      request_id: options.requestId || null,
    }),
    signal: options.signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `问答请求失败 (${response.status})`)
  }
  if (!response.body) throw new Error('浏览器不支持流式响应')

  // NDJSON 可能在任意字节位置分段，因此保留半行到下一次读取继续拼接。
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finalResult = null
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const lines = buffer.split('\n')
    buffer = done ? '' : lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      const event = JSON.parse(line)
      if (event.type === 'error') throw new Error(event.message || 'AI 助手处理失败')
      if (event.type === 'cancelled') {
        const error = new Error(event.message || '请求已取消')
        error.code = 'ASSISTANT_CANCELLED'
        throw error
      }
      if (event.type === 'result') finalResult = event.result
      onEvent(event)
    }
    if (done) break
  }
  if (!finalResult) throw new Error('模型请求结束但没有返回回答')
  return finalResult
}

export function exportUrl(sessionId, filename) {
  return `/api/export/${sessionId}/${filename}`
}
