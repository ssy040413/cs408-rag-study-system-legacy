<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  modelValue: Boolean,
})
const emit = defineEmits(['update:modelValue'])

const API_BASE = 'http://localhost:8001'

const visible = ref(props.modelValue)
watch(() => props.modelValue, (v) => { visible.value = v })
watch(visible, (v) => { emit('update:modelValue', v) })

const form = ref({
  provider: 'anthropic',
  base_url: '',
  api_key: '',
  model: '',
})
const loading = ref(false)
const saving = ref(false)

const fetchConfig = async () => {
  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/api/settings/llm`)
    const data = await res.json()
    form.value = {
      provider: data.provider || 'anthropic',
      base_url: data.base_url || '',
      api_key: data.api_key || '',
      model: data.model || '',
    }
  } catch (e) {
    ElMessage.error('获取配置失败')
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const res = await fetch(`${API_BASE}/api/settings/llm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    const data = await res.json()
    if (data.success) {
      ElMessage.success('配置已保存')
      visible.value = false
    } else {
      ElMessage.error(data.message || '保存失败')
    }
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const onOpen = () => {
  fetchConfig()
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="LLM API 设置"
    width="480px"
    @open="onOpen"
  >
    <el-form :model="form" label-width="100px" v-loading="loading">
      <el-form-item label="提供商">
        <el-select v-model="form.provider" style="width: 100%">
          <el-option label="Anthropic" value="anthropic" />
          <el-option label="OpenAI 兼容" value="openai" />
        </el-select>
      </el-form-item>
      <el-form-item label="Base URL">
        <el-input v-model="form.base_url" placeholder="例如 https://api.anthropic.com" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input v-model="form.api_key" type="password" show-password placeholder="输入你的 API Key" />
      </el-form-item>
      <el-form-item label="模型名称">
        <el-input v-model="form.model" placeholder="例如 claude-sonnet-4-6" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
    </template>
  </el-dialog>
</template>
