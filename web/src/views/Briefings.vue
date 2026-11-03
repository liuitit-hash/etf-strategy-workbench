<script setup>
import { ref, computed, onMounted } from 'vue'
import { marked } from 'marked'
import { supabase } from '../supabase'
import { BRIEFING_LABEL } from '../lib/format'

const type = ref('post')
const list = ref([])
const copied = ref(false)

async function load() {
  const { data } = await supabase.from('briefings').select('*')
    .order('date', { ascending: false }).order('created_at', { ascending: false }).limit(40)
  list.value = data || []
}
onMounted(load)

// 选中类型的最新一篇
const current = computed(() => list.value.find((b) => b.type === type.value) || null)
const html = computed(() => (current.value ? marked.parse(current.value.markdown) : ''))

async function copy() {
  if (!current.value) return
  await navigator.clipboard.writeText(current.value.markdown)
  copied.value = true; setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <h2>简报中心</h2>
  <p class="muted" style="font-size:12px">简报由定时任务后台预生成入库，页面只读。需要临时复盘可在 GitHub Actions 手动 dispatch。</p>

  <div class="pill-group">
    <button v-for="t in ['pre','intra','post']" :key="t" :class="{ on: type === t }" @click="type = t">{{ BRIEFING_LABEL[t] }}</button>
  </div>

  <div v-if="current" class="card">
    <div class="spread">
      <span class="muted" style="font-size:12px">{{ current.date }} · v{{ current.version }} · {{ current.model }}</span>
      <button class="ghost" @click="copy">{{ copied ? '已复制' : '复制 Markdown' }}</button>
    </div>
    <div class="md" v-html="html"></div>
  </div>
  <div v-else class="card muted">暂无「{{ BRIEFING_LABEL[type] }}」简报。定时任务运行后会出现在这里。</div>
</template>
