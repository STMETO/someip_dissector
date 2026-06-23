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

export function exportUrl(sessionId, filename) {
  return `/api/export/${sessionId}/${filename}`
}
