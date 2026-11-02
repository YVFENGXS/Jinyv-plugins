import assert from 'node:assert/strict'
import { test } from 'node:test'

import { archiveBatch, fallbackArchive, parseArchive } from '../lib/archive.js'

test('parseArchive accepts bare, fenced, and prose-wrapped JSON', () => {
  const body = '{"cards":[{"summary":"主人把伞落在柜台","hooks":["旧伞","柜台"],"importance":0.8}],"facts":[{"text":"主人有一把旧伞","kind":"设定","tags":["伞"],"importance":0.9}]}'
  for (const raw of [body, `\`\`\`json\n${body}\n\`\`\``, `好的，结果如下：\n${body}\n以上。`]) {
    const parsed = parseArchive(raw)
    assert.ok(parsed)
    assert.equal(parsed.cards[0].summary, '主人把伞落在柜台')
    assert.deepEqual(parsed.cards[0].hooks, ['旧伞', '柜台'])
    assert.equal(parsed.facts[0].kind, '设定')
  }
})

test('parseArchive rejects unusable output', () => {
  assert.equal(parseArchive('not json'), null)
  assert.equal(parseArchive('{"cards":[]}'), null)
  assert.equal(parseArchive('{"cards":[{"summary":""}]}'), null)
})

test('fallback archive builds a local card from frequent hooks', () => {
  const turns = [
    { turn: 1, user: '我想吃桂花糕，桂花糕还有吗', assistant: '桂花糕卖完了' },
    { turn: 2, user: '那明天给我留一份桂花糕', assistant: '好' },
  ]
  const result = fallbackArchive(turns)
  assert.equal(result.cards.length, 1)
  assert.match(result.cards[0].summary, /桂花糕/)
  assert.ok(result.cards[0].hooks.includes('桂花'))
  assert.equal(result.cards[0].turnStart, 1)
  assert.equal(result.cards[0].turnEnd, 2)
})

test('archiveBatch falls back when no model route is available', async () => {
  const turns = [{ turn: 4, user: '记得把旧伞收好', assistant: '嗯，我收好了' }]
  const result = await archiveBatch({ turns })
  assert.equal(result.source, 'local')
  assert.equal(result.cards.length, 1)
  assert.ok(result.cards[0].summary.length > 0)
  assert.equal(result.cards[0].turnStart, 4)
  assert.equal(result.cards[0].turnEnd, 4)
})

test('archiveBatch uses model output when available', async () => {
  const turns = [{ turn: 7, user: '明天去看灯会', assistant: '我陪你' }]
  const llm = {
    async *stream() {
      yield { type: 'text-delta', text: '{"cards":[{"summary":"两人约好明天看灯会","hooks":["灯会"],"importance":0.7}],"facts":[]}' }
      yield { type: 'finish', reason: { kind: 'stop' } }
    },
  }
  const result = await archiveBatch({ turns, llm, route: { provider: 'p', model: 'm' } })
  assert.equal(result.source, 'model')
  assert.equal(result.cards[0].summary, '两人约好明天看灯会')
  assert.equal(result.cards[0].turnStart, 7)
  assert.equal(result.cards[0].turnEnd, 7)
})
