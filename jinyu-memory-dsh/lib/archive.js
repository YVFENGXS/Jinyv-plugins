/**
 * Background archiving of completed turns into event cards and facts.
 *
 * The model is asked for one JSON object. Parsing tolerates bare JSON, a
 * ```json fence, and leading/trailing prose. Any model failure, missing route,
 * or empty result falls back to a deterministic local summary so memory keeps
 * working offline.
 *
 * @module jinyu-memory-dsh/archive
 */

import { cleanText, STOP_CHARS } from './recall.js'

const PROMPT = `你是角色扮演记忆整理员。只输出一个 JSON 对象，不要解释文字，不要 markdown 代码块。

从下面的对话片段抽取长期记忆：
1. cards：1-3 张事件卡。summary 写「谁因为什么做了什么」，一句话，只写对话里确实发生的事，不推测心理。
2. hooks：2-5 个具体可指代的对象（对玩家的称呼、物品、地点、专名），用对话里的原词，2-6 字；
   不要情绪词（难过/开心）、动作词（告别/约定）、抽象概念。
3. facts：0-3 条值得长期记住的稳定事实。text 是不超过 30 字的陈述句；tags 是 2-4 个以后会用来找它的名词。
4. importance 取 0~1；boundary 取 "self"（仅角色知道）、"player"（仅玩家知道）、"both"（双方都知道）。
5. 每条 fact 的 kind 取 "设定"（永久设定/偏好）、"事件"（值得记得的经历）、"临时"（只在当下成立的状态）。

输出格式：
{"cards":[{"summary":"...","hooks":["..."],"importance":0.5,"boundary":"both"}],
 "facts":[{"text":"...","kind":"设定","tags":["..."],"importance":0.8}]}

对话片段：
`

const CTRL = /[\u0000-\u001f\u202a-\u202e\u2066-\u2069]+/g
const BOUNDARIES = new Set(['self', 'player', 'both'])
const KINDS = new Set(['设定', '事件', '临时'])
const HAN = /[\u4e00-\u9fff]/u

function clamp(value, fallback = 0.5) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.round(Math.max(0, Math.min(1, n)) * 1000) / 1000
}

function clean(value, limit = 0) {
  const text = String(value ?? '').replace(CTRL, '').trim()
  return limit > 0 ? text.slice(0, limit) : text
}

function terms(value, limit) {
  if (!Array.isArray(value)) return []
  const out = []
  for (const item of value) {
    const term = clean(item, 8)
    if (term && !out.includes(term)) out.push(term)
  }
  return out.slice(0, limit)
}

/**
 * Parse a model reply into cards and facts.
 * @param {string} raw - model output.
 * @returns {{cards: object[], facts: object[]}|null} normalized result, or null when unusable.
 */
export function parseArchive(raw) {
  const text = String(raw ?? '').trim()
  let data
  try {
    data = JSON.parse(text)
  } catch {
    const fenced = /```(?:json)?\s*(.*?)```/s.exec(text)
    if (fenced) {
      try {
        data = JSON.parse(fenced[1].trim())
      } catch {
        data = undefined
      }
    }
    if (data === undefined) {
      const lo = text.indexOf('{')
      const hi = text.lastIndexOf('}')
      if (lo !== -1 && hi > lo) {
        try {
          data = JSON.parse(text.slice(lo, hi + 1))
        } catch {
          data = undefined
        }
      }
    }
  }
  if (!data || typeof data !== 'object') return null
  const cards = []
  for (const item of Array.isArray(data.cards) ? data.cards : []) {
    if (!item || typeof item !== 'object') continue
    const summary = clean(item.summary, 200)
    if (!summary) continue
    cards.push({
      summary,
      hooks: terms(item.hooks, 8),
      relHooks: terms(item.relHooks, 5),
      importance: clamp(item.importance, 0.5),
      boundary: BOUNDARIES.has(item.boundary) ? item.boundary : 'both',
    })
  }
  const facts = []
  for (const item of Array.isArray(data.facts) ? data.facts : []) {
    const value = item && typeof item === 'object' ? item : { text: item }
    const fact = clean(value.text ?? value.fact, 40)
    if (fact.length < 2) continue
    facts.push({
      text: fact,
      kind: KINDS.has(value.kind ?? value.category) ? value.kind ?? value.category : '',
      tags: terms(value.tags, 4),
      importance: clamp(value.importance, 0.5),
    })
  }
  if (cards.length === 0 && facts.length === 0) return null
  return { cards: cards.slice(0, 3), facts: facts.slice(0, 3) }
}

