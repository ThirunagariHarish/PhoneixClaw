/**
 * Connector TypeScript types.
 */

export type ConnectorType = 'discord' | 'reddit' | 'twitter' | 'unusual_whales' | 'news_api' | 'webhook' | 'alpaca' | 'ibkr' | 'tradier'

export interface Connector {
  id: string
  name: string
  type: ConnectorType
  status: 'connected' | 'disconnected' | 'error'
  config: Record<string, unknown>
  is_active: boolean
  last_connected_at?: string
  error_message?: string
  created_at: string
  updated_at: string
}

export interface ConnectorAgent {
  id: string
  connector_id: string
  agent_id: string
  channel: string  // Legacy field, use channel_id_snowflake instead
  channel_id_snowflake?: string  // Canonical Discord snowflake identifier (migration 048)
  is_active: boolean
  created_at: string
}
