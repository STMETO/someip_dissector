<script>
import { computed, h, ref } from 'vue'

export default {
  name: 'ParseTree',
  props: { message: Object },
  setup(props) {
    return () => {
      if (!props.message) {
        return h('div', { class: 'tree-empty' }, [
          h('div', { class: 'tree-empty-mark' }, 'SOME/IP'),
          h('div', { class: 'tree-empty-title' }, 'Select a packet'),
          h('div', { class: 'tree-empty-subtitle' }, 'Raw protocol fields and decoded payload will appear here.'),
        ])
      }

      const msg = props.message
      const statusChip = _statusChip(msg.parse_status)
      const sections = []

      if (msg.raw_view) {
        sections.push(h(TreeSection, {
          title: 'Raw Protocol Tree',
          subtitle: 'SOME/IP header, service discovery, payload bytes',
          node: msg.raw_view,
          tone: 'raw',
          key: 'raw-root',
        }))
      }

      if (msg.parsed && msg.parse_status === 'ok') {
        sections.push(h(TreeSection, {
          title: 'Decoded Payload',
          subtitle: 'Payload deserialized with ARXML type definitions',
          node: msg.parsed,
          tone: 'decoded',
          key: 'parsed-root',
        }))
      }

      return h('div', { class: 'tree-panel' }, [
        h('header', { class: 'tree-header' }, [
          h('div', { class: 'packet-title' }, [
            h('span', { class: 'packet-id mono' }, `${msg.service_id} / ${msg.method_id}`),
            h('span', { class: 'packet-kind' }, msg.message_kind || 'SOME/IP'),
          ]),
          h('div', { class: 'packet-facts' }, [
            h('span', { class: 'fact' }, msg.message_type_name || msg.message_type || '-'),
            h('span', { class: 'fact', title: msg.timestamp_iso || '' }, _formatTimestamp(msg.timestamp_epoch)),
            h('span', { class: 'fact' }, msg.transport || '-'),
            h('span', { class: 'fact' }, `${msg.payload_length || 0}B payload`),
            statusChip ? h('span', { class: `fact ${statusChip.cls}` }, statusChip.label) : null,
          ]),
        ]),
        h('div', { class: 'tree-scroll' }, sections),
      ])
    }
  },
}

const TreeSection = {
  name: 'TreeSection',
  props: { title: String, subtitle: String, node: Object, tone: String },
  setup(props) {
    return () => h('section', { class: ['tree-section', `tone-${props.tone || 'raw'}`] }, [
      h('header', { class: 'section-head' }, [
        h('div', null, [
          h('div', { class: 'section-title' }, props.title),
          h('div', { class: 'section-subtitle' }, props.subtitle),
        ]),
        h('span', { class: 'section-size' }, `${props.node?.byte_size || 0} bytes`),
      ]),
      h(TreeNode, { node: props.node, depth: 0 }),
    ])
  },
}

const TreeNode = {
  name: 'TreeNode',
  props: { node: Object, depth: { type: Number, default: 0 } },
  setup(props) {
    const open = ref(props.depth <= 1)
    const children = computed(() => props.node?.children || [])
    const hasKids = computed(() => children.value.length > 0)
    // 父级容器负责层级差，行内保留统一起点，让分支和叶子在同层对齐。
    const rowStyle = { paddingLeft: '8px' }

    return () => {
      if (hasKids.value) {
        const meta = props.node.meta_kind || ''
        return h('div', { class: 'tn' }, [
          h('div', { class: ['branch-row', open.value ? 'is-open' : ''], style: rowStyle }, [
            h('button', {
              class: 'branch-toggle',
              type: 'button',
              title: open.value ? 'Collapse' : 'Expand',
              onClick: () => { open.value = !open.value },
            }, open.value ? '-' : '+'),
            h('div', { class: 'branch-main' }, [
              h('span', { class: 'branch-name', title: props.node.name }, props.node.name),
              h('span', {
                class: 'branch-type',
                title: props.node.type || 'container',
              }, props.node.type || 'container'),
              meta ? h('span', { class: `node-badge node-badge-${meta}` }, _metaLabel(meta)) : null,
            ]),
            h('span', {
              class: 'branch-meta',
              title: `${props.node.byte_size || 0}B @ ${props.node.offset || 0}`,
            }, `${props.node.byte_size || 0}B @ ${props.node.offset || 0}`),
          ]),
          open.value ? h('div', { class: 'branch-children' }, children.value.map((child, idx) => h(TreeNode, {
            node: child,
            depth: props.depth + 1,
            key: `${child.name}-${child.offset}-${idx}`,
          }))) : null,
        ])
      }

      const value = _valueParts(props.node)
      const showLocation = props.node.show_location !== false
      const renderedValue = value.kind === 'numeric'
        ? [
            h('div', { class: 'value-slot' }, [
              h('span', {
                class: 'value-chip hex-chip',
                title: `hex ${value.hex}`,
              }, [
                'hex ', h('strong', null, value.hex),
              ]),
            ]),
            h('div', { class: 'value-slot' }, [
              h('span', {
                class: 'value-chip dec-chip',
                title: `dec ${value.dec}`,
              }, [
                'dec ', h('strong', null, value.dec),
              ]),
            ]),
            value.meaning ? h('div', { class: 'value-slot meaning-slot' }, [
              h('span', { class: 'leaf-meaning', title: value.meaning }, [
                h('span', { class: 'meta-label' }, 'meaning'),
                h('span', { class: 'meaning-text' }, value.meaning),
              ]),
            ]) : null,
          ]
        : h('span', { class: 'plain-value', title: value.text }, value.text)
      return h('div', { class: 'tn leaf-row', style: rowStyle }, [
        h('div', { class: 'leaf-key', title: props.node.name }, props.node.name),
        h('div', { class: 'leaf-body' }, [
          h('div', {
            class: ['leaf-value', value.meaning ? 'has-meaning' : ''],
          }, renderedValue),
        ]),
        showLocation ? h('div', {
          class: 'leaf-meta',
          title: `len ${props.node.byte_size || 0}B, offset ${props.node.offset || 0}B`,
        }, [
          h('span', null, ['len ', h('strong', null, `${props.node.byte_size || 0}B`)]),
          h('span', null, ['offset ', h('strong', null, `${props.node.offset || 0}B`)]),
        ]) : null,
      ])
    }
  },
}