function dialogueText(turns) {
  const lines = []
  for (const turn of turns) {
    if (turn.user) lines.push(`[t${turn.turn}] 用户：${cleanText(turn.user, 600)}`)
    if (turn.assistant) lines.push(`[t${turn.turn}] 助手：${cleanText(turn.assistant, 600)}`)
  }
  return lines.join('\n')
}

function frequentHooks(text, limit = 5) {
  const counts = new Map()
  for (let i = 0; i < text.length - 1; i += 1) {
    const key = text.slice(i, i + 2)
    if (!HAN.test(key[0]) || !HAN.test(key[1])) continue
    if (STOP_CHARS.has(key[0]) || STOP_CHARS.has(key[1])) continue
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([key]) => key)
}

/**
 * Deterministic archive used when the model is unavailable or its output is unusable.
 * @param {object[]} turns - unarchived turns.
 * @returns {{cards: object[], facts: object[]}} one locally summarized card.
 */
export function fallbackArchive(turns) {
  if (!Array.isArray(turns) || turns.length === 0) return { cards: [], facts: [] }
  const body = turns.map(turn => `${turn.user || ''} ${turn.assistant || ''}`).join(' ')
  const first = turns.find(turn => turn.user)?.user || turns.find(turn => turn.assistant)?.assistant || ''
  const summary = clean(first, 100) || `第 ${turns[0].turn}-${turns.at(-1).turn} 轮对话`
  return {
    cards: [{
      summary,
      hooks: frequentHooks(body),
      importance: 0.45,
      boundary: 'both',
      turnStart: turns[0].turn,
      turnEnd: turns.at(-1).turn,
    }],
    facts: [],
  }
}

async function askModel(llm, route, prompt, signal) {
  if (!llm || typeof llm.stream !== 'function') throw new Error('llm service unavailable')
  if (!route?.provider || !route?.model) throw new Error('no model route selected')
  let out = ''
  const chunks = llm.stream({
    provider: route.provider,
    model: route.model,
    maxTokens: 1200,
    messages: [{ role: 'user', content: [{ type: 'text', text: prompt }] }],
    ...(signal ? { signal } : {}),
  })
  for await (const chunk of chunks) {
    if (!chunk) continue
    if (chunk.type === 'text-delta' && typeof chunk.text === 'string') out += chunk.text
    else if (chunk.type === 'block-end' && chunk.block?.type === 'text' && !out) out = chunk.block.text ?? ''
    else if (chunk.type === 'finish') {
      const kind = chunk.reason?.kind
      if (kind === 'error' || kind === 'aborted') {
        const failure = chunk.reason?.failure
        throw new Error(`model ${kind}: ${failure?.message || failure?.code || kind}`)
      }
    }
  }
  return out
}

/**
 * Archive a batch, preferring the model and falling back locally on any failure.
 * @param {object} options - archive options.
 * @param {object[]} options.turns - turns to summarize.
 * @param {object} [options.llm] - DSH llm service.
 * @param {{provider: string, model: string}|undefined} [options.route] - selected model route.
 * @param {AbortSignal} [options.signal] - cancellation signal.
 * @param {object} [options.logger] - logger with a `warn` method.
 * @returns {Promise<{cards: object[], facts: object[], source: 'model'|'local', error?: string}>} archive result.
 */
export async function archiveBatch({ turns, llm, route, signal, logger }) {
  if (!Array.isArray(turns) || turns.length === 0) return { cards: [], facts: [], source: 'local' }
  try {
    const raw = await askModel(llm, route, `${PROMPT}${dialogueText(turns)}`, signal)
    const parsed = parseArchive(raw)
    if (!parsed) throw new Error('model returned no usable JSON')
    const first = turns[0].turn
    const last = turns.at(-1).turn
    return {
      cards: parsed.cards.map(card => ({ ...card, turnStart: first, turnEnd: last })),
      facts: parsed.facts.map(fact => ({ ...fact, turn: last })),
      source: 'model',
    }
  } catch (error) {
    logger?.warn?.(`jinyu-memory: archive fallback: ${error?.message || error}`)
    return { ...fallbackArchive(turns), source: 'local', error: String(error?.message || error) }
  }
}
