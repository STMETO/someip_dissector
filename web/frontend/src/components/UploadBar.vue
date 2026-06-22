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
          <a v-if="hasExport" :href="exportUrl(sessionId, 'pcap_output.json')" class="lnk">↓ PCAP JSON</a>
          <a v-if="hasExport" :href="exportUrl(sessionId, 'arxml_output.json')" class="lnk">↓ ARXML JSON</a>
          <a v-if="hasExport" :href="exportUrl(sessionId, 'deserialized_output.json')" class="lnk">↓ 反序列化 JSON</a>
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
  flex-shrink: 0; background: linear-gradient(180deg, #f8fbff 0%, #eef3f9 100%);
  border-bottom: 1px solid #d8e0ea; padding: 14px 18px 12px; user-select: none;
  box-shadow: 0 6px 18px rgba(31, 45, 61, 0.06);
}
.toolbar-dragover { background: linear-gradient(180deg, #eef7ff 0%, #e1efff 100%); }
.toolbar-top {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  justify-content: space-between;
}
.brand-block { display: flex; flex-direction: column; gap: 4px; }
.brand { font-size: 20px; font-weight: 800; color: #223246; letter-spacing: 0.02em; }
.toolbar-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pick-btn {
  position: relative; padding: 9px 16px; border: 1px dashed #b9c7da;
  border-radius: 8px; cursor: pointer; font-size: 13px; color: #606266;
  background: rgba(255,255,255,0.9); transition: border-color .2s, transform .2s;
}
.pick-btn:hover { border-color: #409eff; transform: translateY(-1px); }
.pick-btn.active { border-style: solid; border-color: #409eff; color: #303133; background: #eef6ff; }
.pick-btn input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.check-label { font-size: 13px; display: flex; align-items: center; gap: 4px; cursor: pointer; }
.btn-go {
  padding: 9px 22px; background: linear-gradient(180deg, #56a9ff, #2f80ed); color: #fff; border: none;
  border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; box-shadow: 0 8px 18px rgba(47, 128, 237, 0.22);
}
.btn-go:disabled { background: #a0cfff; cursor: not-allowed; }
.lnk {
  font-size: 12px; color: #2f80ed; text-decoration: none; margin-left: 4px;
  padding: 6px 10px; border-radius: 7px; background: rgba(47, 128, 237, 0.08);
}
.toolbar-hint {
  margin-top: 10px; font-size: 12px; color: #7b8794;
}
@media (max-width: 900px) {
  .toolbar-top { justify-content: flex-start; }
}
</style>
