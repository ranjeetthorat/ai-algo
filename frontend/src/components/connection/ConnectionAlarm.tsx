import { useEffect, useState } from 'react'
import { useSocketContext } from '@/components/socket/SocketProvider'
import { evaluateConnection } from '@/lib/connection/evaluate'
import { useConnectionStore } from '@/stores/connectionStore'

/** How often the alarm sound repeats while the link stays down. */
const ALARM_REPEAT_MS = 4000

/**
 * A global banner + audible alarm for a lost connection.
 *
 * Two problems raise it: the broker feed going down (reported by the server over
 * `broker_feed_status`), and this browser losing its SocketIO link to the server
 * (client internet loss on a server deployment). A brief blip shows a quiet
 * "reconnecting" banner; if it persists it escalates to a red banner and a
 * repeating alarm sound, until the link is restored or the trader dismisses the
 * sound. The banner stays visible while the problem lasts.
 */
export function ConnectionAlarm() {
  const serverConnected = useConnectionStore((s) => s.serverConnected)
  const brokerStatus = useConnectionStore((s) => s.brokerStatus)
  const brokerMessage = useConnectionStore((s) => s.brokerMessage)
  const { playAlertSound } = useSocketContext()

  const [problemSince, setProblemSince] = useState<number | null>(null)
  const [silenced, setSilenced] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  const problem = !serverConnected || brokerStatus === 'down' || brokerStatus === 'reconnecting'

  // Mark when the current problem began, and clear it (and the silence) when the
  // link recovers so the next outage alarms fresh.
  useEffect(() => {
    if (problem) {
      setProblemSince((prev) => prev ?? Date.now())
    } else {
      setProblemSince(null)
      setSilenced(false)
    }
  }, [problem])

  // Tick once a second while there is a problem, to drive the escalation timer.
  useEffect(() => {
    if (!problem) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [problem])

  const verdict = evaluateConnection({ serverConnected, brokerStatus, problemSince, now })
  const detail = brokerStatus === 'down' && brokerMessage ? brokerMessage : verdict.detail

  // Repeat the alarm sound while escalated and not silenced.
  useEffect(() => {
    if (verdict.severity !== 'alarm' || silenced) return
    playAlertSound('system')
    const id = setInterval(() => playAlertSound('system'), ALARM_REPEAT_MS)
    return () => clearInterval(id)
  }, [verdict.severity, silenced, playAlertSound])

  if (!verdict.problem) return null

  const isAlarm = verdict.severity === 'alarm'

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed inset-x-0 top-0 z-[100] flex items-center justify-center gap-3 px-4 py-2 text-sm font-medium shadow-md"
      style={{
        backgroundColor: isAlarm ? '#dc2626' : '#f59e0b',
        color: isAlarm ? '#ffffff' : '#1f2937',
      }}
    >
      <span
        aria-hidden
        className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full bg-current ${isAlarm ? 'animate-pulse' : ''}`}
      />
      <span className="text-center">
        <strong>{verdict.title}.</strong> {detail}
      </span>
      {isAlarm && !silenced && (
        <button
          type="button"
          onClick={() => setSilenced(true)}
          className="ml-2 shrink-0 rounded border border-current/40 px-2 py-0.5 text-xs font-semibold hover:bg-black/10"
        >
          Dismiss sound
        </button>
      )}
    </div>
  )
}
