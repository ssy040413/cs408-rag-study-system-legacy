<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const API_BASE = 'http://localhost:8001'
const STATIC_BASE = `${API_BASE}/static/408`

const router = useRouter()
const treeData = ref([])
const docs = ref([])
const loading = ref(false)
const selectedKeys = ref([])
const currentSubject = ref('')
const currentChapter = ref('')

const defaultProps = {
  children: 'children',
  label: 'label',
}

const fetchChapters = async () => {
  try {
    const res = await fetch(`${API_BASE}/api/kb/chapters`)
    const data = await res.json()
    treeData.value = data.tree || []
  } catch (e) {
    console.error('加载章节失败', e)
  }
}

const fetchDocs = async (subject, chapter) => {
  loading.value = true
  currentSubject.value = subject
  currentChapter.value = chapter
  try {
    const url = new URL(`${API_BASE}/api/kb/chapter_docs`)
    url.searchParams.set('subject', subject)
    url.searchParams.set('chapter', chapter)
    const res = await fetch(url)
    const data = await res.json()
    docs.value = data.docs || []
  } catch (e) {
    console.error('加载文档失败', e)
    docs.value = []
  } finally {
    loading.value = false
  }
}

const onNodeClick = (node) => {
  if (node.is_leaf) {
    fetchDocs(node.subject, node.chapter)
  }
}

const PDF_MAP = {
  '数据结构': '27版竟成《数据结构考研复习全书》-20260228日公开(OCR)(已优化).pdf',
}

const resolvePdfName = (subject) => {
  return PDF_MAP[subject] || ''
}

const openPdfAtPage = (doc) => {
  const pdfName = resolvePdfName(doc.subject)
  if (!pdfName) return
  const url = `${STATIC_BASE}/${encodeURIComponent(pdfName)}#page=${doc.page_start || 1}`
  window.open(url, '_blank')
}

const goChat = () => {
  router.push('/')
}

onMounted(() => {
  fetchChapters()
})
</script>

<template>
  <div class="kb-layout">
    <aside class="kb-sidebar">
      <div class="kb-header">
        <div class="kb-brand">408 知识库</div>
        <el-button type="primary" size="small" @click="goChat" :icon="'ChatLineRound'">返回对话</el-button>
      </div>
      <el-tree
        :data="treeData"
        :props="defaultProps"
        @node-click="onNodeClick"
        highlight-current
        class="kb-tree"
      />
    </aside>

    <main class="kb-main">
      <div class="kb-toolbar">
        <h3 v-if="currentChapter">{{ currentChapter }}</h3>
        <h3 v-else>请点击左侧章节查看原文</h3>
        <el-tag v-if="currentSubject" type="info" size="small">{{ currentSubject }}</el-tag>
      </div>

      <div v-loading="loading" class="kb-content">
        <div v-if="docs.length === 0 && !loading" class="empty-tip">暂无内容</div>

        <div
          v-for="(doc, idx) in docs"
          :key="idx"
          class="doc-card"
        >
          <div class="doc-meta">
            <span class="doc-title">{{ doc.chapter }}</span>
            <span class="doc-page">p{{ doc.page_start }}-{{ doc.page_end }}</span>
            <el-button size="small" type="primary" text @click="openPdfAtPage(doc)">
              查看PDF原文
            </el-button>
          </div>
          <div class="doc-body">{{ doc.content }}</div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.kb-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
}
.kb-sidebar {
  width: 280px;
  background: #ffffff;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
}
.kb-header {
  padding: 16px;
  border-bottom: 1px solid #e5e7eb;
}
.kb-brand {
  font-weight: 700;
  font-size: 16px;
  margin-bottom: 10px;
  color: #111827;
}
.kb-tree {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}
.kb-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f9fafb;
  min-width: 0;
}
.kb-toolbar {
  height: 56px;
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}
.kb-toolbar h3 {
  margin: 0;
  font-weight: 600;
  color: #111827;
}
.kb-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px 8vw;
}
.empty-tip {
  text-align: center;
  color: #9ca3af;
  padding: 40px;
}
.doc-card {
  background: #ffffff;
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.doc-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.doc-title {
  font-weight: 600;
  color: #111827;
}
.doc-page {
  color: #6b7280;
  font-size: 13px;
}
.doc-body {
  color: #374151;
  line-height: 1.7;
  white-space: pre-wrap;
}
</style>
