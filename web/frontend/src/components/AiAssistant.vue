<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  askAssistantStream,
  cancelAssistantRequest,
  configureAssistant,
  fetchAssistantConversation,
  fetchAssistantStatus,
  probeAssistant,
  setAssistantPersistence,
} from '../api'

const DEFAULT_DRAWER_WIDTH = 400
const MIN_DRAWER_WIDTH = 340
const MAX_DRAWER_WIDTH = 760
const MIN_WORKSPACE_WIDTH = 620
const MOBILE_BREAKPOINT = 900

const props = defineProps({
  open: Boolean,
  sessionId: { type: String, default: '' },
  pcapName: { type: String, default: '' },
  persistent: Boolean,
  sessions: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'update:open',
  'navigate-message',
  'navigate-service',
  'navigate-eventgroup',
  'navigate-signal',
])

const status = ref({ configured: false, api_base: '', model: '', source: 'none' })
const statusLoading = ref(false)
const configOpen = ref(false)
const configSaving = ref(false)
const configError = ref('')
const configForm = ref({
  api_key: '',
  api_base: '',
  model: '',
  provider: 'auto',
  context_window: 65536,
  max_output_tokens: 4096,
  stream: true,
})
const probeLoading = ref(false)
const probeResult = ref(null)

const messages = ref([])
const conversationId = ref(null)
const draft = ref('')
const sending = ref(false)
const chatError = ref('')
const progressEvents = ref([])
const progressMessage = ref('')
const streamedAnswer = ref('')
const contextStats = ref(null)
const failedQuestion = ref('')
const persistence = ref({ available: false, enabled: false })
const persistenceSaving = ref(false)
// 勾选项构成本轮请求的显式白名单；切换主会话时立即清空，避免权限串会话。
const comparisonSessionIds = ref([])
const comparisonOptions = computed(() => (
  props.sessions.filter(item => item?.session_id && item.session_id !== props.sessionId)
))
const messageList = ref(null)
const drawerWidth = ref(DEFAULT_DRAWER_WIDTH)
const resizing = ref(false)
let resizeStartX = 0
let resizeStartWidth = DEFAULT_DRAWER_WIDTH
let activeController = null
let activeRequestId = ''
let activeRequestSessionId = ''
let conversationLoadSerial = 0

watch(() => props.open, async (isOpen) => {
  if (isOpen) {
    refreshStatus()
    await nextTick()
    clampDrawerWidth()
  } else {
    stopResize()
  }
})

// 每段对话只绑定一份解析记录；切换记录时清空上下文，防止“这个服务”等指代串到其他会话。
watch(() => props.sessionId, (sessionId) => {
  cancelCurrentRequest()
  messages.value = []
  conversationId.value = null
  draft.value = ''
  chatError.value = ''
  progressEvents.value = []
  progressMessage.value = ''
  streamedAnswer.value = ''
  failedQuestion.value = ''
  persistence.value = { available: false, enabled: false }
  comparisonSessionIds.value = []
  if (sessionId) loadConversation(sessionId)
})

watch(() => props.sessions, () => {
  const available = new Set(comparisonOptions.value.map(item => item.session_id))
  comparisonSessionIds.value = comparisonSessionIds.value.filter(id => available.has(id))
}, { deep: true })

watch(() => props.persistent, (persistent) => {
  persistence.value.available = Boolean(persistent)
  if (!persistent) persistence.value.enabled = false
})

onMounted(() => {
  refreshStatus()
  window.addEventListener('resize', clampDrawerWidth)
})

onUnmounted(() => {
  cancelCurrentRequest()
  if (scrollFrame) window.cancelAnimationFrame(scrollFrame)
  stopResize()
  window.removeEventListener('resize', clampDrawerWidth)
})

async function refreshStatus() {
  statusLoading.value = true
  try {
    const next = await fetchAssistantStatus()
    applyStatus(next)
    probeResult.value = null
    if (!next.configured) configOpen.value = true
  } catch (error) {
    configError.value = apiError(error, '无法读取模型配置')
  } finally {
    statusLoading.value = false
  }
}

function applyStatus(next) {
  status.value = next
  configForm.value.api_base = next.api_base || 'https://api.deepseek.com'
  configForm.value.model = next.model || 'deepseek-v4-flash'
  configForm.value.provider = next.provider || 'auto'
  configForm.value.context_window = next.context_window || 65536
  configForm.value.max_output_tokens = next.max_output_tokens || 4096
  configForm.value.stream = next.stream !== false
}

