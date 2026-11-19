/**
 * Local durable storage for one DSH session.
 *
 * Everything lives under `$DSH_HOME/jinyu-memory/sessions/<id>/`; no HTTP
 * service and no external database. Writes are synchronous and atomic for
 * whole-file rewrites so a crashed step cannot leave a half-written index.
 *
 * @module jinyu-memory-dsh/store
 */

import { createHash, randomUUID } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

/** Per-session tunables; persisted beside the session data. */
export const DEFAULT_CONFIG = Object.freeze({
  enabled: true,
  archiveBatch: 12,
  recallLimit: 2,
  injectBudget: 900,
  maxFacts: 6,
})

const CTRL = /[\u0000-\u001f\u202a-\u202e\u2066-\u2069]/g
const BOUNDARIES = new Set(['self', 'player', 'both'])
const KINDS = new Set(['设定', '事件', '临时'])

/**
 * Resolve the memory root, honoring an explicit home for tests.
 * @param {string} [home] - override for `$DSH_HOME`.
 * @returns {string} absolute directory holding all sessions.
 */
export function memoryRoot(home = process.env.DSH_HOME || path.join(os.homedir(), '.dsh')) {
  return path.join(home, 'jinyu-memory', 'sessions')
}

/**
 * Map an arbitrary session id to a stable, filesystem-safe directory name.
 * @param {string} sessionId - live session id.
 * @returns {string} safe directory component.
 */
export function sessionDirName(sessionId) {
  const raw = String(sessionId || 'session')
  const safe = raw.replace(/[^\w.-]/g, '_').slice(0, 64)
  if (safe === raw && raw.length <= 64) return safe
  return `${safe}-${createHash('sha256').update(raw).digest('hex').slice(0, 8)}`
}

function makeId(prefix) {
  return `${prefix}-${randomUUID().slice(0, 8)}`
}

function clean(value, limit = 0) {
  const text = String(value ?? '').replace(CTRL, '').trim()
  return limit > 0 ? text.slice(0, limit) : text
}

function clamp(value, fallback = 0.5) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.round(Math.max(0, Math.min(1, n)) * 1000) / 1000
}

function integer(value, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : fallback
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true })
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch {
    return fallback
  }
}

function writeFileAtomic(file, contents) {
  const tmp = `${file}.tmp-${process.pid}-${randomUUID().slice(0, 8)}`
  fs.writeFileSync(tmp, contents, 'utf8')
  fs.renameSync(tmp, file)
}

function writeJsonAtomic(file, value) {
  writeFileAtomic(file, `${JSON.stringify(value, null, 2)}\n`)
}

function readTurns(file) {
  let raw = ''
  try {
    raw = fs.readFileSync(file, 'utf8')
  } catch {
    return []
  }
  const turns = []
  for (const line of raw.split('\n')) {
    if (!line.trim()) continue
    try {
      const turn = JSON.parse(line)
      if (turn && typeof turn === 'object') turns.push(turn)
    } catch {
      // One corrupt line must not hide the rest of the session history.
    }
  }
  return turns
}

function normalizeCard(raw, fallbackTurn) {
  const card = raw && typeof raw === 'object' ? raw : {}
  const turnStart = integer(card.turnStart ?? card.turn_start, fallbackTurn)
  const turnEnd = integer(card.turnEnd ?? card.turn_end, fallbackTurn)
  const hooks = (Array.isArray(card.hooks ?? card.entity_hooks) ? card.hooks ?? card.entity_hooks : [])
    .map(hook => clean(hook, 8))
    .filter(hook => hook.length >= 1)
  const relHooks = (Array.isArray(card.relHooks ?? card.rel_hooks) ? card.relHooks ?? card.rel_hooks : [])
    .map(hook => clean(hook, 16))
    .filter(Boolean)
  return {
    id: String(card.id || makeId('C')),
    summary: clean(card.summary, 200),
    hooks: [...new Set(hooks)].slice(0, 8),
    relHooks: [...new Set(relHooks)].slice(0, 5),
    importance: clamp(card.importance, 0.5),
    boundary: BOUNDARIES.has(card.boundary) ? card.boundary : 'both',
    turnStart: Math.min(turnStart, turnEnd),
    turnEnd,
    createdAt: String(card.createdAt || new Date().toISOString()),
    mentions: integer(card.mentions ?? 1, 1),
    verified: integer(card.verified, 0),
  }
}

function normalizeFact(raw, fallbackTurn) {
  const fact = raw && typeof raw === 'object' ? raw : { text: raw }
  return {
    id: String(fact.id || makeId('F')),
    text: clean(fact.text ?? fact.fact, 40),
    tags: [...new Set((Array.isArray(fact.tags) ? fact.tags : [])
      .map(tag => clean(tag, 12))
      .filter(Boolean))].slice(0, 4),
    kind: KINDS.has(fact.kind ?? fact.category) ? fact.kind ?? fact.category : '',
    importance: clamp(fact.importance, 0.5),
    turn: integer(fact.turn, fallbackTurn),
    createdAt: String(fact.createdAt || new Date().toISOString()),
  }
}

