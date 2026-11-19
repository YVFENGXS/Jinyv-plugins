/**
 * Jinyu memory as a local DSH plugin.
 *
 * The plugin observes completed turns, archives them into local event cards
 * and facts under `$DSH_HOME/jinyu-memory/`, and injects a bounded memory
 * block before each model step. There is no server, no HTTP surface, and no
 * Python process; the only external capability is the host `llm` service used
 * for optional background summarization.
 *
 * @module jinyu-memory-dsh
 */

import { randomUUID } from 'node:crypto'
import { archiveBatch } from './archive.js'
import { formatMemory } from './inject.js'
import { retrieve } from './recall.js'
import { createStore } from './store.js'

export const name = 'jinyu-memory'

const BUFFER_LIMIT = 4000

function textOf(message) {
  const content = message?.content
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .filter(block => block?.type === 'text' && typeof block.text === 'string')
    .map(block => block.text)
    .join('\n')
}

function lastUserText(messages) {
  for (let i = (messages?.length ?? 0) - 1; i >= 0; i -= 1) {
    const message = messages[i]
    if (message?.role !== 'user') continue
    if (message?.source?.kind !== 'user') continue
    const text = textOf(message).trim()
    if (text) return text.slice(0, 1000)
  }
  return ''
}

function memoryMessage(text) {
  return {
    id: randomUUID(),
    role: 'user',
    content: [{ type: 'text', text }],
    source: {
      kind: 'jinyu-memory',
      form: 'snapshot',
      sections: [{ name: 'jinyu-memory', text }],
    },
  }
}

function clip(value, limit) {
  return String(value ?? '').trim().slice(0, limit)
}

/**
 * Register the plugin with the host context.
 * @param {object} ctx - DSH plugin context.
 * @returns {void}
 */
export function apply(ctx) {
  const sessions = new Map()

  function stateFor(session) {
    let state = sessions.get(session.id)
    if (!state) {
      state = {
        session,
        store: createStore({ sessionId: session.id }),
        agent: undefined,
        buffer: { user: '', assistant: '' },
        archiving: undefined,
        abort: new AbortController(),
        lastHash: '',
        lastHashTurn: -1,
      }
      sessions.set(session.id, state)
    }
    return state
  }

  async function maybeArchive(state) {
    if (state.archiving || !state.store.config.enabled) return
    const pending = state.store.unarchivedTurns()
    if (pending.length < state.store.config.archiveBatch) return
    const lastTurn = pending.at(-1)
    const task = archiveBatch({
      turns: pending,
      llm: ctx.get('llm'),
      route: state.agent?.model?.current?.(),
      signal: state.abort.signal,
      logger: ctx.logger,
    }).then(result => {
      if (state.abort.signal.aborted) return
      state.store.addCards(result.cards, lastTurn.turn)
      state.store.upsertFacts(result.facts, lastTurn.turn)
      state.store.markTurnsArchived(lastTurn.idx)
    }).catch(error => {
      ctx.logger?.warn?.(`jinyu-memory: archive failed: ${error?.message || error}`)
    }).finally(() => {
      state.archiving = undefined
      if (state.store.unarchivedTurns().length >= state.store.config.archiveBatch) {
        void maybeArchive(state)
      }
    })
    state.archiving = task
  }

  ctx.on('agent/created', ({ agent }) => {
    stateFor(agent.session).agent = agent
  })

  ctx.on('session/event', (session, event) => {
    const state = stateFor(session)
    if (event.type === 'turn/start') {
      state.buffer = { user: '', assistant: '' }
      return
    }
    if (event.type === 'user/message') {
      if (event.data?.source?.kind === 'user') {
        state.buffer.user = clip(`${state.buffer.user}\n${textOf(event.data)}`, BUFFER_LIMIT)
      }
      return
    }
    if (event.type === 'assistant/message') {
      state.buffer.assistant = clip(`${state.buffer.assistant}\n${textOf(event.data)}`, BUFFER_LIMIT)
      return
    }
    if (event.type === 'turn/end') {
      const buffered = state.buffer
      state.buffer = { user: '', assistant: '' }
      if (!buffered.user.trim() && !buffered.assistant.trim()) return
      state.store.appendTurn({
        turn: event.data?.turn,
        user: buffered.user,
        assistant: buffered.assistant,
        createdAt: new Date(event.time ?? Date.now()).toISOString(),
      })
      void maybeArchive(state)
    }
  })

  ctx.on('agent/pre-step', async (payload, next) => {
    const decision = await next()
    if (decision.kind === 'reject') return decision
    if (payload.signal?.aborted) return decision
    const state = stateFor(payload.agent.session)
    state.agent = payload.agent
    if (!state.store.config.enabled) return decision
    const query = lastUserText(decision.messages)
    if (!query) return decision
    const snapshot = state.store.snapshot()
    const matched = retrieve(snapshot, query, {
      limit: state.store.config.recallLimit,
      factLimit: state.store.config.maxFacts,
    })
    if (matched.cards.length === 0 && matched.facts.length === 0) return decision
    const formatted = formatMemory(matched, state.store.config.injectBudget)
    if (!formatted.text) return decision
    if (formatted.hash === state.lastHash && state.lastHashTurn === payload.turn) return decision
    state.lastHash = formatted.hash
    state.lastHashTurn = payload.turn
    return { ...decision, messages: [...decision.messages, memoryMessage(formatted.text)] }
  })

  ctx.on('session/disposed', (session) => {
    const state = sessions.get(session.id)
    if (!state) return
    state.abort.abort()
    sessions.delete(session.id)
  })

  ctx.inject(['commands'], (scope) => {
    scope.effect(() => scope.commands.register({
      name: 'jinyu',
      description: 'Inspect or toggle Jinyu memory for this session',
      handler: (invocation) => {
        try {
          const state = stateFor(invocation.agent.session)
          const action = invocation.rawInput.trim().toLowerCase()
          if (action === 'on' || action === 'off') {
            state.store.updateConfig({ enabled: action === 'on' })
            return { kind: 'success', text: `jinyu-memory: ${action}` }
          }
          if (action === '' || action === 'status') {
            const unarchived = state.store.unarchivedTurns().length
            return {
              kind: 'success',
              text: `jinyu-memory: ${state.store.config.enabled ? 'on' : 'off'} · `
                + `${state.store.cards.length} cards · ${state.store.facts.length} facts · `
                + `${unarchived} pending turns`,
            }
          }
          return { kind: 'error', text: 'usage: /jinyu [on|off|status]' }
        } catch (error) {
          return { kind: 'error', text: `jinyu-memory: ${error?.message || error}` }
        }
      },
    }))
  })
}
