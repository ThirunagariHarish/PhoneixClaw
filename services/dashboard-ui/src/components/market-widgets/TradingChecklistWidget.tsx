import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, RotateCcw } from 'lucide-react'

interface CheckItem {
  id: string
  text: string
  checked: boolean
}

const STORAGE_KEY = 'trading-checklist-items'

const DEFAULT_ITEMS: CheckItem[] = [
  { id: '1', text: 'Check pre-market movers & gaps', checked: false },
  { id: '2', text: 'Review economic calendar', checked: false },
  { id: '3', text: 'Set max daily loss limit', checked: false },
  { id: '4', text: 'Identify key support/resistance levels', checked: false },
  { id: '5', text: 'Check VIX & market sentiment', checked: false },
  { id: '6', text: 'Define entry/exit plan for each trade', checked: false },
]

function loadItems(): CheckItem[] {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch {}
  return DEFAULT_ITEMS
}

export default function TradingChecklistWidget() {
  const [items, setItems] = useState<CheckItem[]>(loadItems)
  const [newText, setNewText] = useState('')

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
  }, [items])

  const toggleItem = useCallback((id: string) => {
    setItems(prev => prev.map(item => item.id === id ? { ...item, checked: !item.checked } : item))
  }, [])

  const addItem = useCallback(() => {
    if (!newText.trim()) return
    setItems(prev => [...prev, { id: Date.now().toString(), text: newText.trim(), checked: false }])
    setNewText('')
  }, [newText])

  const removeItem = useCallback((id: string) => {
    setItems(prev => prev.filter(item => item.id !== id))
  }, [])

  const resetAll = useCallback(() => {
    setItems(prev => prev.map(item => ({ ...item, checked: false })))
  }, [])

  const completed = items.filter(i => i.checked).length

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-hidden">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">
          {completed}/{items.length} completed
        </span>
        <button onClick={resetAll} className="text-[10px] text-muted-foreground hover:text-foreground flex items-center gap-1">
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
      </div>

      <div className="w-full bg-muted/30 rounded-full h-1.5">
        <div
          className="bg-green-500 h-1.5 rounded-full transition-all duration-300"
          style={{ width: items.length > 0 ? `${(completed / items.length) * 100}%` : '0%' }}
        />
      </div>

      <div className="flex-1 overflow-auto space-y-0.5">
        {items.map(item => (
          <div key={item.id} className="flex items-center gap-2 px-1 py-1 rounded hover:bg-muted/50 group">
            <input
              type="checkbox"
              checked={item.checked}
              onChange={() => toggleItem(item.id)}
              className="h-3.5 w-3.5 rounded border-border accent-green-500 cursor-pointer"
            />
            <span className={`text-xs flex-1 ${item.checked ? 'line-through text-muted-foreground' : ''}`}>
              {item.text}
            </span>
            <button
              onClick={() => removeItem(item.id)}
              className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-red-400"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>

      <div className="flex gap-1">
        <input
          type="text"
          value={newText}
          onChange={e => setNewText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addItem()}
          placeholder="Add checklist item..."
          className="flex-1 text-xs bg-muted/30 border border-border rounded px-2 py-1 outline-none focus:border-purple-500/40"
        />
        <button
          onClick={addItem}
          className="p-1 rounded border border-border hover:bg-muted/50 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}
