/**
 * Token estimation for the injection budget.
 *
 * No tokenizer dependency: CJK characters cost about one token each, while
 * Latin text is estimated at four characters per token. The value is only used
 * to bound a prompt section, never for billing or truncation of durable data.
 *
 * @module jinyu-memory-dsh/token
 */

const CJK = /[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\u3000-\u303f]/u

/**
 * Estimate the token count of a string.
 * @param {string} text - text to measure.
 * @returns {number} estimated tokens, always non-negative.
 */
export function estimateTokens(text) {
  let cjk = 0
  let other = 0
  for (const ch of String(text ?? '')) {
    if (CJK.test(ch)) cjk += 1
    else other += 1
  }
  return Math.ceil(cjk + other / 4)
}

/**
 * Keep a prefix that fits the token budget, appending an ellipsis when cut.
 * @param {string} text - source text.
 * @param {number} maxTokens - positive token budget.
 * @param {string} [suffix] - marker appended after truncation.
 * @returns {string} the original text or a truncated prefix.
 */
export function truncateToTokens(text, maxTokens, suffix = '…') {
  const source = String(text ?? '')
  const budget = Math.max(1, Math.floor(Number(maxTokens) || 1))
  if (estimateTokens(source) <= budget) return source
  let out = ''
  let used = 0
  for (const ch of source) {
    const cost = CJK.test(ch) ? 1 : 0.25
    if (used + cost > budget - estimateTokens(suffix)) break
    out += ch
    used += cost
  }
  return out + suffix
}
