import { Database, Cog, Brain, Wallet, GitBranch, Clock } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'

interface PaletteItem {
  type: string
  label: string
  subtype: string
  icon: React.ElementType
  color: string
  category: string
}

const PALETTE_ITEMS: PaletteItem[] = [
  { type: 'dataSource', label: 'Discord', subtype: 'discord', icon: Database, color: 'border-blue-500/40 bg-blue-500/10 text-blue-600', category: 'Data Sources' },
  { type: 'dataSource', label: 'Sentiment Feed', subtype: 'sentiment', icon: Database, color: 'border-blue-500/40 bg-blue-500/10 text-blue-600', category: 'Data Sources' },
  { type: 'dataSource', label: 'News Feed', subtype: 'news', icon: Database, color: 'border-blue-500/40 bg-blue-500/10 text-blue-600', category: 'Data Sources' },
  { type: 'dataSource', label: 'Chat Input', subtype: 'chat', icon: Database, color: 'border-blue-500/40 bg-blue-500/10 text-blue-600', category: 'Data Sources' },
  { type: 'processing', label: 'Trade Parser', subtype: 'parser', icon: Cog, color: 'border-green-500/40 bg-green-500/10 text-green-600', category: 'Processing' },
  { type: 'processing', label: 'Sentiment Analyzer', subtype: 'sentiment_analyzer', icon: Cog, color: 'border-green-500/40 bg-green-500/10 text-green-600', category: 'Processing' },
  { type: 'processing', label: 'Ticker Extractor', subtype: 'ticker_extractor', icon: Cog, color: 'border-green-500/40 bg-green-500/10 text-green-600', category: 'Processing' },
  { type: 'aiModel', label: 'LLM (Mistral)', subtype: 'mistral', icon: Brain, color: 'border-purple-500/40 bg-purple-500/10 text-purple-600', category: 'AI Models' },
  { type: 'aiModel', label: 'Option Chain Analyzer', subtype: 'option_analyzer', icon: Brain, color: 'border-purple-500/40 bg-purple-500/10 text-purple-600', category: 'AI Models' },
  { type: 'aiModel', label: 'AI Trade Recommender', subtype: 'trade_recommender', icon: Brain, color: 'border-purple-500/40 bg-purple-500/10 text-purple-600', category: 'AI Models' },
  { type: 'broker', label: 'Trading Account', subtype: '', icon: Wallet, color: 'border-orange-500/40 bg-orange-500/10 text-orange-600', category: 'Execution' },
  { type: 'control', label: 'Condition', subtype: 'condition', icon: GitBranch, color: 'border-gray-500/40 bg-gray-500/10 text-gray-600', category: 'Control' },
  { type: 'control', label: 'Delay', subtype: 'delay', icon: Clock, color: 'border-gray-500/40 bg-gray-500/10 text-gray-600', category: 'Control' },
  { type: 'control', label: 'Market Hours', subtype: 'market_hours', icon: Clock, color: 'border-gray-500/40 bg-gray-500/10 text-gray-600', category: 'Control' },
]

interface Props {
  onDragStart: (item: PaletteItem) => void
}

export function NodePalette({ onDragStart }: Props) {
  const categories = [...new Set(PALETTE_ITEMS.map(i => i.category))]

  return (
    <div className="w-56 border-r bg-muted/30 flex flex-col">
      <div className="p-3 border-b">
        <h3 className="text-sm font-semibold">Components</h3>
        <p className="text-[10px] text-muted-foreground">Drag to canvas</p>
      </div>
      <ScrollArea className="flex-1 p-2">
        {categories.map(cat => (
          <div key={cat} className="mb-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-1 mb-1.5">{cat}</p>
            <div className="space-y-1">
              {PALETTE_ITEMS.filter(i => i.category === cat).map((item, idx) => {
                const Icon = item.icon
                return (
                  <div
                    key={`${item.type}-${idx}`}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData('application/pipeline-node', JSON.stringify(item))
                      onDragStart(item)
                    }}
                    className={`flex items-center gap-2 rounded-md border px-2.5 py-2 cursor-grab active:cursor-grabbing transition-colors hover:shadow-sm ${item.color}`}
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="text-xs font-medium truncate">{item.label}</span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </ScrollArea>
    </div>
  )
}

export type { PaletteItem }
