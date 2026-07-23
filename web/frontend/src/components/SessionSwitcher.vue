<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: String,
  loading: Boolean,
  busyIds: { type: Array, default: () => [] },
})
const emit = defineEmits(['select', 'delete', 'persist', 'unpersist', 'refresh'])

const open = ref(false)
const query = ref('')

const activeSession = computed(() =>
  props.sessions.find(item => item.session_id === props.activeId)
)

const filteredSessions = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.sessions
  return props.sessions.filter(item => [
    item.session_id,
    item.pcap_name,
    item.arxml_name,
    item.persistent ? 'saved' : 'local',
  ].some(value => String(value || '').toLowerCase().includes(q)))
})

function formatTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function shortName(name, fallback) {
  return name || fallback
}

function isBusy(sessionId) {
  return props.busyIds.includes(sessionId)
}

function select(item) {
  emit('select', item)
  open.value = false
}
</script>

<template>
  <div class="session-switcher">
    <button
      class="session-menu-btn"
      type="button"
      :aria-expanded="open"
      aria-controls="session-modal"
      @click="open = true"
    >
      <span>解析记录</span>
      <strong>{{ sessions.length }}</strong>
    </button>

    <Teleport to="body">
      <div v-if="open" class="session-modal-layer" role="presentation">
        <button
          class="modal-backdrop"
          type="button"
          aria-label="Close parse records"
          @click="open = false"
        ></button>

        <section id="session-modal" class="session-modal" role="dialog" aria-modal="true" aria-label="Parse records">
          <header class="modal-head">
            <div>
              <strong>解析记录</strong>
              <span v-if="activeSession">
                Current: {{ shortName(activeSession.pcap_name, activeSession.session_id) }}
              </span>
              <span v-else>{{ sessions.length }} groups</span>
            </div>
            <div class="modal-actions">
              <button type="button" :disabled="loading" @click="emit('refresh')">Refresh</button>
              <button type="button" @click="open = false">Close</button>
            </div>
          </header>

          <div class="session-controls">
            <label class="session-search">
              <span>Filter</span>
              <input v-model="query" placeholder="pcap / arxml / id">
            </label>
            <div class="session-count">
              <strong>{{ filteredSessions.length }}</strong>
              <span>shown</span>
            </div>
          </div>

          <div class="session-list" v-if="filteredSessions.length">
            <article
              v-for="item in filteredSessions"
              :key="item.session_id"
              class="session-item"
              :class="{ active: item.session_id === activeId }"
            >
              <button class="session-select" type="button" @click="select(item)">
                <span class="file-pair">
                  <strong :title="item.pcap_name">{{ shortName(item.pcap_name, 'capture') }}</strong>
                  <small :title="item.arxml_name">{{ shortName(item.arxml_name, 'schema') }}</small>
                </span>
                <span class="session-facts">
                  <span :class="['state-chip', item.persistent ? 'saved' : 'local']">
                    {{ item.persistent ? 'saved' : 'local' }}
                  </span>
                  <span class="mono">{{ item.summary?.total_messages || 0 }} msg</span>
                  <span class="mono">{{ item.summary?.parsed_count || 0 }} parsed</span>
                  <span>{{ formatTime(item.created_at) }}</span>
                </span>
                <span class="session-id mono">{{ item.session_id }}</span>
              </button>

              <div class="session-row-actions">
                <button
                  v-if="!item.persistent"
                  type="button"
                  class="save-btn"
                  :disabled="isBusy(item.session_id)"
                  @click.stop="emit('persist', item.session_id)"
                >
                  {{ isBusy(item.session_id) ? 'Saving' : 'Save' }}
                </button>
                <button
                  v-if="item.persistent"
                  type="button"
                  class="unsave-btn"
                  title="Stop saving this record after the current UI closes"
                  :disabled="isBusy(item.session_id)"
                  @click.stop="emit('unpersist', item.session_id)"
                >
                  {{ isBusy(item.session_id) ? 'Saving' : 'Unsave' }}
                </button>
                <button
                  v-else
                  type="button"
                  class="delete-btn"
                  :disabled="isBusy(item.session_id)"
                  @click.stop="emit('delete', item)"
                >
                  Delete
                </button>
              </div>
            </article>
          </div>

          <div class="session-empty" v-else>
            No parse records.
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.session-switcher {
  display: inline-flex;
  align-items: center;
}
.session-menu-btn {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px 0 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface-subtle);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  font-weight: 850;
}
.session-menu-btn:hover {
  border-color: var(--accent-border);
  background: var(--surface-hover);
  color: var(--text-primary);
}
.session-menu-btn strong {
  min-width: 22px;
  min-height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--accent-border);
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 900;
}
.session-modal-layer {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  padding: 20px;
}
.modal-backdrop {
  position: absolute;
  inset: 0;
  border: 0;
  background: rgba(10, 12, 16, .32);
}
.session-modal {
  position: relative;
  z-index: 1;
  width: min(780px, calc(100vw - 32px));
  max-height: min(620px, calc(100vh - 40px));
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-panel);
  background: var(--surface);
  box-shadow: var(--shadow-popover);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-raised);
}
.modal-head strong {
  display: block;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 900;
}
.modal-head span {
  display: block;
  margin-top: 3px;
  max-width: 54ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 750;
}
.modal-actions {
  display: flex;
  flex-shrink: 0;
  gap: 6px;
}
.modal-actions button,
.session-row-actions button {
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}
.modal-actions button:hover:not(:disabled),
.session-row-actions button:hover {
  border-color: var(--accent-border);
  color: var(--accent);
  background: var(--accent-soft);
}
.modal-actions button:disabled {
  opacity: .5;
  cursor: not-allowed;
}
.session-row-actions button:disabled {
  opacity: .55;
  cursor: wait;
}
.session-controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 12px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
}
.session-search {
  min-width: 0;
  display: grid;
  gap: 5px;
}
.session-search span,
.session-count span {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 800;
}
.session-search input {
  width: 100%;
  height: 32px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--text-primary);
  outline: none;
  font-size: 12px;
}
.session-search input:focus {
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}
.session-count {
  min-width: 70px;
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface);
}
.session-count strong {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 900;
}
.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 9px;
}
.session-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: stretch;
  margin-bottom: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface);
  overflow: hidden;
}
.session-item.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  box-shadow: inset 3px 0 0 var(--accent);
}
.session-select {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(180px, 1.2fr) minmax(190px, .9fr) minmax(120px, .7fr);
  align-items: center;
  gap: 10px;
  padding: 10px 12px 10px 14px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.session-select:hover {
  background: var(--surface-hover);
}
.file-pair {
  min-width: 0;
  display: grid;
  gap: 3px;
}
.file-pair strong,
.file-pair small,
.session-id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-pair strong {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 900;
}
.file-pair small {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 700;
}
.session-facts {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 11px;
}
.session-facts span {
  min-height: 20px;
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface-subtle);
}
.state-chip.saved {
  color: var(--success);
  border-color: var(--success-border);
  background: var(--success-soft);
}
.state-chip.local {
  color: var(--text-secondary);
}
.session-id {
  color: var(--text-tertiary);
  font-size: 10px;
}
.session-row-actions {
  min-width: 122px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  padding: 0 10px;
  border-left: 1px solid var(--border);
  background: var(--surface-subtle);
}
.session-row-actions .save-btn {
  color: var(--success);
  border-color: var(--success-border);
  background: var(--success-soft);
}
.session-row-actions .unsave-btn {
  color: var(--warning);
  border-color: var(--warning-border);
  background: var(--warning-soft);
}
.session-row-actions .delete-btn:hover {
  border-color: var(--danger-border);
  background: var(--danger-soft);
  color: var(--danger);
}
.session-empty {
  padding: 34px 12px;
  color: var(--text-tertiary);
  text-align: center;
  font-size: 12px;
}
@media (max-width: 820px) {
  .session-modal {
    width: calc(100vw - 20px);
  }
  .session-item {
    grid-template-columns: 1fr;
  }
  .session-select {
    grid-template-columns: 1fr;
  }
  .session-row-actions {
    min-height: 40px;
    border-left: 0;
    border-top: 1px solid var(--border);
  }
}
</style>
