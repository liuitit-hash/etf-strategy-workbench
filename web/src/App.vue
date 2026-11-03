<script setup>
import { ref, onMounted } from 'vue'
import { supabase } from './supabase'
import { store, loadAll } from './store'
import Portfolio from './views/Portfolio.vue'
import ConfigPanel from './views/ConfigPanel.vue'
import TradeEntry from './views/TradeEntry.vue'
import DataBoard from './views/DataBoard.vue'
import Briefings from './views/Briefings.vue'
import History from './views/History.vue'

const tab = ref('portfolio')
const email = ref('')
const sent = ref(false)
const authMsg = ref('')

const TABS = [
  { k: 'portfolio', ic: '📊', label: '看板' },
  { k: 'trade', ic: '✍️', label: '录入' },
  { k: 'briefings', ic: '📰', label: '简报' },
  { k: 'data', ic: '🌐', label: '数据' },
  { k: 'config', ic: '⚙️', label: '策略' },
  { k: 'history', ic: '🕰️', label: '回溯' },
]
const views = { portfolio: Portfolio, config: ConfigPanel, trade: TradeEntry, data: DataBoard, briefings: Briefings, history: History }

async function sendLink() {
  authMsg.value = ''
  const { error } = await supabase.auth.signInWithOtp({ email: email.value, options: { emailRedirectTo: window.location.href } })
  if (error) authMsg.value = error.message
  else sent.value = true
}
async function logout() { await supabase.auth.signOut(); store.user = null }

onMounted(async () => {
  const { data } = await supabase.auth.getSession()
  store.user = data.session?.user || null
  if (store.user) loadAll()
  supabase.auth.onAuthStateChange((_e, session) => {
    store.user = session?.user || null
    if (store.user) loadAll()
  })
})
</script>

<template>
  <!-- 登录门 -->
  <div v-if="!store.user" class="card" style="margin-top:28vh">
    <h2>ETF 策略校准工作台</h2>
    <p class="muted" style="font-size:13px">单人自用。用你的邮箱登录（魔法链接），仅你可读写自己的数据。</p>
    <template v-if="!sent">
      <label>邮箱</label>
      <input v-model="email" type="email" placeholder="you@example.com" />
      <button class="primary" style="width:100%;margin-top:12px" @click="sendLink">发送登录链接</button>
    </template>
    <p v-else class="muted" style="font-size:13px">已发送登录链接到 {{ email }}，点击邮件里的链接即可登录。</p>
    <p v-if="authMsg" class="error">{{ authMsg }}</p>
  </div>

  <template v-else>
    <header class="app-header">
      <div>
        <div class="title">ETF 策略校准工作台</div>
        <div class="sub">{{ store.user.email }} · 自用纪律校验</div>
      </div>
      <div class="row">
        <button class="ghost" @click="loadAll" :disabled="store.loading">{{ store.loading ? '…' : '刷新' }}</button>
        <button class="ghost" @click="logout">退出</button>
      </div>
    </header>

    <p v-if="store.error" class="error">加载出错：{{ store.error }}</p>

    <component :is="views[tab]" />

    <nav class="tabbar">
      <button v-for="t in TABS" :key="t.k" :class="{ active: tab === t.k }" @click="tab = t.k">
        <span class="ic">{{ t.ic }}</span><span>{{ t.label }}</span>
      </button>
    </nav>
  </template>
</template>
