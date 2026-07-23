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

export function exportUrl(sessionId, filename) {
  return `/api/export/${sessionId}/${filename}`
}
