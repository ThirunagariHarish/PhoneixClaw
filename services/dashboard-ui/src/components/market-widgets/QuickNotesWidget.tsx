import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, Pin } from 'lucide-react'

interface Note {
  id: string
  text: string
  color: string
  pinned: boolean
  timestamp: number
}

const STORAGE_KEY = 'trading-quick-notes'
const COLORS = ['bg-yellow-500/10', 'bg-blue-500/10', 'bg-green-500/10', 'bg-pink-500/10', 'bg-purple-500/10']

function loadNotes(): Note[] {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch {}
  return []
}

export default function QuickNotesWidget() {
  const [notes, setNotes] = useState<Note[]>(loadNotes)
  const [newText, setNewText] = useState('')

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notes))
  }, [notes])

  const addNote = useCallback(() => {
    if (!newText.trim()) return
    const note: Note = {
      id: Date.now().toString(),
      text: newText.trim(),
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      pinned: false,
      timestamp: Date.now(),
    }
    setNotes(prev => [note, ...prev])
    setNewText('')
  }, [newText])

  const removeNote = useCallback((id: string) => {
    setNotes(prev => prev.filter(n => n.id !== id))
  }, [])

  const togglePin = useCallback((id: string) => {
    setNotes(prev => prev.map(n => n.id === id ? { ...n, pinned: !n.pinned } : n))
  }, [])

  const sorted = [...notes].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    return b.timestamp - a.timestamp
  })

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-hidden">
      <div className="flex gap-1">
        <input
          type="text"
          value={newText}
          onChange={e => setNewText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addNote()}
          placeholder="Quick note..."
          className="flex-1 text-xs bg-muted/30 border border-border rounded px-2 py-1 outline-none focus:border-purple-500/40"
        />
        <button
          onClick={addNote}
          className="p-1 rounded border border-border hover:bg-muted/50 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-auto space-y-1">
        {sorted.length === 0 ? (
          <p className="text-[10px] text-muted-foreground text-center py-4">
            No notes yet. Add trade ideas, reminders, or observations.
          </p>
        ) : (
          sorted.map(note => (
            <div
              key={note.id}
              className={`${note.color} rounded px-2 py-1.5 group relative border border-transparent hover:border-border/50`}
            >
              <p className="text-xs pr-10 whitespace-pre-wrap break-words">{note.text}</p>
              <p className="text-[9px] text-muted-foreground mt-1">
                {new Date(note.timestamp).toLocaleString('en-US', {
                  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                })}
              </p>
              <div className="absolute top-1 right-1 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={() => togglePin(note.id)}
                  className={`p-0.5 rounded hover:bg-background/50 ${note.pinned ? 'text-purple-400' : 'text-muted-foreground'}`}
                >
                  <Pin className="h-3 w-3" />
                </button>
                <button
                  onClick={() => removeNote(note.id)}
                  className="p-0.5 rounded text-muted-foreground hover:text-red-400 hover:bg-background/50"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="text-[9px] text-muted-foreground text-right">
        {notes.length} note{notes.length !== 1 ? 's' : ''}
      </div>
    </div>
  )
}
