function createDissectorState() {
  return {
    dragOver: false,
    isSubmitting: false,
    errorMessage: "",
    exportUrl: "",
    selectedIndex: null,
    messages: [],
    summary: {
      totalMessages: 0,
      deserialized: 0,
      missed: 0,
      typePoolSize: 0,
      methodCount: 0,
      eventCount: 0,
    },
    form: {
      pcap: null,
      arxml: null,
      keepIntermediate: false,
    },

    canSubmit() {
      return Boolean(this.form.pcap && this.form.arxml);
    },

    assignFile(kind, event) {
      const [file] = event.target.files || [];
      if (!file) {
        return;
      }
      this.form[kind] = file;
      this.maybeAutoSubmit();
    },

    handleDrop(event) {
      this.dragOver = false;
      for (const file of event.dataTransfer.files) {
        const lower = file.name.toLowerCase();
        if (lower.endsWith(".pcap") || lower.endsWith(".pcapng") || lower.endsWith(".cap")) {
          this.form.pcap = file;
        } else if (lower.endsWith(".arxml") || lower.endsWith(".xml")) {
          this.form.arxml = file;
        }
      }
      this.maybeAutoSubmit();
    },

    maybeAutoSubmit() {
      if (this.canSubmit() && !this.isSubmitting) {
        this.submitAnalysis();
      }
    },

    async submitAnalysis() {
      if (!this.canSubmit() || this.isSubmitting) {
        return;
      }

      this.isSubmitting = true;
      this.errorMessage = "";
      this.exportUrl = "";

      const body = new FormData();
      body.append("pcap_file", this.form.pcap);
      body.append("arxml_file", this.form.arxml);
      body.append("keep_intermediate", this.form.keepIntermediate ? "true" : "false");

      try {
        const response = await fetch("/api/analyze", {
          method: "POST",
          body,
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "解析失败");
        }
        this.messages = payload.messages || [];
        this.summary = {
          totalMessages: payload.summary?.total_messages || 0,
          deserialized: payload.summary?.deserialized || 0,
          missed: payload.summary?.missed || 0,
          typePoolSize: payload.summary?.type_pool_size || 0,
          methodCount: payload.summary?.registry?.methods || 0,
          eventCount: payload.summary?.registry?.events || 0,
        };
        this.exportUrl = payload.export_url || "";
        this.selectedIndex = this.messages.length ? this.messages[0].index : null;
      } catch (error) {
        this.messages = [];
        this.selectedIndex = null;
        this.summary = {
          totalMessages: 0,
          deserialized: 0,
          missed: 0,
          typePoolSize: 0,
          methodCount: 0,
          eventCount: 0,
        };
        this.errorMessage = error instanceof Error ? error.message : "未知错误";
      } finally {
        this.isSubmitting = false;
      }
    },

    selectMessage(index) {
      this.selectedIndex = index;
    },

    selectedMessage() {
      return this.messages.find((message) => message.index === this.selectedIndex) || null;
    },

    summaryLabel() {
      if (!this.summary.totalMessages) {
        return "等待分析结果";
      }
      return `${this.summary.totalMessages} packets | ${this.summary.deserialized} resolved | ${this.summary.typePoolSize} types`;
    },

    selectedHeaderLabel() {
      const message = this.selectedMessage();
      if (!message) {
        return "未选择报文";
      }
      return `Frame ${message.frame_index} | ${message.message_kind} | ${message.transport}`;
    },

    rowClass(message) {
      return {
        "is-selected": message.index === this.selectedIndex,
        "is-unresolved": message.parse_status !== "ok",
      };
    },

    statusClass(status) {
      return {
        "is-ok": status === "ok",
        "is-unresolved": status !== "ok",
      };
    },

    statusLabel(status) {
      return status === "ok" ? "已解析" : "未匹配";
    },

    renderSelectedTree() {
      const message = this.selectedMessage();
      if (!message || !message.parsed) {
        return '<div class="empty-detail">当前报文没有匹配到可反序列化的 ARXML 类型。</div>';
      }
      return this.renderNode(message.parsed, 0);
    },

    renderNode(node, depth) {
      const children = Array.isArray(node.children) ? node.children : [];
      const value = node.value === undefined || node.value === null ? "-" : this.escapeHtml(String(node.value));
      const summaryMeta = [
        `type ${this.escapeHtml(node.type || "-")}`,
        `offset ${Number(node.offset || 0)}`,
        `size ${Number(node.byte_size || 0)} B`,
        `hex ${this.escapeHtml(this.formatHex(node.hex || "")) || "-"}`,
      ].join(" | ");

      const childHtml = children.map((child) => this.renderNode(child, depth + 1)).join("");
      const open = depth < 2 ? " open" : "";

      return `
        <div class="tree-node" style="--depth:${depth}">
          <details class="tree-details"${open}>
            <summary class="tree-summary">
              <span class="tree-name">${this.escapeHtml(node.name || "unnamed")}</span>
              <span class="tree-inline">${summaryMeta}</span>
            </summary>
            <div class="tree-body">
              <div class="tree-grid">
                <span>字段名称</span><strong>${this.escapeHtml(node.name || "unnamed")}</strong>
                <span>解析值</span><strong>${value}</strong>
                <span>数据类型</span><strong>${this.escapeHtml(node.type || "-")}</strong>
                <span>起始偏移</span><strong>${Number(node.offset || 0)}</strong>
                <span>字节长度</span><strong>${Number(node.byte_size || 0)}</strong>
                <span>原始十六进制</span><strong class="hex-block">${this.escapeHtml(this.formatHex(node.hex || "")) || "-"}</strong>
              </div>
              ${childHtml ? `<div class="tree-children">${childHtml}</div>` : ""}
            </div>
          </details>
        </div>`;
    },

    formatHex(hex) {
      if (!hex) {
        return "";
      }
      return hex.match(/.{1,2}/g)?.join(" ") || hex;
    },

    escapeHtml(value) {
      return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    },
  };
}

function registerDissectorApp() {
  if (!window.Alpine) {
    return;
  }
  window.Alpine.data("dissectorApp", createDissectorState);
}

if (window.Alpine) {
  registerDissectorApp();
} else {
  document.addEventListener("alpine:init", registerDissectorApp, { once: true });
}
