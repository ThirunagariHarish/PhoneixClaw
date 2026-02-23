import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { MessageSquare, RefreshCw, Loader2, Inbox, Search, XCircle } from 'lucide-react'

interface Source {
  id: string
  display_name: string
  source_type: string
  enabled: boolean
  connection_status: string
}

interface RawMsg {
  id: string
  data_source_id: string | null
  source_type: string
  channel_name: string | null
  author: string | null
  content: string
  source_message_id: string | null
  created_at: string | null
}

export default function RawMessages() {
  const [selectedSource, setSelectedSource] = useState<string>('all')
  const [searchText, setSearchText] = useState('')
  const [page, setPage] = useState(0)
  const limit = 50

  const { data: sources } = useQuery<Source[]>({
    queryKey: ['sources'],
    queryFn: () => axios.get('/api/v1/sources').then((r) => r.data),
  })

  useEffect(() => {
    setPage(0)
  }, [selectedSource, searchText])

  const { data: msgData, isLoading, isError, refetch, isFetching } = useQuery<{ total: number; messages: RawMsg[] }>({
    queryKey: ['raw-messages', selectedSource, page],
    queryFn: () => {
      const params: Record<string, string | number> = { limit, offset: page * limit }
      if (selectedSource !== 'all') params.source_id = selectedSource
      return axios.get('/api/v1/messages', { params }).then((r) => r.data)
    },
    refetchInterval: 10_000,
  })

  const allMessages = msgData?.messages ?? []
  const messages = searchText
    ? allMessages.filter(m =>
        m.content.toLowerCase().includes(searchText.toLowerCase()) ||
        (m.author && m.author.toLowerCase().includes(searchText.toLowerCase())) ||
        (m.channel_name && m.channel_name.toLowerCase().includes(searchText.toLowerCase()))
      )
    : allMessages
  const total = msgData?.total ?? 0
  const totalPages = Math.ceil(total / limit)

  const formatTime = (iso: string | null) => {
    if (!iso) return '—'
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">View all raw messages pulled from your data sources</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search messages, authors, channels..."
              className="pl-9 w-[250px]"
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
            />
          </div>
          <Select value={selectedSource} onValueChange={setSelectedSource}>
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder="Filter by source" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Sources</SelectItem>
              {(sources ?? []).map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="icon" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <Badge variant="outline">{total} message{total !== 1 ? 's' : ''}</Badge>
        <span className="text-xs">Auto-refreshes every 10s</span>
      </div>

      {isError ? (
        <Card className="border-destructive/30">
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <XCircle className="h-10 w-10 text-destructive mb-3" />
            <p className="text-destructive font-medium">Failed to load messages</p>
            <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>Retry</Button>
          </CardContent>
        </Card>
      ) : isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : messages.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Inbox className="h-12 w-12 text-muted-foreground/50 mb-4" />
            <p className="text-muted-foreground font-medium">No messages yet</p>
            <p className="text-sm text-muted-foreground/70 mt-1">
              {selectedSource === 'all'
                ? 'Messages will appear here once your data sources start ingesting.'
                : 'No messages from this source yet. Make sure the source is connected and active.'}
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <ScrollArea className="h-[calc(100vh-320px)]">
            <div className="space-y-2">
              {messages.map((msg) => (
                <Card key={msg.id} className="hover:bg-accent/30 transition-colors">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-start gap-3 min-w-0 flex-1">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 mt-0.5">
                          <MessageSquare className="h-4 w-4 text-primary" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap mb-1">
                            {msg.author && (
                              <span className="text-sm font-semibold">{msg.author}</span>
                            )}
                            {msg.channel_name && (
                              <Badge variant="outline" className="text-xs font-normal">
                                #{msg.channel_name}
                              </Badge>
                            )}
                            <Badge variant="secondary" className="text-xs capitalize">
                              {msg.source_type}
                            </Badge>
                          </div>
                          <p className="text-sm whitespace-pre-wrap break-words">{msg.content}</p>
                        </div>
                      </div>
                      <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
                        {formatTime(msg.created_at)}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </ScrollArea>

          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-2">
              <p className="text-sm text-muted-foreground">
                Page {page + 1} of {totalPages}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page + 1 >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