function _valueParts(node) {
  const value = node.value
  if (_isHexDecValue(value)) {
    return {
      kind: 'numeric',
      hex: value.hex || '',
      dec: String(value.dec ?? 0),
      meaning: value.meaning || '',
    }
  }
  return {
    kind: 'plain',
    text: _formatVal(value),
  }
}

function _isHexDecValue(value) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.prototype.hasOwnProperty.call(value, 'hex')
    && Object.prototype.hasOwnProperty.call(value, 'dec')
}

function _formatVal(value) {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function _formatTimestamp(epoch) {
  const n = Number(epoch)
  if (!Number.isFinite(n) || n <= 0) return '-'
  const d = new Date(n * 1000)
  const pad = (v, len = 2) => String(v).padStart(len, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

function _statusChip(st) {
  if (st === 'sd') return { label: 'SOME/IP-SD', cls: 'status-sd' }
  if (st === 'unresolved') return { label: 'Unresolved', cls: 'status-unresolved' }
  if (st === 'ok') return { label: 'Decoded', cls: 'status-ok' }
  return null
}

function _metaLabel(meta) {
  if (meta === 'raw') return 'RAW'
  if (meta === 'sd') return 'SD'
  if (meta === 'unresolved') return 'UNRESOLVED'
  return meta.toUpperCase()
}
</script>

<style>
.tree-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface);
  color: var(--text-primary);
}
.tree-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  background: var(--surface-raised);
  border-bottom: 1px solid var(--border);
}
.packet-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.packet-id { font-size: 15px; font-weight: 850; color: var(--text-primary); }
.packet-kind {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  border-radius: var(--radius-control);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
}
.packet-facts { display: flex; gap: 5px; flex-wrap: wrap; justify-content: flex-end; }
.fact {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 750;
  background: var(--surface-subtle);
}
.status-ok { color: var(--success); border-color: var(--success-border); background: var(--success-soft); }
.status-sd { color: var(--warning); border-color: var(--warning-border); background: var(--warning-soft); }
.status-unresolved { color: var(--danger); border-color: var(--danger-border); background: var(--danger-soft); }
.tree-scroll {
  flex: 1;
  overflow: auto;
  padding: 8px;
  background: var(--canvas-deep);
}
.tree-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  color: var(--text-tertiary);
  background: var(--canvas-deep);
}
.tree-empty-mark {
  letter-spacing: .16em;
  color: var(--accent);
  font-weight: 900;
  font-size: 12px;
}
.tree-empty-title { color: var(--text-primary); font-size: 18px; font-weight: 850; }
.tree-empty-subtitle { font-size: 13px; }
.tree-section {
  width: 100%;
  min-width: 540px;
  container-name: tree-section;
  container-type: inline-size;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
  margin-bottom: 8px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 11px;
  background: var(--surface-muted);
  border-bottom: 1px solid var(--border);
}
.section-title { font-size: 14px; font-weight: 900; color: var(--text-primary); }
.section-subtitle { margin-top: 2px; color: var(--text-secondary); font-size: 12px; }
.section-size {
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  background: var(--surface);
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 800;
}
.tn { min-width: 0; font-family: var(--font-mono); font-size: 12px; font-variant-numeric: tabular-nums; }
.branch-row {
  min-width: 500px;
  min-height: 29px;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) 82px;
  align-items: center;
  gap: clamp(8px, 1.2cqw, 14px);
  padding-top: 3px;
  padding-bottom: 3px;
  padding-right: 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.branch-row:hover, .leaf-row:hover { background: var(--surface-hover); }