async function saveConfig() {
  configSaving.value = true
  configError.value = ''
  try {
    const next = await configureAssistant({
      api_key: configForm.value.api_key || null,
      api_base: configForm.value.api_base.trim(),
      model: configForm.value.model.trim(),
      provider: configForm.value.provider,
      context_window: Number(configForm.value.context_window),
      max_output_tokens: Number(configForm.value.max_output_tokens),
      stream: Boolean(configForm.value.stream),
    })
    applyStatus(next)
    configForm.value.api_key = ''
    configOpen.value = false
  } catch (error) {
    configError.value = apiError(error, '模型配置保存失败')
  } finally {
    configSaving.value = false
  }
}

async function runProbe() {
  if (probeLoading.value || !status.value.configured) return
  probeLoading.value = true
  probeResult.value = null
  configError.value = ''
  try {
    probeResult.value = await probeAssistant()
  } catch (error) {
    configError.value = apiError(error, '模型能力验证失败')
  } finally {
    probeLoading.value = false
  }
}

async function loadConversation(sessionId) {
  const serial = ++conversationLoadSerial
  try {
    const result = await fetchAssistantConversation(sessionId)
    if (serial !== conversationLoadSerial || sessionId !== props.sessionId) return
    persistence.value = {
      available: Boolean(result.available),
      enabled: Boolean(result.enabled),
    }
    const conversation = result.conversation
    if (!conversation) return
    conversationId.value = conversation.conversation_id
    messages.value = (conversation.history || []).map(item => ({
      role: item.role,
      content: item.content,
      renderedContent: item.role === 'assistant' ? renderMarkdown(item.content) : null,
      model: conversation.model,
    }))
    await scrollToLatest()
  } catch (error) {
    if (serial === conversationLoadSerial) {
      chatError.value = apiError(error, '无法恢复 AI 对话')
    }
  }
}

async function togglePersistence() {
  if (persistenceSaving.value || !props.sessionId) return
  persistenceSaving.value = true
  chatError.value = ''
  try {
    const result = await setAssistantPersistence(
      props.sessionId,
      !persistence.value.enabled,
    )
    persistence.value = {
      available: Boolean(result.available),
      enabled: Boolean(result.enabled),
    }
  } catch (error) {
    chatError.value = apiError(error, '对话保存设置失败')
  } finally {
    persistenceSaving.value = false
  }
}

async function submitQuestion(value = draft.value) {
  const question = String(value || '').trim()
  if (!question || sending.value || !props.sessionId || !status.value.configured) return
  const submittedSessionId = props.sessionId

  messages.value.push({ role: 'user', content: question })
  draft.value = ''
  sending.value = true
  chatError.value = ''
  failedQuestion.value = ''
  // 每个问题独立显示进度，避免上一轮 Tool 状态残留造成误解。
  progressEvents.value = []
  progressMessage.value = '正在分析问题'
  streamedAnswer.value = ''
  contextStats.value = null
  activeController = new AbortController()
  activeRequestId = createRequestId()
  activeRequestSessionId = props.sessionId
  await scrollToLatest()

  try {
    const result = await askAssistantStream(
      submittedSessionId,
      question,
      conversationId.value,
      onProgressEvent,
      {
        signal: activeController.signal,
        requestId: activeRequestId,
        comparisonSessionIds: comparisonSessionIds.value,
      },
    )
    if (props.sessionId !== submittedSessionId) return
    conversationId.value = result.conversation_id
    messages.value.push({
      role: 'assistant',
      content: result.answer,
      renderedContent: renderMarkdown(result.answer),
      tools: result.tools || [],
      model: result.model,
      usage: result.usage || {},
      context: result.context || null,
    })
  } catch (error) {
    if (props.sessionId !== submittedSessionId) return
    const cancelled = error?.name === 'AbortError' || error?.code === 'ASSISTANT_CANCELLED'
    if (cancelled) {
      chatError.value = '请求已取消，可重新发送该问题。'
    } else {
      chatError.value = apiError(error, '问答请求失败')
    }
    failedQuestion.value = question
  } finally {
    activeController = null
    activeRequestId = ''
    activeRequestSessionId = ''
    sending.value = false
    progressMessage.value = ''
    streamedAnswer.value = ''
    await scrollToLatest()
  }
}

function onProgressEvent(event) {
  if (event.type === 'status' || event.type === 'context') {
    progressMessage.value = event.message || '正在分析问题'
    if (event.type === 'context') contextStats.value = event
    return
  }
  if (event.type === 'text_reset') {
    streamedAnswer.value = ''
    return
  }
  if (event.type === 'text_delta') {
    streamedAnswer.value += event.delta || ''
    scheduleScroll()
    return
  }
  if (event.type === 'tool_start') {
    progressMessage.value = event.message || `正在调用 ${event.name}`
    progressEvents.value = [
      ...progressEvents.value,
      { name: event.name, message: progressMessage.value, status: 'running' },
    ]
    return
  }
  if (event.type === 'tool_end') {
    // 同一 Tool 可能被模型调用多次，只结束最近一条仍在运行的记录。
    const next = [...progressEvents.value]
    for (let index = next.length - 1; index >= 0; index -= 1) {
      if (next[index].name !== event.name || next[index].status !== 'running') continue
      next[index] = {
        ...next[index],
        message: event.message,
        status: event.ok ? 'done' : 'error',
      }
      break
    }
    progressEvents.value = next
    progressMessage.value = '正在整理查询结果'
  }
}

