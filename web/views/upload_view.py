from __future__ import annotations


def render_upload_view() -> str:
    return """
<header class="toolbar">
  <div class="toolbar-title">
    <div class="app-name">SOME/IP Dissector</div>
    <div class="app-subtitle">Wireshark 风格报文视图</div>
  </div>
  <form class="upload-panel" x-on:submit.prevent="submitAnalysis()">
    <div class="dropzone"
         x-bind:class="{ 'is-dragover': dragOver }"
         x-on:dragover.prevent="dragOver = true"
         x-on:dragleave.prevent="dragOver = false"
         x-on:drop.prevent="handleDrop($event)">
      <div class="dropzone-title">拖拽 pcap / arxml 到这里，或手动选择</div>
      <div class="dropzone-meta">支持同时上传抓包与配置文件；按扩展名自动归类</div>
    </div>

    <div class="file-pickers">
      <label class="picker">
        <span>PCAP 抓包</span>
        <input type="file" accept=".pcap,.pcapng,.cap" x-on:change="assignFile('pcap', $event)">
        <strong x-text="form.pcap ? form.pcap.name : '未选择文件'"></strong>
      </label>
      <label class="picker">
        <span>ARXML 配置</span>
        <input type="file" accept=".arxml,.xml" x-on:change="assignFile('arxml', $event)">
        <strong x-text="form.arxml ? form.arxml.name : '未选择文件'"></strong>
      </label>
      <label class="checkbox-row">
        <input type="checkbox" x-model="form.keepIntermediate">
        <span>保留中间 JSON 产物</span>
      </label>
      <button class="analyze-button" type="submit" x-bind:disabled="isSubmitting || !canSubmit()">
        <span x-show="!isSubmitting">开始解析</span>
        <span x-show="isSubmitting">解析中...</span>
      </button>
    </div>

    <div class="status-row">
      <span class="status-pill" x-show="summary.totalMessages">
        报文 <strong x-text="summary.totalMessages"></strong>
      </span>
      <span class="status-pill" x-show="summary.deserialized">
        成功 <strong x-text="summary.deserialized"></strong>
      </span>
      <a class="status-pill download-link" x-show="exportUrl" x-bind:href="exportUrl">下载完整 JSON</a>
      <span class="error-text" x-text="errorMessage" x-show="errorMessage"></span>
    </div>
  </form>
</header>
"""
