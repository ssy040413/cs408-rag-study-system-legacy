<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import LLMSettingsDialog from './LLMSettingsDialog.vue'

const API_BASE = 'http://localhost:8001'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(code, { language: lang }).value } catch (e) {}
    }
    return hljs.highlightAuto(code).value
  },
})

md.renderer.rules.math_inline = (tokens, idx) => {
  try { return katex.renderToString(tokens[idx].content, { throwOnError: false, displayMode: false }) } catch (e) { return tokens[idx].content }
}
md.renderer.rules.math_block = (tokens, idx) => {
  try { return katex.renderToString(tokens[idx].content, { throwOnError: false, displayMode: true }) } catch (e) { return tokens[idx].content }
}

md.inline.ruler.before('escape', 'math_inline', (state, silent) => {
  if (state.src.charCodeAt(state.pos) !== 0x24) return false
  const start = state.pos + 1
  const match = state.src.indexOf('$', start)
  if (match === -1 || match === start) return false
  if (!silent) {
    const token = state.push('math_inline', 'math', 0)
    token.content = state.src.slice(start, match)
    token.markup = '$'
  }
  state.pos = match + 1
  return true
})

md.block.ruler.before('fence', 'math_block', (state, startLine, endLine, silent) => {
  const pos = state.bMarks[startLine] + state.tShift[startLine]
  const max = state.eMarks[startLine]
  if (pos + 2 > max) return false
  const marker = state.src.slice(pos, pos + 2)
  if (marker !== '$$') return false
  let nextLine = startLine + 1
  let content = ''
  while (nextLine < endLine) {
    const linePos = state.bMarks[nextLine] + state.tShift[nextLine]
    const lineMax = state.eMarks[nextLine]
    const line = state.src.slice(linePos, lineMax)
    if (line.trim() === '$$') {
      if (!silent) {
        const token = state.push('math_block', 'math', 0)
        token.content = content.trim()
        token.markup = '$$'
        token.map = [startLine, nextLine + 1]
      }
      state.line = nextLine + 1
      return true
    }
    content += line + '\n'
    nextLine++
  }
  return false
})

const router = useRouter()

const sessions = ref([])
const currentSessionId = ref('')
const messages = ref([])
const inputMessage = ref('')
const loading = ref(false)
const chatContainer = ref(null)
const settingsVisible = ref(false)

const openSettings = () => {
  settingsVisible.value = true
}

const goKb = () => {
  router.push('/kb')
}

const scrollToBottom = async () => {
  await nextTick()
  if (chatContainer.value) chatContainer.value.scrollTop = chatContainer.value.scrollHeight
}

const fetchSessions = async () => {
  try {
    const res = await fetch(`${API_BASE}/api/sessions`)
    const data = await res.json()
    sessions.value = data.sessions || []
  } catch (e) {}
}

const createSession = async () => {
  currentSessionId.value = ''
  messages.value = []
  await fetchSessions()
}

const switchSession = async (sid) => {
  currentSessionId.value = sid
  try {
    const res = await fetch(`${API_BASE}/api/sessions/${sid}`)
    const data = await res.json()
    messages.value = (data.messages || []).map(m => ({
      role: m.role,
      content: m.content,
      sources: [],
      status: m.role === 'assistant' ? 'done' : undefined,
    }))
    await scrollToBottom()
  } catch (e) {
    ElMessage.error('获取会话失败')
  }
}

const deleteSession = async (sid, event) => {
  event.stopPropagation()
  try {
    await fetch(`${API_BASE}/api/sessions/${sid}`, { method: 'DELETE' })
    if (currentSessionId.value === sid) {
      currentSessionId.value = ''
      messages.value = []
    }
    await fetchSessions()
  } catch (e) {
    ElMessage.error('删除会话失败')
  }
}

