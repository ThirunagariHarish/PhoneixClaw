/**
 * Skills page — skill catalog and agent configuration.
 * Tabs: Skill Catalog, Agent Configuration. Sync skills button.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { FlexCard } from '@/components/ui/FlexCard'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { SidePanel } from '@/components/ui/SidePanel'
import { BookOpen, RefreshCw } from 'lucide-react'

const SKILL_CATEGORIES = ['analysis', 'data', 'execution', 'risk', 'all']

const EMPTY_AGENT_CONFIG = {
  agents_md: '',
  soul_md: '',
  tools_md: '',
}

export default function SkillsPage() {
  const [category, setCategory] = useState('all')
  const [selectedSkill, setSelectedSkill] = useState<{ id: string; name: string; category: string; description: string } | null>(null)
  const [syncing, setSyncing] = useState(false)

  const { data: skills = [] } = useQuery({
    queryKey: ['skills', category],
    queryFn: async () => {
      try {
        const res = await api.get(`/api/v2/skills?category=${category}`)
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const { data: agentConfig = EMPTY_AGENT_CONFIG } = useQuery({
    queryKey: ['agent-config'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/skills/agent-config')
        return res.data ?? EMPTY_AGENT_CONFIG
      } catch {
        return EMPTY_AGENT_CONFIG
      }
    },
  })

  const syncSkills = async () => {
    setSyncing(true)
    try {
      await api.post('/api/v2/skills/sync')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={BookOpen} title="Skills" description="Skill catalog and agent configuration">
        <Button variant="outline" onClick={syncSkills} disabled={syncing}>
          <RefreshCw className={`h-4 w-4 mr-2 ${syncing ? 'animate-spin' : ''}`} />
          Sync Skills
        </Button>
      </PageHeader>

      <Tabs defaultValue="catalog">
        <TabsList>
          <TabsTrigger value="catalog">Skill Catalog</TabsTrigger>
          <TabsTrigger value="config">Agent Configuration</TabsTrigger>
        </TabsList>

        <TabsContent value="catalog" className="mt-4 space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Category" />
              </SelectTrigger>
              <SelectContent>
                {SKILL_CATEGORIES.map((c) => (
                  <SelectItem key={c} value={c}>{c}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
            {skills.map((s: { id: string; name: string; category: string; description: string }) => (
              <FlexCard key={s.id} className="cursor-pointer hover:border-primary/50">
                <div onClick={() => setSelectedSkill(s)}>
                <div className="flex items-start gap-2">
                  <BookOpen className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold truncate">{s.name}</span>
                    <Badge variant="outline" className="ml-2">{s.category}</Badge>
                    <p className="text-sm text-muted-foreground mt-1">{s.description}</p>
                  </div>
                </div>
              </div>
              </FlexCard>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="config" className="mt-4 space-y-4">
          <div className="grid gap-3 sm:gap-4">
            <FlexCard title="AGENTS.md">
              <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-32 font-mono">{agentConfig.agents_md}</pre>
            </FlexCard>
            <FlexCard title="SOUL.md">
              <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-32 font-mono">{agentConfig.soul_md}</pre>
            </FlexCard>
            <FlexCard title="TOOLS.md">
              <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-32 font-mono">{agentConfig.tools_md}</pre>
            </FlexCard>
          </div>
        </TabsContent>
      </Tabs>

      <SidePanel open={!!selectedSkill} onOpenChange={() => setSelectedSkill(null)} title={selectedSkill?.name ?? ''} description={selectedSkill?.category ?? ''}>
        {selectedSkill && (
          <div className="space-y-2">
            <p className="text-sm">{selectedSkill.description}</p>
            <Badge variant="outline">{selectedSkill.category}</Badge>
          </div>
        )}
      </SidePanel>
    </div>
  )
}
