from __future__ import annotations


def render_message_list_view() -> str:
    return """
<section class="pane pane-left">
  <div class="pane-header">
    <span>Packet List</span>
    <span class="pane-header-meta" x-text="summaryLabel()"></span>
  </div>
  <div class="table-wrap">
    <table class="packet-table">
      <thead>
        <tr>
          <th>序号</th>
          <th>Service ID</th>
          <th>Method/Event ID</th>
          <th>类型</th>
          <th>Payload 长度</th>
          <th>解析状态</th>
        </tr>
      </thead>
      <tbody>
        <template x-if="!messages.length && !isSubmitting">
          <tr>
            <td colspan="6" class="empty-state">上传并解析文件后，这里显示 SOME/IP 报文摘要。</td>
          </tr>
        </template>
        <template x-if="isSubmitting">
          <tr>
            <td colspan="6" class="empty-state">正在执行 ARXML 构建、PCAP 解析与 payload 反序列化...</td>
          </tr>
        </template>
        <template x-for="message in messages" :key="message.index">
          <tr x-bind:class="rowClass(message)" x-on:click="selectMessage(message.index)">
            <td x-text="message.index"></td>
            <td x-text="message.header.service_id.hex"></td>
            <td x-text="message.header.method_id.hex"></td>
            <td>
              <div class="cell-primary" x-text="message.message_kind"></div>
              <div class="cell-secondary" x-text="message.transport"></div>
            </td>
            <td x-text="message.payload_length"></td>
            <td>
              <span class="status-badge" x-bind:class="statusClass(message.parse_status)" x-text="statusLabel(message.parse_status)"></span>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</section>
"""