const sendMessage = async () => {
  const text = inputMessage.value.trim()
  if (!text || loading.value) return
  messages.value.push({ role: 'user', content: text, sources: [] })
  inputMessage.value = ''
  loading.value = true
  await scrollToBottom()

  messages.value.push({ role: 'assistant', content: '', sources: [], status: 'retrieving' })
  const assistantIdx = messages.value.length - 1

  // 滚动节流：流式阶段不每字都滚动，避免阻塞渲染
  let scrollTimer = null
  const throttledScroll = () => {
    if (scrollTimer) return
    scrollTimer = setTimeout(() => {
      scrollToBottom()
      scrollTimer = null
    }, 150)
  }

  try {
    const response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: currentSessionId.value || undefined }),
    })

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      let currentEvent = 'message'
      let dataBuffer = ''
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim()
        if (line.startsWith('event:')) {
          currentEvent = line.replace('event:', '').trim()
        } else if (line.startsWith('data:')) {
          dataBuffer = line.replace('data:', '').trim()
          try {
            const payload = JSON.parse(dataBuffer)
            if (currentEvent === 'session_id') {
              currentSessionId.value = payload.session_id
              await fetchSessions()
            } else if (currentEvent === 'retrieving') {
              messages.value[assistantIdx].status = 'retrieving'
            } else if (currentEvent === 'thinking') {
              messages.value[assistantIdx].status = 'thinking'
            } else if (currentEvent === 'message') {
              if (messages.value[assistantIdx].status !== 'streaming') {
                messages.value[assistantIdx].status = 'streaming'
              }
              messages.value[assistantIdx].content += payload.delta
              throttledScroll()
            } else if (currentEvent === 'source') {
              messages.value[assistantIdx].sources = payload.sources || []
            } else if (currentEvent === 'end') {
              messages.value[assistantIdx].status = 'done'
            }
          } catch (e) {}
          dataBuffer = ''
        }
      }
    }
  } catch (e) {
    messages.value[assistantIdx].content += '\n[连接失败，请检查后端服务是否运行]'
    messages.value[assistantIdx].status = 'done'
    ElMessage.error('请求失败')
  } finally {
    loading.value = false
    if (messages.value[assistantIdx] && messages.value[assistantIdx].status !== 'done') {
      messages.value[assistantIdx].status = 'done'
    }
  }
  await scrollToBottom()
}

const handleKeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

const statusText = (status) => {
  if (status === 'retrieving') return '正在检索知识库'
  if (status === 'thinking') return '正在思考问题'
  if (status === 'streaming') return '正在生成回答'
  return ''
}

