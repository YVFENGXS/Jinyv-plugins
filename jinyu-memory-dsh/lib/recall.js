/**
 * Deterministic hook recall over local event cards and facts.
 *
 * No embedding service and no tokenizer: stored hooks are expanded into
 * whole-term, all-bigram, and trailing-character keys, then looked up as
 * substrings of the current user text. Chinese noun heads sit at the end of a
 * phrase, so the trailing-character fallback keeps short hooks recallable while
 * a stop-character table suppresses noise such as `客人 → 人`.
 *
 * @module jinyu-memory-dsh/recall
 */

/** Characters discarded by the trailing-character fallback. */
export const STOP_CHARS = new Set(
  '人的了是个这那我你他她它一不有在上下来说时里面地得着过又很就都也还只把被给和与住吧呢啊'
  + '子儿头们么之其此某每另点数化',
)

const CTRL = /[\u0000-\u001f\u202a-\u202e\u2066-\u2069]+/g
const SUSPICIOUS = /忽略(以上|之前|先前|上述)|ignore\s+(all\s+)?(previous|above)|system\s*:|assistant\s*:|<\|.*?\|>|you\s+are\s+now|忽略你的(设定|规则)/i

const MIN_ABS = 0.6
const MIN_REL = 0.3
const MIN_FACT = 0.5

/**
 * Strip control and bidi characters and trim surrounding whitespace.
 * @param {string} text - untrusted text.
 * @param {number} [limit] - maximum characters to keep.
 * @returns {string} cleaned text.
 */
export function cleanText(text, limit = 0) {
  const value = String(text ?? '').replace(CTRL, '').trim()
  return limit > 0 ? value.slice(0, limit) : value
}

/**
 * Detect obvious instruction-override attempts in model-produced summaries.
 * @param {string} text - card summary or fact text.
 * @returns {boolean} whether the text should be kept out of the prompt.
 */
export function suspicious(text) {
  return SUSPICIOUS.test(cleanText(text))
}

/**
 * Expand a stored hook into matchable keys with descending weight.
 * @param {string} term - one stored hook.
 * @returns {Array<[string, number]>} key and weight pairs.
 */
export function coreKeys(term) {
  const keys = [[term, 3 + 0.2 * term.length]]
  if (term.length >= 3) {
    for (let i = 0; i < term.length - 1; i += 1) keys.push([term.slice(i, i + 2), 1.2])
  }
  if (term.length >= 2 && !STOP_CHARS.has(term.at(-1))) {
    keys.push([term.at(-1), 0.6])
  }
  return keys
}

function bestHookScore(hooks, query) {
  let best = 0
  for (const hook of Array.isArray(hooks) ? hooks : []) {
    const term = cleanText(hook)
    if (!term) continue
    for (const [key, weight] of coreKeys(term)) {
      if (key && query.includes(key) && weight > best) best = weight
    }
  }
  return best
}

function relScore(hooks, query) {
  let best = 0
  for (const hook of Array.isArray(hooks) ? hooks : []) {
    const term = cleanText(hook)
    if (term.length >= 2 && term.length < 8 && query.includes(term)) best = Math.max(best, 1.2)
  }
  return best
}

/**
 * Score one event card against the current user text.
 * @param {object} card - stored event card.
 * @param {string} query - current user text.
 * @returns {number} evidence score; 0 means no literal overlap.
 */
export function scoreCard(card, query) {
  if (!query) return 0
  return Math.max(bestHookScore(card.hooks, query), relScore(card.relHooks, query))
}

function factScore(fact, query) {
  let best = 0
  for (const tag of Array.isArray(fact.tags) ? fact.tags : []) {
    const term = cleanText(tag)
    if (!term) continue
    if (term.length >= 2 && query.includes(term)) best = Math.max(best, 3)
    for (const [key, weight] of coreKeys(term)) {
      if (key.length >= 2 && query.includes(key)) best = Math.max(best, weight)
    }
  }
  const text = cleanText(fact.text)
  if (text.length >= 2) {
    for (let i = 0; i < text.length - 1; i += 1) {
      const key = text.slice(i, i + 2)
      if (query.includes(key) && best < 0.6) best = 0.6
    }
  }
  return best
}

function order(card) {
  return [card.turnEnd ?? 0, card.importance ?? 0.5]
}

/**
 * Retrieve event cards and facts for one user text.
 *
 * Ordering is score, then repeated confirmation (`mentions + verified`),
 * then importance, then recency. Cards private to the player and cards whose
 * summaries look like prompt injection never enter the candidate set.
 *
 * @param {object} data - session indexes.
 * @param {object[]} data.cards - stored event cards.
 * @param {object[]} data.facts - stored facts.
 * @param {string} query - current user text.
 * @param {object} [options] - retrieval options.
 * @param {number} [options.limit] - maximum cards to return.
 * @param {number} [options.factLimit] - maximum facts to return.
 * @param {Iterable<string>} [options.excludeIds] - card ids already injected.
 * @returns {{cards: Array<{score: number, card: object}>, facts: Array<{score: number, fact: object}>}} matches.
 */
export function retrieve(data, query, options = {}) {
  const text = cleanText(query)
  if (!text) return { cards: [], facts: [] }
  const limit = Math.max(1, Math.floor(Number(options.limit) || 2))
  const factLimit = Math.max(1, Math.floor(Number(options.factLimit) || 4))
  const exclude = new Set(options.excludeIds || [])
  const scored = []
  for (const card of data.cards || []) {
    if (exclude.has(card.id)) continue
    if ((card.boundary || 'both') === 'player') continue
    if (suspicious(card.summary)) continue
    const score = scoreCard(card, text)
    if (score > 0) scored.push({ score, card })
  }
  if (scored.length > 0) {
    const floor = Math.max(MIN_ABS, scored.reduce((top, hit) => Math.max(top, hit.score), 0) * MIN_REL)
    const kept = scored.filter(hit => hit.score >= floor)
    kept.sort((a, b) => (b.score - a.score)
      || ((b.card.mentions || 0) + (b.card.verified || 0) - ((a.card.mentions || 0) + (a.card.verified || 0)))
      || ((b.card.importance || 0) - (a.card.importance || 0))
      || (order(b.card)[0] - order(a.card)[0]))
    scored.length = 0
    scored.push(...kept.slice(0, limit))
  }
  const facts = []
  for (const fact of data.facts || []) {
    if (suspicious(fact.text)) continue
    const score = factScore(fact, text)
    if (score >= MIN_FACT) facts.push({ score, fact })
  }
  facts.sort((a, b) => (b.score - a.score)
    || ((b.fact.importance || 0) - (a.fact.importance || 0))
    || ((b.fact.turn || 0) - (a.fact.turn || 0)))
  return { cards: scored, facts: facts.slice(0, factLimit) }
}
