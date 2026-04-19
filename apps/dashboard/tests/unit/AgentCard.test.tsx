/**
 * AgentCard unit tests — engine and broker badge rendering.
 *
 * Tests:
 *  - Pipeline engine badge renders with green ML badge
 *  - SDK engine badge renders with blue SDK badge
 *  - Broker badge renders when pipeline engine + broker_account_id present
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AgentCard, type AgentData } from '../../src/pages/Agents'

// Mocks
vi.mock('../../src/lib/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
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

describe('AgentCard – engine and broker badges', () => {
  it('pipeline_badge_renders — shows green ML badge when engine_type=pipeline', () => {
    renderCard(makeAgent({ engine_type: 'pipeline' }))
    expect(screen.getByText('ML')).toBeInTheDocument()
  })

  it('sdk_badge_renders — shows blue SDK badge when engine_type=sdk', () => {
    renderCard(makeAgent({ engine_type: 'sdk' }))
    expect(screen.getByText('SDK')).toBeInTheDocument()
  })

  it('default_sdk_badge_when_no_engine_type — defaults to SDK badge when engine_type missing', () => {
    renderCard(makeAgent({ engine_type: undefined }))
    expect(screen.getByText('SDK')).toBeInTheDocument()
  })

  it('broker_badge_renders_for_pipeline — shows broker badge when pipeline + broker_account_id', async () => {
    renderCard(
      makeAgent({
        engine_type: 'pipeline',
        broker_account_id: 'broker-123',
        broker_type: 'robinhood',
      }),
    )
    // Broker badge should render (may show loading or broker type initially)
    // Since we're mocking API to return empty array, it will show the broker_type fallback
    await screen.findByText(/ROBINHOOD|Broker/i)
  })

  it('no_broker_badge_for_sdk — no broker badge when SDK engine', () => {
    renderCard(
      makeAgent({
        engine_type: 'sdk',
        broker_account_id: 'broker-123',
      }),
    )
    // Should not render BrokerBadge component at all
    expect(screen.queryByText(/ROBINHOOD|IBKR|Broker/i)).not.toBeInTheDocument()
  })
})