onMounted(() => {
  fetchSessions()
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="brand">408 智能学习助手</div>
        <div class="sidebar-actions">
          <el-button type="primary" size="small" @click="createSession" :icon="'Plus'">新建对话</el-button>
          <el-button size="small" @click="openSettings" :icon="'Setting'">设置</el-button>
        </div>
      </div>
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.session_id"
          :class="['session-item', { active: currentSessionId === s.session_id }]"
          @click="switchSession(s.session_id)"
        >
          <el-icon><ChatLineRound /></el-icon>
          <span class="session-title" :title="s.title">{{ s.title || '新对话' }}</span>
          <span v-if="s.message_count" class="msg-count">{{ s.message_count }}</span>
          <el-icon class="delete-icon" @click="deleteSession(s.session_id, $event)"><Delete /></el-icon>
        </div>
        <div v-if="sessions.length === 0" class="empty-tip">暂无会话，点击上方新建</div>
      </div>
    </aside>

    <main class="chat-main">
      <div class="chat-header">
        <span>408 考研计算机专业课智能答疑</span>
        <el-button type="primary" size="small" :icon="'Collection'" @click="goKb">知识库</el-button>
      </div>
      <div ref="chatContainer" class="chat-body">
        <div v-if="messages.length === 0" class="welcome">
          <h2>欢迎使用 408 智能学习助手</h2>
          <p>基于 RAG 技术，结合权威教材与真题，为你提供精准、可溯源的专业知识解答。</p>
          <div class="quick-questions">
            <el-tag class="q-tag" @click="inputMessage = '什么是虚拟内存？'; sendMessage()">什么是虚拟内存？</el-tag>
            <el-tag class="q-tag" @click="inputMessage = 'TCP 三次握手的过程是什么？'; sendMessage()">TCP 三次握手</el-tag>
            <el-tag class="q-tag" @click="inputMessage = 'Cache 的三种映射方式有什么区别？'; sendMessage()">Cache 映射方式</el-tag>
            <el-tag class="q-tag" @click="inputMessage = '快速排序的时间复杂度是多少？'; sendMessage()">快排时间复杂度</el-tag>
          </div>
        </div>

        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          :class="['message-row', msg.role]"
        >
          <div class="avatar">
            <el-avatar v-if="msg.role === 'user'" :size="36" :icon="'UserFilled'" />
            <el-avatar v-else :size="36" :icon="'Cpu'" style="background: #7c3aed" />
          </div>
          <div class="message-content">
            <div v-if="msg.role === 'user'" class="user-text">{{ msg.content }}</div>
            <div v-else>
              <div v-if="msg.content && (!msg.status || msg.status === 'done')" class="md-content" v-html="md.render(msg.content)" />
              <div v-else-if="msg.content" class="streaming-content" style="white-space: pre-wrap; line-height: 1.6;">{{ msg.content }}</div>
              <div v-if="msg.status && msg.status !== 'done'" class="status-line">
                <span class="status-dot" />
                <span class="status-label">{{ statusText(msg.status) }}</span>
              </div>
              <div v-if="msg.sources && msg.sources.length" class="sources-block">
                <div class="sources-title">知识来源</div>
                <el-collapse>
                  <el-collapse-item
                    v-for="(src, sidx) in msg.sources"
                    :key="sidx"
                    :title="`${src.source || src.subject || '来源'} · ${src.chapter || ''} · p${src.page_start || ''}-${src.page_end || ''}`"
                  >
                    <div class="source-content">{{ src.content }}</div>
                  </el-collapse-item>
                </el-collapse>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="chat-input-area">
        <div class="input-box">
          <el-input
            v-model="inputMessage"
            type="textarea"
            :rows="2"
            placeholder="请输入你的问题，Shift+Enter 换行，Enter 发送"
            resize="none"
            @keydown="handleKeydown"
          />
          <el-button type="primary" :disabled="!inputMessage.trim() || loading" @click="sendMessage" :icon="'Promotion'">发送</el-button>
        </div>
        <div class="input-hint">内容由 AI 生成，仅供参考，请以教材和真题为准</div>
      </div>
    </main>
  </div>
  <LLMSettingsDialog v-model="settingsVisible" />
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  width: 100vw;
}
.sidebar {
  width: 260px;
  background: #ffffff;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #e5e7eb;
}
.brand {
  font-weight: 700;
  font-size: 16px;
  margin-bottom: 10px;
  color: #111827;
}
.sidebar-actions {
  display: flex;
  gap: 8px;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 6px;
  color: #374151;
  transition: background 0.2s;
}
.session-item:hover {
  background: #f3f4f6;
}
.msg-count {
  font-size: 12px;
  color: #9ca3af;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 10px;
  margin-left: 4px;
  flex-shrink: 0;
}
.session-item.active {
  background: #ede9fe;
  color: #5b21b6;
}
.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}
.delete-icon {
  opacity: 0;
  font-size: 14px;
  color: #9ca3af;
}
.session-item:hover .delete-icon {
  opacity: 1;
}
.empty-tip {
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
  padding: 20px;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f9fafb;
  min-width: 0;
}
.chat-header {
  height: 56px;
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  padding: 0 20px;
  font-weight: 600;
  color: #111827;
}
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 8vw;
}
.welcome {
  text-align: center;
  margin-top: 10vh;
  color: #4b5563;
}
.welcome h2 {
  color: #111827;
  margin-bottom: 8px;
}
.quick-questions {
  margin-top: 20px;
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
}
.q-tag {
  cursor: pointer;
}

.message-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}
.message-row.user {
  flex-direction: row-reverse;
}
.message-content {
  max-width: 80%;
  background: #ffffff;
  padding: 12px 16px;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.message-row.user .message-content {
  background: #ede9fe;
  color: #1f2937;
}
.user-text {
  white-space: pre-wrap;
  line-height: 1.6;
}

.status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  color: #6b7280;
  font-size: 14px;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #7c3aed;
  animation: pulse 1.4s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.status-label {
  font-style: italic;
}

.sources-block {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #e5e7eb;
}
.sources-title {
  font-size: 13px;
  color: #6b7280;
  margin-bottom: 6px;
}
.source-content {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.5;
}

.chat-input-area {
  background: #ffffff;
  border-top: 1px solid #e5e7eb;
  padding: 16px 8vw;
}
.input-box {
  display: flex;
  gap: 10px;
}
.input-box :deep(.el-textarea__inner) {
  border-radius: 10px;
  padding: 10px 14px;
}
.input-hint {
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
  margin-top: 8px;
}
@media (max-width: 768px) {
  .sidebar { width: 200px; min-width: 180px; }
  .chat-body { padding: 14px 16px; }
  .chat-input-area { padding: 12px 16px; }
}
</style>
