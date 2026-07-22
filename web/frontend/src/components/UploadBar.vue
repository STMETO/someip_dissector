<script setup>
import { ref, computed, watch } from 'vue'
import { uploadFiles, exportUrl } from '../api'

const emit = defineEmits(['parsed', 'update:uploading'])
const props = defineProps({ loading: Boolean, sessionId: String, hasExport: Boolean })

const pcapFile = ref(null)
const arxmlFile = ref(null)
const keepTemp = ref(false)
const submitting = ref(false)
const dragOver = ref(false)

watch(submitting, (val) => emit('update:uploading', val))

const canSubmit = computed(() => pcapFile.value && arxmlFile.value && !props.loading && !submitting.value)

function handlePcap(e) { pcapFile.value = e.target.files[0] || null }
function handleArxml(e) { arxmlFile.value = e.target.files[0] || null }

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const res = await uploadFiles(pcapFile.value, arxmlFile.value, keepTemp.value)
    emit('parsed', res)
  } catch (e) {
    alert('解析失败: ' + (e.response?.data?.detail || e.message))
  } finally { submitting.value = false }
}

function onDrop(e) {
  dragOver.value = false
  const files = e.dataTransfer?.files || []
  for (const f of files) {
    const name = f.name.toLowerCase()
    if (name.endsWith('.pcap') || name.endsWith('.pcapng') || name.endsWith('.cap'))
      pcapFile.value = f
    else if (name.endsWith('.arxml') || name.endsWith('.xml'))
      arxmlFile.value = f
  }
}
</script>

<template>
  <header class="toolbar"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
          :class="{ 'toolbar-dragover': dragOver }">
    <div class="toolbar-top">
      <div class="brand-block">
        <span class="brand">SOME/IP Dissector</span>
        <span class="brand-subtitle">PCAP / ARXML protocol analysis workbench</span>
      </div>
      <div class="toolbar-actions">
        <label class="pick-btn" :class="{ active: pcapFile }">
          {{ pcapFile ? pcapFile.name : '选择 PCAP' }}
          <input type="file" accept=".pcap,.pcapng,.cap" @change="handlePcap">
        </label>
        <label class="pick-btn" :class="{ active: arxmlFile }">
          {{ arxmlFile ? arxmlFile.name : '选择 ARXML' }}
          <input type="file" accept=".arxml,.xml" @change="handleArxml">
        </label>
        <label class="check-label"><input type="checkbox" v-model="keepTemp"> 保留中间JSON</label>
        <button class="btn-go" :disabled="!canSubmit" @click="submit">
          {{ submitting ? '解析中...' : '开始解析' }}
        </button>
        <template v-if="sessionId">
          <a v-if="hasExport" :href="exportUrl(sessionId, 'pcap_output.json')" class="lnk">PCAP JSON</a>
          <a v-if="hasExport" :href="exportUrl(sessionId, 'arxml_output.json')" class="lnk">ARXML JSON</a>
          <a v-if="hasExport" :href="exportUrl(sessionId, 'deserialized_output.json')" class="lnk">反序列化 JSON</a>
        </template>
      </div>
    </div>
    <div class="toolbar-hint" v-if="!sessionId">
      拖拽 pcap + arxml 文件到此处，或点击按钮选择文件。建议先上传同一版本的协议定义与抓包，避免类型未注册。
    </div>
  </header>
</template>

<style>
.toolbar {
  flex-shrink: 0;
  background: rgba(8, 13, 24, .94);
  border-bottom: 1px solid rgba(148, 163, 184, .24);
  padding: 13px 18px 11px;
  user-select: none;
  box-shadow: 0 12px 28px rgba(0, 0, 0, .26);
}
.toolbar-dragover {
  background: #10233d;
  outline: 2px solid #38bdf8;
  outline-offset: -2px;
}
.toolbar-top {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  justify-content: space-between;
}
.brand-block { display: flex; flex-direction: column; gap: 2px; }
.brand {
  font-size: 19px;
  font-weight: 900;
  color: #f8fafc;
  letter-spacing: 0;
}
.brand-subtitle {
  font-size: 12px;
  color: #93a4ba;
  font-weight: 650;
}
.toolbar-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pick-btn {
  position: relative;
  max-width: 220px;
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  padding: 0 12px;
  border: 1px solid #334155;
  border-radius: 5px;
  cursor: pointer;
  font-size: 13px;
  color: #cbd5e1;
  background: #111827;
  transition: border-color .15s, background .15s, color .15s;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pick-btn:hover { border-color: #38bdf8; color: #ffffff; background: #17233a; }
.pick-btn.active { border-color: #38bdf8; color: #e0f2fe; background: #082f49; }
.pick-btn input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.check-label {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #cbd5e1;
  cursor: pointer;
}
.check-label input { width: 14px; height: 14px; accent-color: #38bdf8; }
.btn-go {
  min-height: 34px;
  padding: 0 18px;
  background: #0284c7;
  color: #ffffff;
  border: 1px solid #38bdf8;
  border-radius: 5px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 900;
  box-shadow: 0 8px 18px rgba(2, 132, 199, .28);
}
.btn-go:hover:not(:disabled) { background: #0369a1; }
.btn-go:disabled {
  background: #334155;
  border-color: #475569;
  color: #94a3b8;
  cursor: not-allowed;
  box-shadow: none;
}
.lnk {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  color: #bae6fd;
  text-decoration: none;
  padding: 0 9px;
  border-radius: 5px;
  background: #082f49;
  border: 1px solid #075985;
  font-weight: 800;
}
.lnk:hover { background: #0c4a6e; }
.toolbar-hint {
  margin-top: 9px;
  font-size: 12px;
  color: #93a4ba;
}
@media (max-width: 900px) {
  .toolbar-top { justify-content: flex-start; }
  .toolbar-actions { width: 100%; }
  .pick-btn { max-width: 100%; }
}
</style>
