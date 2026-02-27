import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, Edit2 } from 'lucide-react'

interface Shortcut {
  id: string
  keys: string
  action: string
  category: string
}

const STORAGE_KEY = 'trading-keyboard-shortcuts'

const DEFAULT_SHORTCUTS: Shortcut[] = [
  { id: '1', keys: 'Ctrl+Shift+B', action: 'Buy Market Order', category: 'Orders' },
  { id: '2', keys: 'Ctrl+Shift+S', action: 'Sell Market Order', category: 'Orders' },
  { id: '3', keys: 'Ctrl+Shift+L', action: 'Buy Limit Order', category: 'Orders' },
  { id: '4', keys: 'Ctrl+Shift+X', action: 'Cancel All Orders', category: 'Orders' },
  { id: '5', keys: 'Ctrl+Shift+F', action: 'Flatten Position', category: 'Risk' },
  { id: '6', keys: 'Ctrl+Z', action: 'Undo Last Order', category: 'Risk' },
  { id: '7', keys: 'F5', action: 'Refresh Data', category: 'Navigation' },
  { id: '8', keys: 'Space', action: 'Toggle Chart Crosshair', category: 'Charts' },
  { id: '9', keys: 'Alt+1..9', action: 'Switch Chart Timeframe', category: 'Charts' },
]

function loadShortcuts(): Shortcut[] {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch {}
  return DEFAULT_SHORTCUTS
}

export default function KeyboardShortcutsWidget() {
  const [shortcuts, setShortcuts] = useState<Shortcut[]>(loadShortcuts)
  const [adding, setAdding] = useState(false)
  const [newKeys, setNewKeys] = useState('')
  const [newAction, setNewAction] = useState('')
  const [newCategory, setNewCategory] = useState('Orders')

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(shortcuts))
  }, [shortcuts])

  const addShortcut = useCallback(() => {
    if (!newKeys.trim() || !newAction.trim()) return
    setShortcuts(prev => [...prev, { id: Date.now().toString(), keys: newKeys.trim(), action: newAction.trim(), category: newCategory }])
    setNewKeys('')
    setNewAction('')
    setAdding(false)
  }, [newKeys, newAction, newCategory])

  const removeShortcut = useCallback((id: string) => {
    setShortcuts(prev => prev.filter(s => s.id !== id))
  }, [])

  const categories = [...new Set(shortcuts.map(s => s.category))]

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-hidden">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">{shortcuts.length} shortcuts</span>
        <button onClick={() => setAdding(!adding)} className="text-[10px] text-purple-400 hover:text-purple-300 flex items-center gap-0.5">
          {adding ? 'Cancel' : <><Plus className="h-3 w-3" /> Add</>}
        </button>
      </div>

      {adding && (
        <div className="flex flex-col gap-1 p-2 bg-muted/20 rounded border border-border">
          <input type="text" value={newKeys} onChange={e => setNewKeys(e.target.value)} placeholder="Keys (e.g., Ctrl+B)"
            className="text-xs bg-muted/30 border border-border rounded px-2 py-1 outline-none focus:border-purple-500/40" />
          <input type="text" value={newAction} onChange={e => setNewAction(e.target.value)} placeholder="Action description"
            className="text-xs bg-muted/30 border border-border rounded px-2 py-1 outline-none focus:border-purple-500/40" />
          <div className="flex gap-1">
            <select value={newCategory} onChange={e => setNewCategory(e.target.value)}
              className="flex-1 text-xs bg-muted/30 border border-border rounded px-2 py-1 outline-none">
              <option>Orders</option><option>Risk</option><option>Charts</option><option>Navigation</option><option>Custom</option>
            </select>
            <button onClick={addShortcut} className="px-3 py-1 text-xs bg-purple-500/20 border border-purple-500/40 rounded text-purple-400 hover:bg-purple-500/30">Save</button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-auto space-y-3">
        {categories.map(cat => (
          <div key={cat}>
            <p className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">{cat}</p>
            <div className="space-y-0.5">
              {shortcuts.filter(s => s.category === cat).map(s => (
                <div key={s.id} className="flex items-center justify-between px-1 py-1 rounded hover:bg-muted/50 group">
                  <div className="flex items-center gap-2">
                    <kbd className="text-[9px] font-mono bg-muted/40 border border-border rounded px-1.5 py-0.5 text-purple-400">{s.keys}</kbd>
                    <span className="text-[11px]">{s.action}</span>
                  </div>
                  <button onClick={() => removeShortcut(s.id)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-red-400">
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
