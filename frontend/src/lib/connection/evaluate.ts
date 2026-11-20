import type { BrokerStatus } from '@/stores/connectionStore'

/** How long a problem must persist before the alarm escalates to sound. */
export const ESCALATE_AFTER_MS = 15_000

export type Severity = 'ok' | 'warning' | 'alarm'

export interface ConnectionSignals {
  serverConnected: boolean
  brokerStatus: BrokerStatus
  /** When the current problem began (ms epoch), or null if there is no problem. */
  problemSince: number | null
  now: number
}

export interface ConnectionVerdict {
  severity: Severity
  /** True while anything is wrong (server unreachable, or broker not connected). */
  problem: boolean
  title: string
  detail: string
}

/**
 * Decide what the connection banner should show, purely from the signals.
 *
 * - server unreachable, or broker "down" (token dead) -> escalate to alarm at
 *   once; these do not self-heal quickly and the trader must act.
 * - broker "reconnecting" -> a quiet warning first, escalating to alarm only
 *   after ESCALATE_AFTER_MS, so a brief blip does not cry wolf.
 * - everything healthy -> ok.
 */
export function evaluateConnection(s: ConnectionSignals): ConnectionVerdict {
  if (!s.serverConnected) {
    const elapsed = s.problemSince === null ? 0 : s.now - s.problemSince
    return {
      severity: elapsed >= ESCALATE_AFTER_MS ? 'alarm' : 'warning',
      problem: true,
      title: 'Connection to server lost',
      detail: 'This device is not reaching the server. Check your internet connection.',
    }
  }

  if (s.brokerStatus === 'down') {
    return {
      severity: 'alarm',
      problem: true,
      title: 'Broker connection lost',
      detail: 'The broker session has ended. Log in again to restore live data and orders.',
    }
  }

  if (s.brokerStatus === 'reconnecting') {
    const elapsed = s.problemSince === null ? 0 : s.now - s.problemSince
    return {
      severity: elapsed >= ESCALATE_AFTER_MS ? 'alarm' : 'warning',
      problem: true,
      title: elapsed >= ESCALATE_AFTER_MS ? 'Broker connection lost' : 'Reconnecting to broker',
      detail:
        elapsed >= ESCALATE_AFTER_MS
          ? 'The broker feed has been down for a while. Live prices and orders may be stale.'
          : 'The broker feed dropped and is reconnecting.',
    }
  }

  return { severity: 'ok', problem: false, title: '', detail: '' }
}
