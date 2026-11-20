import { describe, expect, it } from 'vitest'
import { type ConnectionSignals, ESCALATE_AFTER_MS, evaluateConnection } from './evaluate'

const base: ConnectionSignals = {
  serverConnected: true,
  brokerStatus: 'connected',
  problemSince: null,
  now: 1_000_000,
}

describe('evaluateConnection', () => {
  it('is ok when server and broker are both connected', () => {
    const v = evaluateConnection(base)
    expect(v.severity).toBe('ok')
    expect(v.problem).toBe(false)
  })

  it('is ok when broker status is unknown (not yet reported)', () => {
    expect(evaluateConnection({ ...base, brokerStatus: 'unknown' }).severity).toBe('ok')
  })

  it('warns, without alarm, during a brief broker reconnect', () => {
    const now = base.now
    const v = evaluateConnection({
      ...base,
      brokerStatus: 'reconnecting',
      problemSince: now - 3000,
      now,
    })
    expect(v.severity).toBe('warning')
    expect(v.problem).toBe(true)
    expect(v.title).toMatch(/reconnect/i)
  })

  it('escalates to alarm after the threshold while reconnecting', () => {
    const now = base.now
    const v = evaluateConnection({
      ...base,
      brokerStatus: 'reconnecting',
      problemSince: now - (ESCALATE_AFTER_MS + 1),
      now,
    })
    expect(v.severity).toBe('alarm')
    expect(v.title).toMatch(/lost/i)
  })

  it('alarms immediately when the broker session is down (token dead)', () => {
    const v = evaluateConnection({
      ...base,
      brokerStatus: 'down',
      problemSince: base.now,
      now: base.now,
    })
    expect(v.severity).toBe('alarm')
  })

  it('warns immediately then alarms after threshold when the server is unreachable', () => {
    const now = base.now
    const brief = evaluateConnection({
      ...base,
      serverConnected: false,
      problemSince: now - 2000,
      now,
    })
    expect(brief.severity).toBe('warning')
    expect(brief.title).toMatch(/server/i)

    const long = evaluateConnection({
      ...base,
      serverConnected: false,
      problemSince: now - (ESCALATE_AFTER_MS + 1),
      now,
    })
    expect(long.severity).toBe('alarm')
  })

  it('treats server loss as the priority over broker status', () => {
    const v = evaluateConnection({
      serverConnected: false,
      brokerStatus: 'connected',
      problemSince: base.now,
      now: base.now,
    })
    expect(v.problem).toBe(true)
    expect(v.title).toMatch(/server/i)
  })
})
