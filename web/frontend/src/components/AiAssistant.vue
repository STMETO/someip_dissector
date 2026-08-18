<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { askAssistant, configureAssistant, fetchAssistantStatus } from '../api'

const DEFAULT_DRAWER_WIDTH = 440
const MIN_DRAWER_WIDTH = 360
const MAX_DRAWER_WIDTH = 960
const MOBILE_BREAKPOINT = 600

const props = defineProps({
  open: Boolean,
  sessionId: { type: String, default: '' },
  pcapName: { type: String, default: '' },
})

const emit = defineEmits(['update:open'])

const status = ref({ configured: false, api_base: '', model: '', source: 'none' })
const statusLoading = ref(false)
const configOpen = ref(false)
const configSaving = ref(false)
const configError = ref('')
const configForm = ref({ api_key: '', api_base: '', model: '' })

const messages = ref([])
const conversationId = ref(null)
const draft = ref('')
const sending = ref(false)
const chatError = ref('')
const messageList = ref(null)
const drawerWidth = ref(DEFAULT_DRAWER_WIDTH)
const resizing = ref(false)
let resizeStartX = 0
let resizeStartWidth = DEFAULT_DRAWER_WIDTH

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
watch(() => props.sessionId, () => {
  messages.value = []
  conversationId.value = null
  draft.value = ''
  chatError.value = ''
})

onMounted(() => {
  refreshStatus()
  window.addEventListener('resize', clampDrawerWidth)
})

onUnmounted(() => {
  stopResize()
  window.removeEventListener('resize', clampDrawerWidth)
})

async function refreshStatus() {
  statusLoading.value = true
  try {
    const next = await fetchAssistantStatus()
    applyStatus(next)
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
}

async function saveConfig() {
  configSaving.value = true
  configError.value = ''
  try {
    const next = await configureAssistant({
      api_key: configForm.value.api_key || null,
      api_base: configForm.value.api_base.trim(),
      model: configForm.value.model.trim(),
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

async function submitQuestion(value = draft.value) {
  const question = String(value || '').trim()
  if (!question || sending.value || !props.sessionId || !status.value.configured) return

  messages.value.push({ role: 'user', content: question })
  draft.value = ''
  sending.value = true
  chatError.value = ''
  await scrollToLatest()

  try {
    const result = await askAssistant(props.sessionId, question, conversationId.value)
    conversationId.value = result.conversation_id
    messages.value.push({
      role: 'assistant',
      content: result.answer,
      renderedContent: renderMarkdown(result.answer),
      tools: result.tools || [],
      model: result.model,
    })
  } catch (error) {
    chatError.value = apiError(error, '问答请求失败')
  } finally {
    sending.value = false
    await scrollToLatest()
  }
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
  return Math.max(MIN_DRAWER_WIDTH, Math.min(MAX_DRAWER_WIDTH, window.innerWidth - 72))
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
  <Teleport to="body">
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
            <p>{{ status.model || '尚未配置模型' }}</p>
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
          <small v-if="sessionId" class="mono">{{ sessionId }}</small>
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
              当前预设 DeepSeek。不同服务商的 API Key 不通用，切换服务商时需同时修改以下三项。
            </p>
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
            <p v-if="configError" class="config-error" role="alert">{{ configError }}</p>
            <button class="config-save" type="submit" :disabled="configSaving || statusLoading">
              {{ configSaving ? '保存中...' : '应用配置' }}
            </button>
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
            ></div>
            <div v-else class="message-content user-content">{{ message.content }}</div>
            <footer v-if="message.tools?.length">
              调用工具：{{ message.tools.map(tool => tool.name).join(', ') }}
            </footer>
          </article>

          <article v-if="sending" class="chat-message is-assistant is-loading" aria-label="AI 正在分析">
            <span class="message-role">AI 助手</span>
            <div class="loading-lines"><i></i><i></i><i></i></div>
          </article>

          <p v-if="chatError" class="chat-error" role="alert">{{ chatError }}</p>
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
            <button type="submit" :disabled="!draft.trim() || sending || !sessionId || !status.configured">
              发送
            </button>
          </div>
        </form>
      </aside>
    </Transition>
  </Teleport>
</template>

<style>
.assistant-drawer {
  position: fixed;
  inset: 0 0 0 auto;
  z-index: 115;
  width: min(440px, 100vw);
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  border-left: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text-primary);
  box-shadow: -18px 0 44px rgba(30, 38, 50, .18);
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
  box-shadow: -18px 0 48px rgba(0, 0, 0, .38);
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
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: baseline;
  gap: 3px 10px;
  padding: 10px 16px;
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
  grid-column: 2;
  color: var(--text-tertiary);
  font-size: 10px;
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
.config-form input {
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
.config-form input:focus {
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}
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
.is-loading { width: 62%; }
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
  padding: 9px 10px;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-control);
  background: var(--danger-soft);
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
@media (max-width: 600px) {
  .assistant-drawer { width: 100vw !important; }
  .assistant-resize-handle { display: none; }
  .assistant-header { padding-left: 12px; }
  .assistant-messages { padding: 12px; }
}
</style>
