import { useState } from 'react'
import './App.css'

type Choice = 'A' | 'B' | 'C'
type Score = -1 | 0 | 1

type MetricKey = 0 | 1 | 2 | 3 | 4

type MetricDef = {
  key: MetricKey
  title: string
  description: string
}

type SessionArticle = {
  article_id: string
  raw_title: string
  raw_text: string
  summaries: Record<Choice, string>
  ab_mapping: Record<Choice, 'raw' | 'structured' | 'rag'>
}

type SessionPayload = {
  ok: boolean
  error?: string
  detail?: string
  session_id?: string
  assigned_articles?: string[]
  data_version?: string
  articles?: SessionArticle[]
}

type TripleScore = Record<Choice, Score>
type ArticleResponses = Record<MetricKey, TripleScore>
type ResponsesByArticle = Record<string, ArticleResponses>

type StaticSessions = {
  step: string
  kind: string
  data_version: string
  sessions: Record<string, string[]>
}

type StaticArticlesById = Record<
  string,
  {
    article_id: string
    raw_title: string
    raw_text: string
    summary_raw: string
    summary_structured: string
    summary_rag: string
  }
>

const METRICS: MetricDef[] = [
  {
    key: 0,
    title: '指標 0：整體理解幫助度',
    description: '哪個摘要最能幫你快速且正確掌握這篇新聞「發生了什麼」？',
  },
  {
    key: 1,
    title: '指標 1：關鍵事實完整性',
    description: '是否涵蓋關鍵角色、事件、結果與必要背景（缺什麼會影響理解）？',
  },
  {
    key: 2,
    title: '指標 2：責任／歸因清晰度',
    description: '是否清楚指出責任主體、爭議點與行為性質（避免把結構問題變成個人責任）？',
  },
  {
    key: 3,
    title: '指標 3：勞工立場呈現',
    description: '是否充分呈現勞工處境、工人話語與權益受侵害的內容，而非只站在資方/官方角度？',
  },
  {
    key: 4,
    title: '指標 4：可讀性與可用性',
    description: '文字是否清楚、結構是否好讀、資訊是否不混亂（且不胡亂補細節）？',
  },
]

function defaultTriple(): TripleScore {
  return { A: 0, B: 0, C: 0 }
}

function defaultArticleResponses(): ArticleResponses {
  return {
    0: defaultTriple(),
    1: defaultTriple(),
    2: defaultTriple(),
    3: defaultTriple(),
    4: defaultTriple(),
  }
}

function normalizeExecBase(input: string): string {
  const trimmed = input.trim().replace(/\/+$/, '')
  if (!trimmed) return ''

  const idx = trimmed.indexOf('/exec')
  if (idx === -1) return trimmed
  return trimmed.slice(0, idx + '/exec'.length)
}

function isMetricComplete(triple: TripleScore): { ok: boolean; reason?: string } {
  const values = Object.values(triple)
  const best = values.filter((v) => v === 1).length
  const worst = values.filter((v) => v === -1).length
  if (best !== 1) return { ok: false, reason: best === 0 ? '尚未選 Best' : '出現多個 Best' }
  if (worst !== 1) return { ok: false, reason: worst === 0 ? '尚未選 Worst' : '出現多個 Worst' }
  return { ok: true }
}

function cycleScore(current: Score): Score {
  if (current === 0) return -1
  if (current === -1) return 1
  return 0
}

function setChoiceScore(triple: TripleScore, choice: Choice): TripleScore {
  const next = cycleScore(triple[choice])
  const out: TripleScore = { ...triple, [choice]: next }

  // 保證同一時間只有一個 Best / 一個 Worst（點下去就把其他同類型清掉）
  if (next === 1) {
    ;(Object.keys(out) as Choice[]).forEach((c) => {
      if (c !== choice && out[c] === 1) out[c] = 0
    })
  }
  if (next === -1) {
    ;(Object.keys(out) as Choice[]).forEach((c) => {
      if (c !== choice && out[c] === -1) out[c] = 0
    })
  }
  return out
}

type View = 'home' | 'metrics' | 'loading' | 'article' | 'submit' | 'done' | 'error'

