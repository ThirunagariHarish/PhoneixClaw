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
// computeCanAdvance — wizard step 0
// ---------------------------------------------------------------------------
describe('computeCanAdvance – step 0', () => {
  it('canAdvance_step0_trend_no_connector — returns true when type="trend", name set, no connector', () => {
    expect(computeCanAdvance(0, 'My Trend Agent', 'trend', [], null)).toBe(true)
  })

  it('canAdvance_step0_trading_no_connector — returns false when type="trading", no connector', () => {
    expect(computeCanAdvance(0, 'My Trading Agent', 'trading', [], null)).toBe(false)
  })

  it('canAdvance_step0_trading_with_connector_and_channel — returns true', () => {
    expect(
      computeCanAdvance(0, 'My Trading Agent', 'trading', ['connector-1'], {
        channel_id: 'ch-1',
        channel_name: 'general',
      }),
    ).toBe(true)
  })

  it('canAdvance_step0_empty_name — returns false for any type', () => {
    expect(computeCanAdvance(0, '', 'trend', [], null)).toBe(false)
    expect(computeCanAdvance(0, '   ', 'trading', ['c'], { channel_id: 'x', channel_name: 'x' })).toBe(false)
    expect(computeCanAdvance(0, '', 'trading', ['c'], { channel_id: 'x', channel_name: 'x' })).toBe(false)
  })

  it('canAdvance_step0_sentiment_no_connector — returns true when type="sentiment", name set, no connector', () => {
    expect(computeCanAdvance(0, 'Sentiment Agent', 'sentiment', [], null)).toBe(true)
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