async function cancelCurrentRequest() {
  if (!activeController) return
  const controller = activeController
  const requestId = activeRequestId
  const requestSessionId = activeRequestSessionId
  // 先通知后端设置取消标记，再中止浏览器读取；两边都执行以释放连接和工作线程。
  if (requestId && requestSessionId) {
    await cancelAssistantRequest(requestSessionId, requestId).catch(() => {})
  }
  controller.abort()
}

function retryLastQuestion() {
  if (!failedQuestion.value || sending.value) return
  const question = failedQuestion.value
  const last = messages.value[messages.value.length - 1]
  if (last?.role === 'user' && last.content === question) messages.value.pop()
  submitQuestion(question)
}

function createRequestId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID()
  return `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

let scrollFrame = 0
function scheduleScroll() {
  if (scrollFrame) return
  scrollFrame = window.requestAnimationFrame(async () => {
    scrollFrame = 0
    await scrollToLatest()
  })
}

function onToolLink(link) {
  if (!link?.kind) return
  emit(`navigate-${link.kind}`, link)
}

function onEvidenceClick(event) {
  const anchor = event.target.closest?.('a')
  const href = anchor?.getAttribute('href') || ''
  if (!href.startsWith('#someip-')) return
  const navigation = parseEvidenceHref(href)
  if (!navigation) return
  event.preventDefault()
  onToolLink(navigation)
}

function parseEvidenceHref(href) {
  let match = href.match(/^#someip-message-(\d+)$/i)
  if (match) return { kind: 'message', message_index: Number(match[1]) }

  match = href.match(/^#someip-service-(0x[0-9a-f]+|\d+)$/i)
  if (match) return { kind: 'service', service_id: parseProtocolId(match[1]) }

  match = href.match(/^#someip-eventgroup-(0x[0-9a-f]+|\d+)-(0x[0-9a-f]+|\d+)$/i)
  if (match) {
    return {
      kind: 'eventgroup',
      service_id: parseProtocolId(match[1]),
      eventgroup_id: parseProtocolId(match[2]),
    }
  }

  if (href.startsWith('#someip-signal?')) {
    const params = new URLSearchParams(href.slice(href.indexOf('?') + 1))
    return {
      kind: 'signal',
      service_id: parseProtocolId(params.get('service')),
      event_id: parseProtocolId(params.get('event')),
      field_path: params.get('field') || null,
      start_time: finiteOrNull(params.get('start')),
      end_time: finiteOrNull(params.get('end')),
    }
  }
  return null
}

function parseProtocolId(value) {
  if (value == null || value === '') return null
  return String(value).toLowerCase().startsWith('0x')
    ? Number.parseInt(value, 16)
    : Number.parseInt(value, 10)
}

function finiteOrNull(value) {
  if (value == null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function onComposerKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submitQuestion()
  }
}

async function scrollToLatest() {
  await nextTick()
  const el = messageList.value
  if (el) el.scrollTop = el.scrollHeight
}

function closePanel() {
  emit('update:open', false)
}

function renderMarkdown(content) {
  const html = marked.parse(String(content || ''), {
    async: false,
    breaks: true,
    gfm: true,
  })
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: [
      'style', 'iframe', 'img', 'video', 'audio', 'object', 'embed',
      'form', 'input', 'textarea', 'button', 'select', 'option',
    ],
    FORBID_ATTR: ['style'],
  })
}

function startResize(event) {
  if (window.innerWidth <= MOBILE_BREAKPOINT || (event.button ?? 0) !== 0) return
  event.preventDefault()
  resizing.value = true
  resizeStartX = event.clientX
  resizeStartWidth = drawerWidth.value
  document.body.classList.add('assistant-is-resizing')
  window.addEventListener('pointermove', resizeDrawer)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

function resizeDrawer(event) {
  if (!resizing.value) return
  setDrawerWidth(resizeStartWidth + resizeStartX - event.clientX)
}

function stopResize() {
  if (!resizing.value) return
  resizing.value = false
  document.body.classList.remove('assistant-is-resizing')
  window.removeEventListener('pointermove', resizeDrawer)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
}

function resizeWithKeyboard(event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  if (event.key === 'ArrowLeft') setDrawerWidth(drawerWidth.value + 24)
  if (event.key === 'ArrowRight') setDrawerWidth(drawerWidth.value - 24)
  if (event.key === 'Home') setDrawerWidth(MIN_DRAWER_WIDTH)
  if (event.key === 'End') setDrawerWidth(maxDrawerWidth())
}

function setDrawerWidth(width) {
  drawerWidth.value = Math.round(Math.min(maxDrawerWidth(), Math.max(MIN_DRAWER_WIDTH, width)))
}

function clampDrawerWidth() {
  if (window.innerWidth > MOBILE_BREAKPOINT) setDrawerWidth(drawerWidth.value)
}

function maxDrawerWidth() {
  // 桌面端始终给协议分析区保留可操作空间，窄屏由 CSS 切换为单视图。
  return Math.max(
    MIN_DRAWER_WIDTH,
    Math.min(MAX_DRAWER_WIDTH, window.innerWidth - MIN_WORKSPACE_WIDTH),
  )
}

function apiError(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    return detail.map(item => item?.msg || String(item)).join('；')
  }
  if (typeof error?.response?.data === 'string' && error.response.data.trim()) {
    return error.response.data
  }
  return error?.message || fallback
}
</script>

<template>
  <Transition name="assistant-panel">
      <aside
        v-if="open"
        class="assistant-drawer"
        :class="{ 'is-resizing': resizing }"
        :style="{ width: `${drawerWidth}px` }"
        aria-label="AI 分析助手"
      >
        <button
          type="button"
          class="assistant-resize-handle"
          role="separator"
          aria-label="调整 AI 对话框宽度"
          aria-orientation="vertical"
          :aria-valuemin="MIN_DRAWER_WIDTH"
          :aria-valuemax="maxDrawerWidth()"
          :aria-valuenow="drawerWidth"
          title="向左拖动调整宽度"
          @pointerdown="startResize"
          @keydown="resizeWithKeyboard"
        ></button>
        <header class="assistant-header">
          <div>
            <h2>AI 分析助手</h2>
            <p>{{ status.model || '尚未配置模型' }}<template v-if="status.effective_provider"> · {{ status.effective_provider }}</template></p>
          </div>
          <div class="assistant-header-actions">
            <span
              class="model-state"
              :class="status.configured ? 'is-ready' : 'is-offline'"
            >{{ status.configured ? '已连接' : '待配置' }}</span>
            <button
              type="button"
              class="assistant-close"
              aria-label="关闭 AI 助手"
              title="关闭"
              @click="closePanel"
            >×</button>
          </div>
        </header>

        <section class="assistant-context">
          <span>当前抓包</span>
          <strong :title="pcapName || sessionId || '未选择抓包'">
            {{ pcapName || (sessionId ? `会话 ${sessionId}` : '未选择抓包') }}
          </strong>
          <small v-if="sessionId" class="mono" :title="sessionId">{{ sessionId }}</small>
          <button
            v-if="sessionId"
            type="button"
            class="conversation-persistence"
            :class="{ active: persistence.enabled }"
            :disabled="persistenceSaving || !persistence.available"
            :title="persistence.available ? '选择是否随解析记录保存 AI 对话' : '请先持久化保存解析记录'"
            @click="togglePersistence"
          >
            {{ persistenceSaving ? '设置中...' : (persistence.enabled ? '对话已保存' : '对话不保存') }}
          </button>
          <details v-if="comparisonOptions.length" class="assistant-comparison">
            <summary :title="'选择本轮允许 AI 比较的解析记录'">
              对比 {{ comparisonSessionIds.length }}
            </summary>
            <div class="comparison-menu">
              <strong>允许本轮比较</strong>
              <label v-for="item in comparisonOptions" :key="item.session_id">
                <input
                  v-model="comparisonSessionIds"
                  type="checkbox"
                  :value="item.session_id"
                  :disabled="comparisonSessionIds.length >= 3 && !comparisonSessionIds.includes(item.session_id)"
                >
                <span :title="item.pcap_name || item.session_id">
                  {{ item.pcap_name || item.session_id }}
                </span>
              </label>
              <small>最多选择 3 条；未勾选的记录不会授权给模型。</small>
            </div>
          </details>
        </section>

        <section class="assistant-config" :class="{ expanded: configOpen }">
          <button
            type="button"
            class="config-toggle"
            :aria-expanded="configOpen"
            @click="configOpen = !configOpen"
          >
            <span>模型配置</span>
            <span>{{ configOpen ? '收起' : '编辑' }}</span>
          </button>
          <form v-if="configOpen" class="config-form" @submit.prevent="saveConfig">
            <p class="config-note">
              Provider 决定请求格式；上下文窗口必须按模型文档填写。API Key 只保存在当前后端进程。
            </p>
            <label>
              <span>Provider</span>
              <select v-model="configForm.provider">
                <option
                  v-for="item in status.providers || []"
                  :key="item.provider"
                  :value="item.provider"
                >{{ item.label }}</option>
              </select>
            </label>
            <label>
              <span>API Key</span>
              <input
                v-model="configForm.api_key"
                type="password"
                autocomplete="off"
                :placeholder="status.configured ? '留空则保持当前 Key' : '请输入 DeepSeek API Key'"
              >
              <small>仅保存在当前后端进程内存中，不写入浏览器或磁盘。</small>
            </label>
            <label>
              <span>API 地址</span>
              <input v-model="configForm.api_base" type="url" required>
            </label>
            <label>
              <span>模型名称</span>
              <input v-model="configForm.model" type="text" required>
            </label>
            <div class="config-number-grid">
              <label>
                <span>上下文窗口</span>
                <input v-model.number="configForm.context_window" type="number" min="4096" max="2000000" required>
              </label>
              <label>
                <span>最大输出 Token</span>
                <input v-model.number="configForm.max_output_tokens" type="number" min="256" max="131072" required>
              </label>
            </div>
            <label class="config-check">
              <input v-model="configForm.stream" type="checkbox">
              <span>启用模型文本流式输出</span>
            </label>
            <p v-if="configError" class="config-error" role="alert">{{ configError }}</p>
            <p v-if="probeResult" class="probe-result" :class="{ ok: probeResult.ok }">
              {{ probeResult.message }}
            </p>
            <div class="config-actions">
              <button class="config-probe" type="button" :disabled="probeLoading || !status.configured" @click="runProbe">
                {{ probeLoading ? '验证中...' : '验证 Tool Calling' }}
              </button>
              <button class="config-save" type="submit" :disabled="configSaving || statusLoading">
                {{ configSaving ? '保存中...' : '应用配置' }}
              </button>
            </div>
          </form>
        </section>

        <div ref="messageList" class="assistant-messages" aria-live="polite">
          <section v-if="!sessionId" class="assistant-empty">
            <strong>未选择解析记录</strong>
            <p>请先打开一组已解析的 PCAP 和 ARXML 记录。</p>
          </section>

          <section v-else-if="!status.configured" class="assistant-empty">
            <strong>需要配置模型</strong>
            <p>请在上方填写 DeepSeek API Key，或修改为其他兼容模型服务。</p>
          </section>

          <section v-else-if="messages.length === 0" class="assistant-empty assistant-starters">
            <strong>询问当前抓包</strong>
            <p>支持服务查找、Offer 与订阅时间线、报文筛选和单报文解析。</p>
            <button type="button" @click="submitQuestion('总结当前抓包中的服务 Offer 和订阅情况')">
              总结 Offer 和订阅情况
            </button>
            <button type="button" @click="submitQuestion('检查当前抓包中是否存在订阅异常')">
              检查订阅异常
            </button>
          </section>

          <article
            v-for="(message, index) in messages"
            :key="`${message.role}-${index}`"
            class="chat-message"
            :class="`is-${message.role}`"
          >
            <span class="message-role">{{ message.role === 'user' ? '我' : 'AI 助手' }}</span>
            <div
              v-if="message.role === 'assistant'"
              class="message-content markdown-body"
              v-html="message.renderedContent"
              @click="onEvidenceClick"
            ></div>
            <div v-else class="message-content user-content">{{ message.content }}</div>
            <footer v-if="message.tools?.length" class="tool-evidence">
              <span>调用工具：{{ message.tools.map(tool => tool.name).join(', ') }}</span>
              <div v-if="message.tools.some(tool => tool.links?.length)" class="evidence-links">
                <button
                  v-for="(link, linkIndex) in message.tools.flatMap(tool => tool.links || [])"
                  :key="`${link.kind}-${link.message_index ?? link.service_id}-${link.eventgroup_id ?? linkIndex}`"
                  type="button"
                  @click="onToolLink(link)"
                >{{ link.label }}</button>
              </div>
            </footer>
            <footer v-if="message.role === 'assistant' && (message.usage || message.context)" class="message-metrics">
              <span v-if="message.usage?.total_tokens">Token {{ message.usage.total_tokens }}</span>
              <span v-if="message.context?.estimated_input_tokens">估算输入 {{ message.context.estimated_input_tokens }}</span>
              <span v-if="message.context?.dropped_messages">摘要 {{ message.context.dropped_messages }} 条旧消息</span>
            </footer>
          </article>

          <article v-if="sending" class="chat-message is-assistant is-loading" aria-label="AI 正在分析">
            <span class="message-role">AI 助手</span>
            <div class="assistant-progress">
              <strong>{{ progressMessage || '正在分析问题' }}</strong>
              <div v-if="progressEvents.length" class="progress-steps">
                <span
                  v-for="(item, index) in progressEvents"
                  :key="`${item.name}-${index}`"
                  :class="`is-${item.status}`"
                >{{ item.message }}</span>
              </div>
              <div v-else class="loading-lines"><i></i><i></i><i></i></div>
              <div
                v-if="streamedAnswer"
                class="streamed-answer markdown-body"
                v-html="renderMarkdown(streamedAnswer)"
              ></div>
              <small v-if="contextStats" class="context-budget">
                估算 {{ contextStats.estimated_input_tokens }} / {{ contextStats.context_window }} Token
              </small>
            </div>
          </article>

          <div v-if="chatError" class="chat-error" role="alert">
            <span>{{ chatError }}</span>
            <button v-if="failedQuestion" type="button" @click="retryLastQuestion">重试</button>
          </div>
        </div>

        <form class="assistant-composer" @submit.prevent="submitQuestion()">
          <label for="assistant-question" class="sr-only">问题</label>
          <textarea
            id="assistant-question"
            v-model="draft"
            rows="3"
            :disabled="!sessionId || !status.configured || sending"
            placeholder="询问某个服务、Offer 或订阅状态..."
            @keydown="onComposerKeydown"
          ></textarea>
          <div class="composer-footer">
            <span>Enter 发送，Shift+Enter 换行</span>
            <button v-if="sending" type="button" class="stop-request" @click="cancelCurrentRequest">停止</button>
            <button v-else type="submit" :disabled="!draft.trim() || !sessionId || !status.configured">发送</button>
          </div>
        </form>
      </aside>
  </Transition>
</template>

<style>
.assistant-drawer {
  position: relative;
  z-index: 3;
  flex: 0 0 auto;
  height: 100%;
  min-width: 0;
  width: min(440px, 100vw);
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  border-left: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text-primary);
  box-shadow: -10px 0 26px rgba(30, 38, 50, .10);
}
.assistant-drawer.is-resizing { transition: none; }
.assistant-resize-handle {
  position: absolute;
  inset: 0 auto 0 -6px;
  z-index: 2;
  width: 12px;
  padding: 0;
  border: 0;
  outline: none;
  background: transparent;
  cursor: col-resize;
  touch-action: none;
}
.assistant-resize-handle::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 5px;
  width: 2px;
  height: 42px;
  border-radius: 1px;
  background: var(--border-strong);
  transform: translateY(-50%);
  transition: height .16s ease, background-color .16s ease;
}
.assistant-resize-handle:hover::after,
.assistant-resize-handle:focus-visible::after,
.assistant-drawer.is-resizing .assistant-resize-handle::after {
  height: 64px;
  background: var(--accent);
}
body.assistant-is-resizing {
  cursor: col-resize;
  user-select: none;
}
:root[data-theme="dark"] .assistant-drawer {
  box-shadow: -10px 0 30px rgba(0, 0, 0, .28);
}
.assistant-panel-enter-active,
.assistant-panel-leave-active {
  transition: transform .2s ease, opacity .2s ease;
}
.assistant-panel-enter-from,
.assistant-panel-leave-to {
  transform: translateX(24px);
  opacity: 0;
}
.assistant-header {
  min-height: 66px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 12px 11px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-raised);
}
.assistant-header h2 {
  font-size: 15px;
  line-height: 1.25;
  font-weight: 900;
}
.assistant-header p {
  margin-top: 3px;
  color: var(--text-tertiary);
  font-size: 11px;
  font-family: var(--font-mono);
}
.assistant-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.model-state {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  font-size: 10px;
  font-weight: 850;
  white-space: nowrap;
}
.model-state.is-ready {
  border-color: var(--success-border);
  background: var(--success-soft);
  color: var(--success);
}
.model-state.is-offline {
  border-color: var(--warning-border);
  background: var(--warning-soft);
  color: var(--warning);
}
.assistant-close {
  width: 32px;
  height: 32px;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 24px;
  line-height: 1;
}
.assistant-close:hover {
  border-color: var(--border);
  background: var(--surface-hover);
  color: var(--text-primary);
}
.assistant-context {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(60px, 1fr) minmax(0, 72px) auto auto;
  align-items: center;
  gap: 7px;
  min-height: 42px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
}
.assistant-context span {
  color: var(--text-tertiary);
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
}
.assistant-context strong,
.assistant-context small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.assistant-context strong {
  font-size: 12px;
  font-weight: 850;
}
.assistant-context small {
  color: var(--text-tertiary);
  font-size: 10px;
}
.conversation-persistence {
  width: max-content;
  min-height: 26px;
  margin: 0;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 10px;
  font-weight: 800;
}
.conversation-persistence.active {
  border-color: var(--success-border);
  background: var(--success-soft);
  color: var(--success);
}
.conversation-persistence:disabled { cursor: not-allowed; opacity: .58; }
.assistant-comparison {
  position: relative;
  font-size: 10px;
}
.assistant-comparison summary {
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--text-secondary);
  cursor: pointer;
  font-weight: 800;
  list-style: none;
  white-space: nowrap;
}
.assistant-comparison summary::-webkit-details-marker { display: none; }
.assistant-comparison[open] summary {
  border-color: var(--accent);
  color: var(--accent);
}
.comparison-menu {
  position: absolute;
  z-index: 12;
  top: calc(100% + 7px);
  right: 0;
  width: min(280px, calc(100vw - 28px));
  max-height: 260px;
  overflow: auto;
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-panel);
  background: var(--surface-raised);
  box-shadow: 0 12px 28px rgba(30, 38, 50, .16);
}
.comparison-menu > strong { font-size: 11px; }
.comparison-menu label {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  min-height: 28px;
  cursor: pointer;
}
.comparison-menu label span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-size: 11px;
  text-transform: none;
}
.comparison-menu > small {
  color: var(--text-tertiary);
  font-size: 9px;
  white-space: normal;
}
.assistant-config {
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.config-toggle {
  width: 100%;
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
  font-weight: 850;
}
.config-toggle:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}
.config-toggle span:last-child { color: var(--accent); }
.config-form {
  display: grid;
  gap: 11px;
  padding: 2px 16px 14px;
}
.config-note {
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.5;
}
.config-form label {
  display: grid;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 800;
}
.config-form input:not([type="checkbox"]),
.config-form select {
  width: 100%;
  height: 34px;
  padding: 0 9px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-control);
  outline: none;
  background: var(--surface-subtle);
  color: var(--text-primary);
  font-size: 12px;
}
.config-form input::placeholder { color: var(--text-tertiary); }
.config-form input:focus,
.config-form select:focus {
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}
.config-number-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 9px;
}
.config-check {
  display: flex !important;
  grid-template-columns: none !important;
  align-items: center;
  gap: 8px !important;
}
.config-check input { width: 15px; height: 15px; accent-color: var(--accent); }
.config-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.config-probe {
  min-height: 34px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-control);
  background: var(--surface-subtle);
  color: var(--text-primary);
  cursor: pointer;
  font-size: 11px;
  font-weight: 850;
}
.config-probe:disabled { opacity: .55; cursor: not-allowed; }
.probe-result {
  color: var(--danger);
  font-size: 10px;
  font-weight: 750;
}
.probe-result.ok { color: var(--success); }
.config-form label small {
  color: var(--text-tertiary);
  font-size: 10px;
  font-weight: 650;
}
.config-error,
.chat-error {
  color: var(--danger);
  font-size: 11px;
  font-weight: 750;
}
.config-save {
  min-height: 34px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-control);
  background: var(--accent);
  color: var(--accent-contrast);
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
}
.config-save:hover:not(:disabled) {
  border-color: var(--accent-hover);
  background: var(--accent-hover);
}
.config-save:disabled { opacity: .55; cursor: not-allowed; }
.assistant-messages {
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  background: var(--canvas);
}
.assistant-empty {
  margin: 20px 0;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
}
.assistant-empty strong {
  display: block;
  font-size: 13px;
  font-weight: 900;
}
.assistant-empty p {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.assistant-starters button {
  width: 100%;
  min-height: 36px;
  margin-top: 9px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface-subtle);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  font-size: 12px;
  font-weight: 750;
}
.assistant-starters button:hover {
  border-color: var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent);
}
.chat-message {
  width: fit-content;
  max-width: 92%;
  margin-bottom: 13px;
}
.chat-message.is-assistant {
  width: 100%;
  max-width: 100%;
}
.chat-message.is-user { margin-left: auto; }
.message-role {
  display: block;
  margin: 0 2px 4px;
  color: var(--text-tertiary);
  font-size: 9px;
  font-weight: 850;
  text-transform: uppercase;
}
.chat-message.is-user .message-role { text-align: right; }
.message-content {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.58;
  overflow-wrap: anywhere;
}
.chat-message.is-user .message-content {
  border-color: var(--accent-border);
  background: var(--accent-soft);
}
.user-content { white-space: pre-wrap; }
.markdown-body > :first-child { margin-top: 0; }
.markdown-body > :last-child { margin-bottom: 0; }
.markdown-body p,
.markdown-body ul,
.markdown-body ol,
.markdown-body blockquote,
.markdown-body pre,
.markdown-body table {
  margin: 0 0 10px;
}
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  margin: 15px 0 7px;
  color: var(--text-primary);
  line-height: 1.35;
  letter-spacing: 0;
}
.markdown-body h1 { font-size: 16px; }
.markdown-body h2 { font-size: 14px; }
.markdown-body h3,
.markdown-body h4 { font-size: 13px; }
.markdown-body ul,
.markdown-body ol { padding-left: 20px; }
.markdown-body li + li { margin-top: 3px; }
.markdown-body strong { font-weight: 900; }
.markdown-body a {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown-body blockquote {
  padding: 7px 10px;
  border-left: 3px solid var(--accent-border);
  background: var(--surface-subtle);
  color: var(--text-secondary);
}
.markdown-body code {
  padding: 1px 4px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--surface-subtle);
  font-family: var(--font-mono);
  font-size: 11px;
}
.markdown-body pre {
  max-width: 100%;
  overflow: auto;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface-subtle);
}
.markdown-body pre code {
  padding: 0;
  border: 0;
  background: transparent;
}
.markdown-body table {
  display: block;
  width: 100%;
  overflow-x: auto;
  border-spacing: 0;
  border-collapse: collapse;
  font-size: 11px;
}
.markdown-body th,
.markdown-body td {
  min-width: 86px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}
.markdown-body th {
  background: var(--surface-subtle);
  font-weight: 850;
}
.markdown-body hr {
  height: 1px;
  margin: 12px 0;
  border: 0;
  background: var(--border);
}
.chat-message footer {
  margin: 5px 2px 0;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 9px;
}
.tool-evidence > span { display: block; }
.message-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.evidence-links {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 6px;
}
.evidence-links button {
  min-height: 25px;
  padding: 3px 7px;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-control);
  background: var(--accent-soft);
  color: var(--accent);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 800;
}
.evidence-links button:hover { border-color: var(--accent); background: var(--surface-selected); }
.is-loading { width: 62%; }
.assistant-progress {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
}
.assistant-progress > strong {
  display: block;
  color: var(--text-secondary);
  font-size: 11px;
}
.streamed-answer {
  margin-top: 9px;
  padding-top: 9px;
  border-top: 1px solid var(--border);
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.58;
}
.context-budget {
  display: block;
  margin-top: 8px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 9px;
}
.progress-steps { display: grid; gap: 5px; margin-top: 8px; }
.progress-steps span {
  padding-left: 13px;
  color: var(--text-tertiary);
  font-size: 10px;
  position: relative;
}
.progress-steps span::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  width: 6px;
  height: 6px;
  border: 1px solid currentColor;
  border-radius: 50%;
}
.progress-steps .is-running { color: var(--accent); }
.progress-steps .is-done { color: var(--success); }
.progress-steps .is-error { color: var(--danger); }
.loading-lines {
  display: grid;
  gap: 6px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
}
.loading-lines i {
  height: 6px;
  border-radius: 3px;
  background: var(--surface-muted);
}
.loading-lines i:nth-child(2) { width: 84%; }
.loading-lines i:nth-child(3) { width: 56%; }
.chat-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 10px;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-control);
  background: var(--danger-soft);
}
.chat-error button {
  flex-shrink: 0;
  min-height: 27px;
  padding: 0 8px;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--danger);
  cursor: pointer;
  font-weight: 850;
}
.assistant-composer {
  padding: 12px;
  border-top: 1px solid var(--border);
  background: var(--surface-raised);
}
.assistant-composer textarea {
  width: 100%;
  height: 78px;
  resize: none;
  padding: 9px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-control);
  outline: none;
  background: var(--surface-subtle);
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.45;
}
.assistant-composer textarea::placeholder { color: var(--text-tertiary); }
.assistant-composer textarea:focus {
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}
.assistant-composer textarea:disabled { opacity: .58; cursor: not-allowed; }
.composer-footer {
  min-height: 32px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-top: 7px;
}
.composer-footer span {
  color: var(--text-tertiary);
  font-size: 9px;
  line-height: 1.35;
}
.composer-footer button {
  min-width: 68px;
  min-height: 32px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-control);
  background: var(--accent);
  color: var(--accent-contrast);
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
}
.composer-footer button:hover:not(:disabled) {
  border-color: var(--accent-hover);
  background: var(--accent-hover);
}
.composer-footer .stop-request {
  border-color: var(--danger-border);
  background: var(--danger-soft);
  color: var(--danger);
}
.composer-footer button:disabled {
  border-color: var(--border);
  background: var(--surface-muted);
  color: var(--text-tertiary);
  cursor: not-allowed;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@media (max-width: 900px) {
  .assistant-drawer { width: 100vw !important; }
  .assistant-resize-handle { display: none; }
  .assistant-header { padding-left: 12px; }
  .assistant-messages { padding: 12px; }
}
</style>
