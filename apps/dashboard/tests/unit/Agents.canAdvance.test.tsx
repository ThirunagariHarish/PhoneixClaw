/**
 * Phase 2 unit tests — Agents wizard canAdvance() guard and error-message rendering.
 *
 * Tests:
 *  - computeCanAdvance pure-function logic (step 0, various form states)
 *  - AgentCard renders an error banner when status === "ERROR" and error_message is set
 *  - AgentCard renders no error banner when status === "RUNNING"
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { computeCanAdvance, AgentCard, type AgentData } from '../../src/pages/Agents'

// ---------------------------------------------------------------------------
// Silence unrelated network / router warnings in the test environment
// ---------------------------------------------------------------------------
vi.mock('../../src/lib/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: null }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
  }
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

const noop = () => {}

function renderCard(agent: AgentData) {
  const qc = makeQueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <AgentCard
        agent={agent}
        onSelect={noop}
        onPause={noop}
        onResume={noop}
        onDelete={noop}
        onReview={noop}
        onPromote={noop}
      />
    </QueryClientProvider>,
  )
}

function makeAgent(overrides: Partial<AgentData> = {}): AgentData {
  return {
    id: 'test-id',
    name: 'Test Agent',
    type: 'trading',
    status: 'CREATED',
    config: {},
    created_at: new Date().toISOString(),
    error_message: null,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// computeCanAdvance — wizard steps
// ---------------------------------------------------------------------------
describe('computeCanAdvance – step 0 (engine type)', () => {
  it('canAdvance_step0_always_true — engine type step always advances', () => {
    expect(computeCanAdvance(0, '', 'trading', [], null, undefined, 'sdk')).toBe(true)
    expect(computeCanAdvance(0, '', 'trend', [], null, undefined, 'pipeline')).toBe(true)
  })
})

describe('computeCanAdvance – step 1 (channel)', () => {
  it('canAdvance_step1_trend_no_connector — returns true when type="trend", name set, no connector, SDK engine', () => {
    expect(computeCanAdvance(1, 'My Trend Agent', 'trend', [], null, undefined, 'sdk')).toBe(true)
  })

  it('canAdvance_step1_trading_no_connector — returns false when type="trading", no connector', () => {
    expect(computeCanAdvance(1, 'My Trading Agent', 'trading', [], null, undefined, 'sdk')).toBe(false)
  })

  it('canAdvance_step1_trading_with_connector_and_channel — returns true', () => {
    expect(
      computeCanAdvance(1, 'My Trading Agent', 'trading', ['connector-1'], {
        channel_id: 'ch-1',
        channel_name: 'general',
      }, undefined, 'sdk'),
    ).toBe(true)
  })

  it('canAdvance_step1_empty_name — returns false for any type', () => {
    expect(computeCanAdvance(1, '', 'trend', [], null, undefined, 'sdk')).toBe(false)
    expect(computeCanAdvance(1, '   ', 'trading', ['c'], { channel_id: 'x', channel_name: 'x' }, undefined, 'sdk')).toBe(false)
    expect(computeCanAdvance(1, '', 'trading', ['c'], { channel_id: 'x', channel_name: 'x' }, undefined, 'sdk')).toBe(false)
  })

  it('canAdvance_step1_sentiment_no_connector — returns true when type="sentiment", name set, no connector', () => {
    expect(computeCanAdvance(1, 'Sentiment Agent', 'sentiment', [], null, undefined, 'sdk')).toBe(true)
  })

  it('canAdvance_step1_pipeline_no_broker — returns false when engine=pipeline and no broker_account_id', () => {
    expect(computeCanAdvance(1, 'Pipeline Agent', 'trading', ['c'], { channel_id: 'x', channel_name: 'x' }, undefined, 'pipeline', undefined)).toBe(false)
  })

  it('canAdvance_step1_pipeline_with_broker — returns true when engine=pipeline and broker_account_id set', () => {
    expect(computeCanAdvance(1, 'Pipeline Agent', 'trading', ['c'], { channel_id: 'x', channel_name: 'x' }, undefined, 'pipeline', 'broker-123')).toBe(true)
  })

  it('canAdvance_step1_sdk_no_broker — returns true when SDK engine without broker', () => {
    expect(computeCanAdvance(1, 'SDK Agent', 'trading', ['c'], { channel_id: 'x', channel_name: 'x' }, undefined, 'sdk', undefined)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// AgentCard rendering
// ---------------------------------------------------------------------------
describe('AgentCard – error_message rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('agent_card_renders_error_message — shows error banner when status="ERROR" and error_message set', () => {
    renderCard(
      makeAgent({
        status: 'ERROR',
        error_message: 'Claude SDK unavailable: ANTHROPIC_API_KEY not set',
      }),
    )

    expect(
      screen.getByText('Claude SDK unavailable: ANTHROPIC_API_KEY not set'),
    ).toBeInTheDocument()
  })

  it('agent_card_no_error_message_when_running — no error banner when status="RUNNING"', () => {
    renderCard(makeAgent({ status: 'RUNNING', error_message: null }))

    // Error banner text should not appear
    expect(
      screen.queryByText(/Claude SDK unavailable/i),
    ).not.toBeInTheDocument()
  })

  it('agent_card_no_error_banner_when_error_message_null — ERROR status with null error_message shows no banner text', () => {
    renderCard(makeAgent({ status: 'ERROR', error_message: null }))
    // The error banner requires both status=ERROR and a truthy error_message
    expect(screen.queryByText(/Claude SDK/i)).not.toBeInTheDocument()
  })
})