/**
 * Open one session store and load its indexes into memory.
 * @param {object} options - store options.
 * @param {string} options.sessionId - live DSH session id.
 * @param {string} [options.home] - memory home override, defaults to `$DSH_HOME`.
 * @returns {object} store handle with synchronous read/write operations.
 */
export function createStore({ sessionId, home }) {
  const dir = path.join(memoryRoot(home), sessionDirName(sessionId))
  ensureDir(dir)
  const turnsFile = path.join(dir, 'turns.jsonl')
  const cardsFile = path.join(dir, 'cards.json')
  const factsFile = path.join(dir, 'facts.json')
  const configFile = path.join(dir, 'config.json')

  const state = {
    turns: readTurns(turnsFile),
    cards: readJson(cardsFile, []),
    facts: readJson(factsFile, []),
    config: { ...DEFAULT_CONFIG, ...(readJson(configFile, {}) || {}) },
  }

  /**
   * Append one completed turn and persist its JSONL line.
   * @param {object} input - turn fields.
   * @param {number} [input.turn] - DSH turn number.
   * @param {string} [input.user] - user text.
   * @param {string} [input.assistant] - assistant text.
   * @param {string} [input.createdAt] - ISO timestamp.
   * @returns {object} the stored turn.
   */
  function appendTurn(input = {}) {
    const turn = {
      idx: state.turns.length + 1,
      turn: integer(input.turn, state.turns.length + 1),
      user: clean(input.user, 4000),
      assistant: clean(input.assistant, 4000),
      createdAt: String(input.createdAt || new Date().toISOString()),
      archived: false,
    }
    state.turns.push(turn)
    fs.appendFileSync(turnsFile, `${JSON.stringify(turn)}\n`, 'utf8')
    return turn
  }

  /**
   * Return turns not yet summarized into event cards.
   * @returns {object[]} unarchived turns in chronological order.
   */
  function unarchivedTurns() {
    return state.turns.filter(turn => !turn.archived)
  }

  /**
   * Mark every turn up to an index as archived and rewrite the JSONL file.
   * @param {number} upToIdx - inclusive turn index.
   * @returns {number} number of turns newly marked.
   */
  function markTurnsArchived(upToIdx) {
    let count = 0
    for (const turn of state.turns) {
      if (!turn.archived && turn.idx <= upToIdx) {
        turn.archived = true
        count += 1
      }
    }
    if (count > 0) {
      writeFileAtomic(turnsFile, `${state.turns.map(turn => JSON.stringify(turn)).join('\n')}\n`)
    }
    return count
  }

  /**
   * Append event cards to the session card index.
   * @param {object[]} cards - raw card fields.
   * @param {number} [fallbackTurn] - turn number used when a card omits bounds.
   * @returns {object[]} normalized stored cards.
   */
  function addCards(cards, fallbackTurn = 0) {
    const stored = (Array.isArray(cards) ? cards : [])
      .map(card => normalizeCard(card, fallbackTurn))
      .filter(card => card.summary)
    if (stored.length === 0) return []
    state.cards.push(...stored)
    writeJsonAtomic(cardsFile, state.cards)
    return stored
  }

  /**
   * Insert facts, merging duplicates by text instead of creating copies.
   * @param {object[]} facts - raw fact fields.
   * @param {number} [fallbackTurn] - turn number used when a fact omits it.
   * @returns {object[]} normalized stored facts.
   */
  function upsertFacts(facts, fallbackTurn = 0) {
    const stored = []
    for (const raw of Array.isArray(facts) ? facts : []) {
      const fact = normalizeFact(raw, fallbackTurn)
      if (!fact.text) continue
      const existing = state.facts.find(item => item.text === fact.text)
      if (existing) {
        existing.importance = Math.max(existing.importance, fact.importance)
        existing.tags = [...new Set([...existing.tags, ...fact.tags])].slice(0, 4)
        if (fact.kind) existing.kind = fact.kind
        stored.push(existing)
        continue
      }
      state.facts.push(fact)
      stored.push(fact)
    }
    if (stored.length > 0) writeJsonAtomic(factsFile, state.facts)
    return stored
  }

  /**
   * Merge a config patch into this session's config and persist it.
   * @param {object} patch - config keys to change.
   * @returns {object} the merged config.
   */
  function updateConfig(patch = {}) {
    state.config = { ...state.config, ...patch }
    writeJsonAtomic(configFile, state.config)
    return state.config
  }

  /**
   * Read a snapshot of loaded turns, cards, and facts.
   * @returns {{turns: object[], cards: object[], facts: object[], config: object}} current indexes.
   */
  function snapshot() {
    return {
      turns: state.turns,
      cards: state.cards,
      facts: state.facts,
      config: state.config,
    }
  }

  return {
    dir,
    appendTurn,
    unarchivedTurns,
    markTurnsArchived,
    addCards,
    upsertFacts,
    updateConfig,
    snapshot,
    get config() { return state.config },
    get turns() { return state.turns },
    get cards() { return state.cards },
    get facts() { return state.facts },
  }
}