.branch-toggle {
  width: 18px;
  height: 18px;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  background: var(--surface-subtle);
  color: var(--accent);
  cursor: pointer;
  font-weight: 900;
  line-height: 1;
  flex-shrink: 0;
}
.branch-toggle:hover { border-color: var(--accent); color: var(--accent-hover); }
.branch-main {
  display: flex;
  align-items: center;
  gap: clamp(6px, 1cqw, 10px);
  min-width: 0;
  overflow: hidden;
}
.branch-name {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 48%;
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.branch-type {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 52%;
  overflow: hidden;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.branch-meta {
  min-width: 0;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: 11px;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.branch-children {
  margin-left: 16px;
  border-left: 1px solid var(--border);
}
.node-badge {
  color: var(--text-secondary);
  background: var(--surface-subtle);
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 900;
}
.node-badge-raw { color: var(--info); border-color: var(--info-border); background: var(--info-soft); }
.node-badge-sd { color: var(--warning); border-color: var(--warning-border); background: var(--warning-soft); }
.node-badge-unresolved { color: var(--danger); border-color: var(--danger-border); background: var(--danger-soft); }
.leaf-row {
  min-width: 500px;
  overflow: hidden;
  display: grid;
  grid-template-columns:
    clamp(200px, 28cqw, 250px)
    minmax(0, 1fr)
    clamp(145px, 22cqw, 170px);
  align-items: center;
  column-gap: clamp(8px, 1.2cqw, 16px);
  min-height: 30px;
  padding-top: 4px;
  padding-bottom: 4px;
  padding-right: 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.leaf-key {
  min-width: 0;
  overflow: hidden;
  padding-left: 22px;
  color: var(--text-primary);
  font-weight: 900;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.leaf-body {
  display: block;
  min-width: 0;
  overflow: hidden;
}
.leaf-value {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: center;
  column-gap: clamp(8px, 1cqw, 14px);
  min-width: 0;
  width: 100%;
  overflow: hidden;
}
.leaf-value.has-meaning {
  grid-template-columns: minmax(64px, 1fr) minmax(56px, 1fr) minmax(105px, 1.35fr);
}
.value-slot {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: clamp(5px, .8cqw, 10px);
  overflow: hidden;
}
.value-chip {
  min-width: 0;
  width: fit-content;
  max-width: 100%;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  gap: clamp(3px, .6cqw, 6px);
  min-height: 24px;
  padding: 0 clamp(5px, 1cqw, 9px);
  border-radius: var(--radius-control);
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--surface-muted);
  border: 1px solid var(--border);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.value-chip strong { color: var(--text-primary); font-weight: 900; }
.hex-chip { border-color: var(--accent-border); background: var(--accent-soft); }
.dec-chip { border-color: var(--border-strong); background: var(--surface-subtle); }
.plain-value {
  grid-column: 1 / -1;
  min-width: 0;
  display: block;
  max-width: 100%;
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 800;
  padding-inline: clamp(2px, .5cqw, 5px);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.leaf-meaning {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  gap: clamp(4px, .8cqw, 7px);
  min-height: 24px;
  padding: 0 clamp(5px, 1cqw, 9px);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-control);
  background: var(--accent-soft);
  white-space: nowrap;
}
.meta-label { color: var(--accent); font-size: 11px; font-weight: 900; text-transform: uppercase; }
.meaning-text {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.leaf-meta {
  min-width: 0;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(62px, .85fr) minmax(92px, 1.15fr);
  align-items: center;
  column-gap: clamp(6px, .8cqw, 10px);
  color: var(--text-tertiary);
  font-size: 12px;
  text-align: right;
  white-space: nowrap;
}
.leaf-meta > span {
  min-width: 0;
  overflow: hidden;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.leaf-meta > span + span {
  padding-left: clamp(5px, .7cqw, 8px);
  border-left: 1px solid var(--border-strong);
}
.leaf-meta strong { color: var(--text-primary); }

@container tree-section (max-width: 640px) {
  .leaf-value.has-meaning {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    row-gap: 4px;
  }
  .meaning-slot { grid-column: 1 / -1; }
}

@media (max-width: 760px) {
  .tree-header { align-items: flex-start; flex-direction: column; }
}
</style>
