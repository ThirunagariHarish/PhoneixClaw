/**
 * M1.1 TDD: App renders without crash.
 * Reference: ImplementationPlan.md Section 5, M1.1 Test List.
 */
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from '../../src/App'

describe('App', () => {
  it('renders without crashing', () => {
    render(<App />)
    // Unauthenticated: login page (branding text evolved from "Phoenix v2")
    expect(screen.getByRole('heading', { name: /Phoenix Claw/i })).toBeInTheDocument()
  })
})