function App() {
  const [view, setView] = useState<View>('home')
  // 只用於提交（POST）。GET 改由本站靜態 JSON，確保 GitHub Pages 可用且避開 CORS。
  const [execBase, setExecBase] = useState<string>(() => {
    const saved = localStorage.getItem('step01_exec_base')
    if (saved) return saved
    // Build-time default (set via VITE_GAS_EXEC_BASE in GitHub Actions vars)
    const envDefault = (import.meta.env.VITE_GAS_EXEC_BASE as string | undefined) || ''
    return envDefault
  })
  const [sid, setSid] = useState<string>(() => localStorage.getItem('step01_sid') || 'S001')
  const [participantId, setParticipantId] = useState<string>(() => localStorage.getItem('step01_participant_id') || '')

  const [session, setSession] = useState<SessionPayload | null>(null)
  const [responses, setResponses] = useState<ResponsesByArticle>({})
  const [articleIdx, setArticleIdx] = useState<number>(0)
  const [activeMetric, setActiveMetric] = useState<MetricKey>(0)

  const [startedAt, setStartedAt] = useState<string | null>(null)
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'submitting' | 'submitted' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  const articles: SessionArticle[] = session?.articles || []
  const current = articles[articleIdx]

  async function fetchJson(url: string, init?: RequestInit): Promise<{ res: Response; data: unknown }> {
    const res = await fetch(url, init)
    const text = await res.text()
    try {
      return { res, data: JSON.parse(text) as unknown }
    } catch {
      throw new Error(`HTTP ${res.status}（非 JSON 回應）\nURL: ${url}\n---\n${text.slice(0, 800)}`)
    }
  }

  function persistBasics(nextExecBase: string, nextSid: string, nextPid: string) {
    localStorage.setItem('step01_exec_base', nextExecBase)
    localStorage.setItem('step01_sid', nextSid)
    localStorage.setItem('step01_participant_id', nextPid)
  }

  async function loadSession() {
    const sessionId = sid.trim().toUpperCase()
    setError(null)
    setView('loading')

    persistBasics(normalizeExecBase(execBase), sessionId, participantId)

    try {
      // GH Pages 通用：GET 不打 Apps Script（避免 CORS 與 query/path 限制）
      const baseUrl = import.meta.env.BASE_URL || '/'
      const sessionsUrl = `${baseUrl}step01_data/step01_sessions_10x12.json`
      const articlesUrl = `${baseUrl}step01_data/step01_articles_by_id.json`

      const [{ res: sRes, data: sData }, { res: aRes, data: aData }] = await Promise.all([
        fetchJson(sessionsUrl, { method: 'GET' }),
        fetchJson(articlesUrl, { method: 'GET' }),
      ])
      if (!sRes.ok) throw new Error(`載入 sessions 失敗：HTTP ${sRes.status}`)
      if (!aRes.ok) throw new Error(`載入 articles 失敗：HTTP ${aRes.status}`)

      const sessions = sData as StaticSessions
      const articlesById = aData as StaticArticlesById
      const ids = sessions.sessions?.[sessionId]
      if (!ids || ids.length !== 12) throw new Error(`unknown_session 或 per_session 不為 12：${sessionId}`)

      const builtArticles: SessionArticle[] = ids.map((aid) => {
        const r = articlesById[aid]
        if (!r) throw new Error(`article_not_in_static_data: ${aid}`)

        // 前端生成 A/B/C 隨機對應（並在提交時回傳 ab_mapping 以便分析反解）
        const pool = [
          { key: 'raw' as const, text: r.summary_raw },
          { key: 'structured' as const, text: r.summary_structured },
          { key: 'rag' as const, text: r.summary_rag },
        ]
        for (let i = pool.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1))
          ;[pool[i], pool[j]] = [pool[j], pool[i]]
        }

        return {
          article_id: aid,
          raw_title: r.raw_title,
          raw_text: r.raw_text,
          summaries: { A: pool[0].text, B: pool[1].text, C: pool[2].text },
          ab_mapping: { A: pool[0].key, B: pool[1].key, C: pool[2].key },
        }
      })

      const payload: SessionPayload = {
        ok: true,
        session_id: sessionId,
        assigned_articles: ids,
        data_version: sessions.data_version,
        articles: builtArticles,
      }

      setSession(payload)

      const init: ResponsesByArticle = {}
      for (const a of builtArticles) init[a.article_id] = defaultArticleResponses()
      setResponses(init)
      setArticleIdx(0)
      setActiveMetric(0)
      setStartedAt(new Date().toISOString())
      setSubmitStatus('idle')
      setView('article')
    } catch (e) {
      setView('error')
      setError(String(e))
    }
  }

  async function quickToSubmitPage() {
    const sessionId = sid.trim().toUpperCase()
    setError(null)
    setView('loading')
    persistBasics(normalizeExecBase(execBase), sessionId, participantId)

    try {
      const baseUrl = import.meta.env.BASE_URL || '/'
      const sessionsUrl = `${baseUrl}step01_data/step01_sessions_10x12.json`
      const { res: sRes, data: sData } = await fetchJson(sessionsUrl, { method: 'GET' })
      if (!sRes.ok) throw new Error(`載入 sessions 失敗：HTTP ${sRes.status}`)
      const sessions = sData as StaticSessions
      const ids = sessions.sessions?.[sessionId]
      if (!ids || ids.length !== 12) throw new Error(`unknown_session 或 per_session 不為 12：${sessionId}`)

      // 最小 session：只為了測試 POST 是否能寫入 Sheet（不載入全文與摘要）
      setSession({
        ok: true,
        session_id: sessionId,
        assigned_articles: ids,
        data_version: sessions.data_version,
        articles: [],
      })
      setResponses({})
      setStartedAt(new Date().toISOString())
      setSubmitStatus('idle')
      setView('submit')
    } catch (e) {
      setView('error')
      setError(String(e))
    }
  }

  async function submitAll() {
    if (!session?.session_id) return
    const base = normalizeExecBase(execBase)
    const sessionId = session.session_id
    const assigned = session.assigned_articles || session.articles?.map((a) => a.article_id) || []
    const abMapping: Record<string, SessionArticle['ab_mapping']> = {}
    for (const a of session.articles || []) abMapping[a.article_id] = a.ab_mapping

    setSubmitStatus('submitting')
    setError(null)

    if (!base || !base.includes('/exec')) {
      setSubmitStatus('error')
      setError('請填入 Apps Script Web App 的 /exec 網址（用於提交）。')
      return
    }

    const payload = {
      api: 'submit',
      session_id: sessionId,
      participant_id: participantId || null,
      assigned_articles: assigned,
      article_order: assigned,
      ab_mapping: abMapping,
      responses,
      client_meta: {
        started_at: startedAt,
        completed_at: new Date().toISOString(),
        user_agent: navigator.userAgent,
      },
      app_version: `step01_platform_web@${import.meta.env.VITE_APP_VERSION || '0.0.0'}`,
      data_version: session.data_version || null,
    }

    try {
      // GH Pages 通用提交（最穩）：用 <form> POST 避開 CORS / preflight / redirect 限制。
      // 後端需支援 form body：api=submit&payload=<json>
      //
      // 注意：我們無法讀取回應，但可以用 iframe 的 load 事件確認「請求確實發出」。
      console.info('[step01] submitting to', base, { session_id: sessionId })

      const form = document.createElement('form')
      form.method = 'POST'
      form.action = base
      form.acceptCharset = 'utf-8'
      form.style.display = 'none'

      const api = document.createElement('input')
      api.type = 'hidden'
      api.name = 'api'
      api.value = 'submit'
      form.appendChild(api)

      const p = document.createElement('input')
      p.type = 'hidden'
      p.name = 'payload'
      p.value = JSON.stringify(payload)
      form.appendChild(p)

      const iframe = document.createElement('iframe')
      const iframeName = `step01_submit_${Date.now()}`
      iframe.name = iframeName
      iframe.style.display = 'none'

      document.body.appendChild(iframe)
      form.target = iframeName
      document.body.appendChild(form)
      form.submit()

      // 等 iframe load 才算「有發出去」（不代表寫入成功，但至少會在 Apps Script 看到 doPost）
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => {
          reject(new Error('提交逾時：瀏覽器未完成送出（請檢查 Network 是否有 /exec POST）'))
        }, 12000)

        iframe.addEventListener(
          'load',
          () => {
            window.clearTimeout(timeout)
            resolve()
          },
          { once: true }
        )
      })

      setSubmitStatus('submitted')
      setView('done')
      window.setTimeout(() => {
        form.remove()
        iframe.remove()
      }, 4000)
    } catch (e) {
      setSubmitStatus('error')
      setError(String(e))
    }
  }

  function metricStatusForCurrent(): { key: MetricKey; ok: boolean; reason?: string }[] {
    if (!current) return []
    const r = responses[current.article_id] || defaultArticleResponses()
    return METRICS.map((m) => ({ key: m.key, ...isMetricComplete(r[m.key]) }))
  }

  function isCurrentArticleComplete(): boolean {
    return metricStatusForCurrent().every((s) => s.ok)
  }

  function updateScore(metric: MetricKey, choice: Choice) {
    if (!current) return
    const aid = current.article_id
    setResponses((prev: ResponsesByArticle) => {
      const ar = prev[aid] || defaultArticleResponses()
      const nextTriple = setChoiceScore(ar[metric], choice)
      return {
        ...prev,
        [aid]: {
          ...ar,
          [metric]: nextTriple,
        },
      }
    })
  }

  function goNext() {
    if (!session?.articles) return
    if (!isCurrentArticleComplete()) return
    if (articleIdx >= session.articles.length - 1) {
      setView('submit')
      return
    }
    setArticleIdx((i: number) => i + 1)
    setActiveMetric(0)
  }

  function goPrev() {
    if (articleIdx <= 0) return
    setArticleIdx((i: number) => i - 1)
    setActiveMetric(0)
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand">Step01 人工評估平台（MVP）</div>
          <div className="muted">先看原文，再看摘要；每指標選 1 Best + 1 Worst</div>
        </div>
        {view === 'article' && session?.articles ? (
          <div className="topbar-right">
            <div className="pill">
              進度 <b>{articleIdx + 1}</b>/{session.articles.length}
            </div>
          </div>
        ) : null}
      </header>

      <main className="main">
        {view === 'home' ? (
          <section className="card">
            <h1>勞工立場新聞摘要：人工評估</h1>
            <p className="lead">
              本平台會給你一個 session（12 篇）。每篇請先完整閱讀原文，再比較 A/B/C 三個摘要，依 0→4
              指標各選 1 個 Best 與 1 個 Worst。
            </p>

            <div className="form">
              <label>
                <div className="label">Apps Script Web App（/exec，僅用於提交）</div>
                <input
                  value={execBase}
                  onChange={(e) => setExecBase(e.target.value)}
                  placeholder="https://script.google.com/macros/s/.../exec"
                />
                <div className="hint">
                  讀取 session 已改成本站靜態 JSON（可部署到 GitHub Pages）。這裡只需要填提交用的 <code>/exec</code>。
                </div>
              </label>

              <div className="row2">
                <label>
                  <div className="label">Session ID</div>
                  <input value={sid} onChange={(e) => setSid(e.target.value)} placeholder="S001" />
                </label>
                <label>
                  <div className="label">Participant ID（可留空）</div>
                  <input
                    value={participantId}
                    onChange={(e) => setParticipantId(e.target.value)}
                    placeholder="P001"
                  />
                </label>
              </div>
            </div>

            <div className="actions">
              <button className="btn" type="button" onClick={() => setView('metrics')}>
                開始
              </button>
              <button className="btn ghost" type="button" onClick={quickToSubmitPage}>
                直接到提交頁（測試）
              </button>
            </div>
          </section>
        ) : null}

        {view === 'metrics' ? (
          <section className="card">
            <h1>評估指標（0–4）</h1>
            <div className="metricList">
              {METRICS.map((m) => (
                <div key={m.key} className="metricItem">
                  <div className="metricTitle">{m.title}</div>
                  <div className="metricDesc">{m.description}</div>
                </div>
              ))}
            </div>
            <div className="actions">
              <button className="btn ghost" type="button" onClick={() => setView('home')}>
                返回
              </button>
              <button className="btn" type="button" onClick={loadSession}>
                我已理解，開始評測
              </button>
            </div>
          </section>
        ) : null}

        {view === 'loading' ? (
          <section className="card">
            <h1>載入中…</h1>
            <p className="muted">正在從 Apps Script 讀取 session 資料。</p>
          </section>
        ) : null}

        {view === 'error' ? (
          <section className="card">
            <h1>發生錯誤</h1>
            <pre className="pre">{error}</pre>
            <div className="actions">
              <button className="btn" type="button" onClick={() => setView('home')}>
                回到首頁
              </button>
            </div>
          </section>
        ) : null}

        {view === 'article' && current ? (
          <section className="page">
            <section className="card articleHeader">
              <div className="articleTitle">{current.raw_title}</div>
              <div className="muted">article_id: {current.article_id}</div>
            </section>

            <section className="card">
              <h2>原文（Raw）</h2>
              <div className="textBlock">{current.raw_text}</div>
            </section>

            <section className="card">
              <h2>評分（0→4）</h2>

              <div className="metricTabs">
                {METRICS.map((m) => (
                  <button
                    key={m.key}
                    type="button"
                    className={m.key === activeMetric ? 'tab active' : 'tab'}
                    onClick={() => setActiveMetric(m.key)}
                  >
                    {m.key}
                  </button>
                ))}
              </div>

              <div className="metricPanel">
                <div className="metricTitle">{METRICS.find((m) => m.key === activeMetric)?.title}</div>
                <div className="metricDesc">{METRICS.find((m) => m.key === activeMetric)?.description}</div>

                <div className="grid3">
                  {(['A', 'B', 'C'] as Choice[]).map((c) => {
                    const triple = (responses[current.article_id] || defaultArticleResponses())[activeMetric]
                    const v = triple[c]
                    const cls = v === 1 ? 'summaryCard pickable best' : v === -1 ? 'summaryCard pickable worst' : 'summaryCard pickable'
                    const label = v === 1 ? 'Best' : v === -1 ? 'Worst' : 'None'
                    return (
                      <button
                        key={c}
                        type="button"
                        className={cls}
                        onClick={() => updateScore(activeMetric, c)}
                      >
                        <div className="summaryHead">
                          <div className="badge">{c}</div>
                          <div className="statePill">{label}</div>
                        </div>
                        <div className="textBlock">{current.summaries[c]}</div>
                      </button>
                    )
                  })}
                </div>

                <div className="checklist">
                  {metricStatusForCurrent().map((s) => (
                    <div key={s.key} className={s.ok ? 'check ok' : 'check bad'}>
                      <span className="checkKey">指標 {s.key}</span>
                      <span className="checkMsg">{s.ok ? '✅ 已完成' : `⚠️ ${s.reason}`}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="actions">
                <button className="btn ghost" type="button" onClick={goPrev} disabled={articleIdx === 0}>
                  上一篇
                </button>
                <button className="btn" type="button" onClick={goNext} disabled={!isCurrentArticleComplete()}>
                  {articleIdx === (session?.articles?.length || 1) - 1 ? '完成並前往提交' : '下一篇'}
                </button>
              </div>
            </section>
          </section>
        ) : null}

        {view === 'submit' && session?.articles ? (
          <section className="card">
            <h1>提交</h1>
            <p className="muted">
              你已完成 12 篇評測。按下提交後，系統會一次性把本 session 的所有結果寫入 Google Sheet。
            </p>
            {submitStatus === 'error' ? <pre className="pre">{error}</pre> : null}
            <div className="actions">
              <button className="btn ghost" type="button" onClick={() => setView('article')}>
                返回修改
              </button>
              <button className="btn" type="button" onClick={submitAll} disabled={submitStatus === 'submitting'}>
                {submitStatus === 'submitting' ? '提交中…' : '確認提交'}
              </button>
            </div>
          </section>
        ) : null}

        {view === 'done' ? (
          <section className="card">
            <h1>已提交</h1>
            <p className="muted">感謝！你可以直接關閉頁面。</p>
            <div className="actions">
              <button className="btn" type="button" onClick={() => setView('home')}>
                回到首頁
              </button>
            </div>
          </section>
        ) : null}
      </main>
    </div>
  )
}

export default App
