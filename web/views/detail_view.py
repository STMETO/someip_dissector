from __future__ import annotations


def render_detail_view() -> str:
    return """
<section class="pane pane-right">
  <div class="pane-header">
    <span>Packet Details</span>
    <span class="pane-header-meta" x-text="selectedHeaderLabel()"></span>
  </div>
  <div class="detail-wrap">
    <template x-if="selectedMessage()">
      <div class="detail-shell">
        <div class="detail-summary">
          <div class="detail-summary-grid">
            <div><span>Service</span><strong x-text="selectedMessage().header.service_id.hex"></strong></div>
            <div><span>Method/Event</span><strong x-text="selectedMessage().header.method_id.hex"></strong></div>
            <div><span>Payload</span><strong x-text="selectedMessage().payload_length + ' bytes'"></strong></div>
            <div><span>Status</span><strong x-text="statusLabel(selectedMessage().parse_status)"></strong></div>
          </div>
        </div>
        <div class="tree-scroll" x-html="renderSelectedTree()"></div>
      </div>
    </template>
    <template x-if="!selectedMessage()">
      <div class="empty-detail">
        <div>右侧显示当前报文的 FieldNode 解析树。</div>
        <div>表格选中某一行后，可逐级展开结构体、数组和基础字段。</div>
      </div>
    </template>
  </div>
</section>
"""
