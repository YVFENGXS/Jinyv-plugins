import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'

import { apply } from '../lib/index.js'
import { formatMemory } from '../lib/inject.js'
import { createStore } from '../lib/store.js'
import { estimateTokens } from '../lib/token.js'

function tempHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'jinyu-plugin-'))
}

function userMessage(text) {
  return {
    id: `u-${Math.random()}`,
    role: 'user',
    content: [{ type: 'text', text }],
    source: { kind: 'user' },
  }
}

function fakeCtx() {
  const handlers = new Map()
  const commands = {
    list: [],
    register(definition) {
      commands.list.push(definition)
      return () => {}
    },
  }
  const ctx = {
    logger: { info() {}, warn() {} },
    get() { return undefined },
    on(event, handler) {
      const list = handlers.get(event) ?? []
      list.push(handler)
      handlers.set(event, list)
      return () => {}
    },
    inject(_deps, callback) {
      callback({ effect: fn => fn(), commands })
    },
    effect(fn) { return fn() },
    emit(event, ...args) {
      for (const handler of handlers.get(event) ?? []) handler(...args)
    },
    handlers,
    commands,
  }
  return ctx
}

test('formatMemory keeps the block within budget and drops the lowest score first', () => {
  const long = '这是很长的一段回忆描述，用来测试预算裁剪是否按召回分数从低到高丢弃。'.repeat(3)
  const matched = {
    cards: [1, 2, 3, 4, 5].map(index => ({
      score: 6 - index,
      card: {
        summary: `${index} ${long}`,
        boundary: 'both',
        turnStart: index,
        turnEnd: index,
        createdAt: '2026-11-01T00:00:00.000Z',
      },
    })),
    facts: [],
  }
  const formatted = formatMemory(matched, 120)
  assert.equal(formatted.text, '')
  const roomy = formatMemory(matched, 400)
  assert.ok(roomy.cards.length < 5)
  assert.ok(estimateTokens(roomy.text) <= 400)
})

test('pre-step injects once per turn and again on a new turn', async () => {
  const home = tempHome()
  const previousHome = process.env.DSH_HOME
  process.env.DSH_HOME = home
  try {
    const seed = createStore({ sessionId: 's-pre' })
    seed.addCards([{
      summary: '主人把旧油纸伞落在柜台',
      hooks: ['旧油纸伞', '柜台'],
      importance: 0.8,
      turnStart: 1,
      turnEnd: 1,
    }], 1)

    const ctx = fakeCtx()
    apply(ctx)
    const preStep = ctx.handlers.get('agent/pre-step')[0]
    const base = {
      kind: 'enter',
      messages: [userMessage('旧油纸伞还在柜台吗')],
    }
    const payload = turn => ({
      agent: { session: { id: 's-pre' } },
      turn,
      step: 1,
      signal: new AbortController().signal,
    })

    const first = await preStep(payload(1), async () => base)
    assert.equal(first.messages.length, 2)
    assert.equal(first.messages[1].source.kind, 'jinyu-memory')
    assert.match(first.messages[1].content[0].text, /【长期记忆】/)
    assert.match(first.messages[1].content[0].text, /旧油纸伞/)

    const duplicate = await preStep(payload(1), async () => base)
    assert.equal(duplicate.messages.length, 1)

    const nextTurn = await preStep(payload(2), async () => base)
    assert.equal(nextTurn.messages.length, 2)
  } finally {
    if (previousHome === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = previousHome
  }
})

test('turn events persist and trigger local archiving at the batch threshold', async () => {
  const home = tempHome()
  const previousHome = process.env.DSH_HOME
  process.env.DSH_HOME = home
  try {
    const seed = createStore({ sessionId: 's-turns' })
    seed.updateConfig({ archiveBatch: 2 })
    const ctx = fakeCtx()
    apply(ctx)
    const session = { id: 's-turns' }

    for (const turn of [1, 2]) {
      ctx.emit('session/event', session, { type: 'turn/start', data: { turn } })
      ctx.emit('session/event', session, {
        type: 'user/message',
        data: { source: { kind: 'user' }, content: [{ type: 'text', text: `第${turn}轮我想看灯会` }] },
        time: Date.now(),
      })
      ctx.emit('session/event', session, {
        type: 'assistant/message',
        data: { content: [{ type: 'text', text: `好，第${turn}轮我带你去` }] },
        time: Date.now(),
      })
      ctx.emit('session/event', session, { type: 'turn/end', data: { turn }, time: Date.now() })
    }

    const stored = createStore({ sessionId: 's-turns' })
    assert.equal(stored.turns.length, 2)
    const deadline = Date.now() + 500
    let after = stored
    while (Date.now() < deadline && after.cards.length === 0) {
      await new Promise(resolve => setTimeout(resolve, 20))
      after = createStore({ sessionId: 's-turns' })
    }
    assert.ok(after.cards.length >= 1)
    assert.equal(after.unarchivedTurns().length, 0)
    assert.ok(after.cards.every(card => card.summary.length > 0))
  } finally {
    if (previousHome === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = previousHome
  }
})

test('pre-step skips injection when the session is disabled by /jinyu off', async () => {
  const home = tempHome()
  const previousHome = process.env.DSH_HOME
  process.env.DSH_HOME = home
  try {
    const seed = createStore({ sessionId: 's-command' })
    seed.addCards([{ summary: '主人把旧伞落在柜台', hooks: ['旧伞'], importance: 0.8, turnStart: 1, turnEnd: 1 }], 1)
    const ctx = fakeCtx()
    apply(ctx)
    const command = ctx.commands.list.find(item => item.name === 'jinyu')
    assert.ok(command)
    const invocation = { agent: { session: { id: 's-command' } }, rawInput: ' off ', attachments: [], signal: new AbortController().signal }
    assert.equal(command.handler(invocation).kind, 'success')

    const preStep = ctx.handlers.get('agent/pre-step')[0]
    const result = await preStep(
      { agent: { session: { id: 's-command' } }, turn: 9, step: 1, signal: new AbortController().signal },
      async () => ({ kind: 'enter', messages: [userMessage('旧伞还在吗')] }),
    )
    assert.equal(result.messages.length, 1)
  } finally {
    if (previousHome === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = previousHome
  }
})
