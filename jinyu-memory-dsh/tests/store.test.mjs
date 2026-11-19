import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'

import { createStore } from '../lib/store.js'

function tempHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'jinyu-memory-'))
}

test('store persists turns, cards, facts, and config across reopen', () => {
  const home = tempHome()
  const store = createStore({ sessionId: 'session/one', home })
  store.appendTurn({ turn: 1, user: '我要去看灯会', assistant: '好，我带你去' })
  store.appendTurn({ turn: 2, user: '记得带伞', assistant: '嗯' })
  assert.equal(store.turns.length, 2)
  assert.equal(store.unarchivedTurns().length, 2)

  store.addCards([{ summary: '两人约好去灯会', hooks: ['灯会', '我们'], importance: 0.7 }], 2)
  store.upsertFacts([
    { text: '主人喜欢桂花糕', kind: '设定', tags: ['桂花糕', '点心'], importance: 0.9 },
  ], 2)
  store.upsertFacts([{ text: '主人喜欢桂花糕', tags: ['偏好'], importance: 0.4 }], 2)
  assert.equal(store.facts.length, 1)
  assert.deepEqual(store.facts[0].tags, ['桂花糕', '点心', '偏好'])

  assert.equal(store.markTurnsArchived(1), 1)
  store.updateConfig({ injectBudget: 400 })

  const reopened = createStore({ sessionId: 'session/one', home })
  assert.equal(reopened.turns.length, 2)
  assert.equal(reopened.turns[0].archived, true)
  assert.equal(reopened.turns[1].archived, false)
  assert.equal(reopened.cards.length, 1)
  assert.equal(reopened.config.injectBudget, 400)
  assert.equal(reopened.unarchivedTurns().length, 1)
})

test('store ignores one corrupt JSONL line instead of dropping history', () => {
  const home = tempHome()
  const store = createStore({ sessionId: 'corrupt', home })
  store.appendTurn({ turn: 1, user: '第一轮', assistant: '收到' })
  fs.appendFileSync(path.join(store.dir, 'turns.jsonl'), 'not json\n')
  store.appendTurn({ turn: 2, user: '第二轮', assistant: '好的' })
  const reopened = createStore({ sessionId: 'corrupt', home })
  assert.equal(reopened.turns.length, 2)
})
