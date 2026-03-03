/**
 * Placeholder for dashboard tabs. M1.4.
 */
interface PlaceholderProps {
  title: string
}

export default function Placeholder({ title }: PlaceholderProps) {
  return (
    <div className="space-y-2">
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="text-muted-foreground">Coming soon.</p>
    </div>
  )
}

export function TradesPage() {
  return <Placeholder title="Trades" />
}
export function PositionsPage() {
  return <Placeholder title="Positions" />
}
export function PerformancePage() {
  return <Placeholder title="Performance" />
}
export function AgentsPage() {
  return <Placeholder title="Agents" />
}
export function StrategiesPage() {
  return <Placeholder title="Strategies" />
}
export function ConnectorsPage() {
  return <Placeholder title="Connectors" />
}
export function SkillsPage() {
  return <Placeholder title="Skills" />
}
export function MarketPage() {
  return <Placeholder title="Market Command Center" />
}
export function AdminPage() {
  return <Placeholder title="Admin" />
}
export function NetworkPage() {
  return <Placeholder title="Agent Network" />
}
export function TasksPage() {
  return <Placeholder title="Task Board" />
}
export function SettingsPage() {
  return <Placeholder title="Settings" />
}
