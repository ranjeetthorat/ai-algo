import { create } from 'zustand'

/** Broker-feed status as reported by the server (`broker_feed_status` event). */
export type BrokerStatus = 'connected' | 'reconnecting' | 'down' | 'unknown'

interface ConnectionStore {
  /** Whether this browser's SocketIO link to the server is up. On a server
   *  deployment, false means the client lost its own internet. On desktop with
   *  the internet off, this stays true because the server is local. */
  serverConnected: boolean
  /** The server's broker link health. */
  brokerStatus: BrokerStatus
  /** A trader-facing message from the server (e.g. session expired). */
  brokerMessage: string
  setServerConnected: (connected: boolean) => void
  setBrokerStatus: (status: BrokerStatus, message?: string) => void
}

export const useConnectionStore = create<ConnectionStore>((set) => ({
  // Optimistic: assume healthy until told otherwise, so the alarm never flashes
  // on first mount before the socket has finished connecting.
  serverConnected: true,
  brokerStatus: 'unknown',
  brokerMessage: '',
  setServerConnected: (connected) => set({ serverConnected: connected }),
  setBrokerStatus: (status, message = '') => set({ brokerStatus: status, brokerMessage: message }),
}))
