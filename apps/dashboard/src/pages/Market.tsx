/**
 * Market Command Center — draggable/resizable widget grid with tabs.
 * MCP-3: Symbol Link Groups, MCP-4: Watchlist, MCP-5: Layout Presets, MCP-9: Lazy Loading.
 */
import React, { useState, useCallback, useMemo, useRef, useEffect, Suspense } from 'react'
import { ResponsiveGridLayout, useContainerWidth, type LayoutItem } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { Plus, X, Pencil, Check, Copy, LineChart, LayoutGrid } from 'lucide-react'

import { PageHeader } from '@/components/ui/PageHeader'
import WidgetCatalog, { WIDGET_DEFINITIONS, type WidgetDef } from '@/components/market-widgets/WidgetCatalog'
import WidgetWrapper from '@/components/market-widgets/WidgetWrapper'
import WidgetSettingsDialog from '@/components/market-widgets/WidgetSettingsDialog'
import { useSymbolLink, type LinkGroup, LINK_GROUP_COLORS } from '@/context/SymbolLinkContext'

/* -------------------------------------------------------------------------- */
/*  MCP-9: Lazy-loaded widget imports with React.lazy()                       */
/* -------------------------------------------------------------------------- */

const FearGreedWidget = React.lazy(() => import('@/components/market-widgets/FearGreedWidget'))
const VixWidget = React.lazy(() => import('@/components/market-widgets/VixWidget'))
const Mag7Widget = React.lazy(() => import('@/components/market-widgets/Mag7Widget'))
const MarketHeatmapWidget = React.lazy(() => import('@/components/market-widgets/MarketHeatmapWidget'))
const TrendingVideosWidget = React.lazy(() => import('@/components/market-widgets/TrendingVideosWidget'))
const BreakingNewsWidget = React.lazy(() => import('@/components/market-widgets/BreakingNewsWidget'))
const SocialFeedWidget = React.lazy(() => import('@/components/market-widgets/SocialFeedWidget'))
const GlobalIndicesWidget = React.lazy(() => import('@/components/market-widgets/GlobalIndicesWidget'))
const CryptoWidget = React.lazy(() => import('@/components/market-widgets/CryptoWidget'))
const SectorPerformanceWidget = React.lazy(() => import('@/components/market-widgets/SectorPerformanceWidget'))
const EconomicCalendarWidget = React.lazy(() => import('@/components/market-widgets/EconomicCalendarWidget'))
const EarningsCalendarWidget = React.lazy(() => import('@/components/market-widgets/EarningsCalendarWidget'))
const MarketBreadthWidget = React.lazy(() => import('@/components/market-widgets/MarketBreadthWidget'))
const FuturesWidget = React.lazy(() => import('@/components/market-widgets/FuturesWidget'))
const CommoditiesWidget = React.lazy(() => import('@/components/market-widgets/CommoditiesWidget'))
const ForexWidget = React.lazy(() => import('@/components/market-widgets/ForexWidget'))
const BondYieldsWidget = React.lazy(() => import('@/components/market-widgets/BondYieldsWidget'))
const TopMoversWidget = React.lazy(() => import('@/components/market-widgets/TopMoversWidget'))
const PlatformSentimentWidget = React.lazy(() => import('@/components/market-widgets/PlatformSentimentWidget'))
const TradingViewChartWidget = React.lazy(() => import('@/components/market-widgets/TradingViewChartWidget'))
const RSSFeedWidget = React.lazy(() => import('@/components/market-widgets/RSSFeedWidget'))
const MarketClockWidget = React.lazy(() => import('@/components/market-widgets/MarketClockWidget'))
const StockScreenerWidget = React.lazy(() => import('@/components/market-widgets/StockScreenerWidget'))
const ForexCrossRatesWidget = React.lazy(() => import('@/components/market-widgets/ForexCrossRatesWidget'))
const CryptoScreenerWidget = React.lazy(() => import('@/components/market-widgets/CryptoScreenerWidget'))
const TechnicalAnalysisWidget = React.lazy(() => import('@/components/market-widgets/TechnicalAnalysisWidget'))
const SymbolInfoWidget = React.lazy(() => import('@/components/market-widgets/SymbolInfoWidget'))
const MiniChartWidget = React.lazy(() => import('@/components/market-widgets/MiniChartWidget'))
const HotlistsWidget = React.lazy(() => import('@/components/market-widgets/HotlistsWidget'))
const PutCallRatioWidget = React.lazy(() => import('@/components/market-widgets/PutCallRatioWidget'))
const IPOCalendarWidget = React.lazy(() => import('@/components/market-widgets/IPOCalendarWidget'))
const RelativeVolumeWidget = React.lazy(() => import('@/components/market-widgets/RelativeVolumeWidget'))
const FiftyTwoWeekWidget = React.lazy(() => import('@/components/market-widgets/FiftyTwoWeekWidget'))
const SectorRotationWidget = React.lazy(() => import('@/components/market-widgets/SectorRotationWidget'))
const OptionsExpiryWidget = React.lazy(() => import('@/components/market-widgets/OptionsExpiryWidget'))
const TradingChecklistWidget = React.lazy(() => import('@/components/market-widgets/TradingChecklistWidget'))
const QuickNotesWidget = React.lazy(() => import('@/components/market-widgets/QuickNotesWidget'))
const TickerTapeWidget = React.lazy(() => import('@/components/market-widgets/TickerTapeWidget'))
const TopStoriesWidget = React.lazy(() => import('@/components/market-widgets/TopStoriesWidget'))
const FundamentalDataWidget = React.lazy(() => import('@/components/market-widgets/FundamentalDataWidget'))
const CompanyProfileWidget = React.lazy(() => import('@/components/market-widgets/CompanyProfileWidget'))
const CryptoHeatmapWidget = React.lazy(() => import('@/components/market-widgets/CryptoHeatmapWidget'))
const ETFHeatmapWidget = React.lazy(() => import('@/components/market-widgets/ETFHeatmapWidget'))
const GammaExposureWidget = React.lazy(() => import('@/components/market-widgets/GammaExposureWidget'))
const MarketInternalsWidget = React.lazy(() => import('@/components/market-widgets/MarketInternalsWidget'))
const VixTermStructureWidget = React.lazy(() => import('@/components/market-widgets/VixTermStructureWidget'))
const PremarketGapWidget = React.lazy(() => import('@/components/market-widgets/PremarketGapWidget'))
const SpxKeyLevelsWidget = React.lazy(() => import('@/components/market-widgets/SpxKeyLevelsWidget'))
const OptionsFlowWidget = React.lazy(() => import('@/components/market-widgets/OptionsFlowWidget'))
const CorrelationMatrixWidget = React.lazy(() => import('@/components/market-widgets/CorrelationMatrixWidget'))
const VolatilityDashboardWidget = React.lazy(() => import('@/components/market-widgets/VolatilityDashboardWidget'))
const PremarketMoversWidget = React.lazy(() => import('@/components/market-widgets/PremarketMoversWidget'))
const DayTradePnlWidget = React.lazy(() => import('@/components/market-widgets/DayTradePnlWidget'))
const PositionSizeCalcWidget = React.lazy(() => import('@/components/market-widgets/PositionSizeCalcWidget'))
const RiskRewardWidget = React.lazy(() => import('@/components/market-widgets/RiskRewardWidget'))
const TradingSessionWidget = React.lazy(() => import('@/components/market-widgets/TradingSessionWidget'))
const KeyboardShortcutsWidget = React.lazy(() => import('@/components/market-widgets/KeyboardShortcutsWidget'))
const WatchlistWidget = React.lazy(() => import('@/components/market-widgets/WatchlistWidget'))

/* -------------------------------------------------------------------------- */
/*  Widget skeleton fallback                                                  */
/* -------------------------------------------------------------------------- */

function WidgetSkeleton() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="animate-pulse space-y-2 w-3/4">
        <div className="h-3 bg-muted rounded" />
        <div className="h-3 bg-muted rounded w-2/3" />
        <div className="h-8 bg-muted rounded mt-3" />
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/*  Widget maps                                                               */
/* -------------------------------------------------------------------------- */

/* eslint-disable @typescript-eslint/no-explicit-any */
const STATIC_WIDGETS: Record<string, React.LazyExoticComponent<React.ComponentType<any>>> = {
  'fear-greed': FearGreedWidget,
  'mag7': Mag7Widget,
  'trending-videos': TrendingVideosWidget,
  'breaking-news': BreakingNewsWidget,
  'social-feed': SocialFeedWidget,
  'global-indices': GlobalIndicesWidget,
  'crypto': CryptoWidget,
  'sector-perf': SectorPerformanceWidget,
  'econ-cal': EconomicCalendarWidget,
  'earnings-cal': EarningsCalendarWidget,
  'market-breadth': MarketBreadthWidget,
  'futures': FuturesWidget,
  'commodities': CommoditiesWidget,
  'forex': ForexWidget,
  'bond-yields': BondYieldsWidget,
  'top-movers': TopMoversWidget,
  'platform-sentiment': PlatformSentimentWidget,
  'rss-feed': RSSFeedWidget,
  'market-clock': MarketClockWidget,
  'stock-screener': StockScreenerWidget,
  'forex-cross-rates': ForexCrossRatesWidget,
  'crypto-screener': CryptoScreenerWidget,
  'hotlists': HotlistsWidget,
  'ipo-calendar': IPOCalendarWidget,
  'rvol': RelativeVolumeWidget,
  '52week': FiftyTwoWeekWidget,
  'sector-rotation': SectorRotationWidget,
  'options-expiry': OptionsExpiryWidget,
  'trading-checklist': TradingChecklistWidget,
  'quick-notes': QuickNotesWidget,
  'ticker-tape': TickerTapeWidget,
  'top-stories': TopStoriesWidget,
  'crypto-heatmap': CryptoHeatmapWidget,
  'etf-heatmap': ETFHeatmapWidget,
  'market-internals': MarketInternalsWidget,
  'vix-term': VixTermStructureWidget,
  'premarket-gaps': PremarketGapWidget,
  'premarket-movers': PremarketMoversWidget,
  'day-pnl': DayTradePnlWidget,
  'position-calc': PositionSizeCalcWidget,
  'risk-reward': RiskRewardWidget,
  'session-timer': TradingSessionWidget,
  'keyboard-shortcuts': KeyboardShortcutsWidget,
  'correlations': CorrelationMatrixWidget,
  'heatmap': MarketHeatmapWidget,
  'watchlist': WatchlistWidget,
}

const CONFIGURABLE_WIDGETS: Record<string, React.LazyExoticComponent<React.ComponentType<any>>> = {
  'tv-chart': TradingViewChartWidget,
  'vix': VixWidget,
  'technical-analysis': TechnicalAnalysisWidget,
  'symbol-info': SymbolInfoWidget,
  'mini-chart': MiniChartWidget,
  'fundamental-data': FundamentalDataWidget,
  'company-profile': CompanyProfileWidget,
  'gex': GammaExposureWidget,
  'spx-levels': SpxKeyLevelsWidget,
  'options-flow': OptionsFlowWidget,
  'put-call-ratio': PutCallRatioWidget,
  'volatility': VolatilityDashboardWidget,
}

const CONFIGURABLE_DEFAULTS: Record<string, string> = {
  'tv-chart': 'AAPL',
  'vix': 'SPY',
  'technical-analysis': 'AAPL',
  'symbol-info': 'AAPL',
  'mini-chart': 'SPY',
  'fundamental-data': 'AAPL',
  'company-profile': 'AAPL',
  'gex': 'SPY',
  'spx-levels': 'SPY',
  'options-flow': 'SPY',
  'put-call-ratio': 'SPY',
  'volatility': 'SPY',
}

function isConfigurable(widgetId: string): boolean {
  return widgetId in CONFIGURABLE_WIDGETS
}

/* -------------------------------------------------------------------------- */
/*  MCP-5: Layout Presets                                                     */
/* -------------------------------------------------------------------------- */

interface PresetDef {
  name: string
  widgets: string[]
  layouts: LayoutItem[]
}

const LAYOUT_PRESETS: PresetDef[] = [
  {
    name: 'Day Trading',
    widgets: ['tv-chart', 'top-movers', 'rvol', 'options-flow', 'fear-greed'],
    layouts: [
      { i: 'tv-chart', x: 0, y: 0, w: 8, h: 8, minW: 4, minH: 4 },
      { i: 'top-movers', x: 8, y: 0, w: 4, h: 4, minW: 3, minH: 3 },
      { i: 'rvol', x: 8, y: 4, w: 4, h: 4, minW: 3, minH: 4 },
      { i: 'options-flow', x: 0, y: 8, w: 6, h: 6, minW: 3, minH: 5 },
      { i: 'fear-greed', x: 6, y: 8, w: 3, h: 4, minW: 2, minH: 3 },
    ],
  },
  {
    name: 'Macro',
    widgets: ['global-indices', 'bond-yields', 'commodities', 'forex', 'econ-cal'],
    layouts: [
      { i: 'global-indices', x: 0, y: 0, w: 5, h: 4, minW: 4, minH: 3 },
      { i: 'bond-yields', x: 5, y: 0, w: 4, h: 4, minW: 3, minH: 3 },
      { i: 'commodities', x: 9, y: 0, w: 3, h: 4, minW: 3, minH: 3 },
      { i: 'forex', x: 0, y: 4, w: 4, h: 4, minW: 3, minH: 3 },
      { i: 'econ-cal', x: 4, y: 4, w: 5, h: 5, minW: 4, minH: 4 },
    ],
  },
  {
    name: 'Swing Trading',
    widgets: ['tv-chart', 'sector-perf', '52week', 'rvol', 'market-breadth'],
    layouts: [
      { i: 'tv-chart', x: 0, y: 0, w: 6, h: 6, minW: 4, minH: 4 },
      { i: 'sector-perf', x: 6, y: 0, w: 4, h: 5, minW: 3, minH: 4 },
      { i: '52week', x: 10, y: 0, w: 2, h: 5, minW: 2, minH: 4 },
      { i: 'rvol', x: 0, y: 6, w: 4, h: 5, minW: 3, minH: 4 },
      { i: 'market-breadth', x: 4, y: 6, w: 4, h: 4, minW: 3, minH: 3 },
    ],
  },
]

/* -------------------------------------------------------------------------- */
/*  Tab types + persistence                                                   */
/* -------------------------------------------------------------------------- */

interface TabData {
  id: string
  name: string
  widgets: string[]
  layouts: LayoutItem[]
  widgetConfigs: Record<string, Record<string, string>>
}

const STORAGE_KEY = 'mcc-tabs-v2'

const DEFAULT_TAB: TabData = {
  id: 'default',
  name: 'Overview',
  widgets: ['fear-greed', 'global-indices', 'top-movers', 'breaking-news', 'mag7', 'sector-perf'],
  layouts: [
    { i: 'fear-greed', x: 0, y: 0, w: 3, h: 4, minW: 2, minH: 3 },
    { i: 'global-indices', x: 3, y: 0, w: 5, h: 4, minW: 4, minH: 3 },
    { i: 'top-movers', x: 8, y: 0, w: 4, h: 4, minW: 3, minH: 3 },
    { i: 'breaking-news', x: 0, y: 4, w: 4, h: 5, minW: 3, minH: 4 },
    { i: 'mag7', x: 4, y: 4, w: 4, h: 5, minW: 3, minH: 4 },
    { i: 'sector-perf', x: 8, y: 4, w: 4, h: 5, minW: 3, minH: 4 },
  ],
  widgetConfigs: {},
}

function loadTabs(): TabData[] {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const tabs = JSON.parse(saved) as TabData[]
      if (Array.isArray(tabs) && tabs.length > 0) return tabs
    }
  } catch { /* ignore */ }
  return [DEFAULT_TAB]
}

function saveTabs(tabs: TabData[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tabs))
}

function getWidgetDef(id: string): WidgetDef | undefined {
  return WIDGET_DEFINITIONS.find((w) => w.id === id)
}

function generateId(): string {
  return Math.random().toString(36).substring(2, 9)
}

/* -------------------------------------------------------------------------- */
/*  Tab Bar                                                                   */
/* -------------------------------------------------------------------------- */

function TabBar({
  tabs,
  activeTabId,
  onSelectTab,
  onAddTab,
  onRenameTab,
  onDeleteTab,
  onDuplicateTab,
}: {
  tabs: TabData[]
  activeTabId: string
  onSelectTab: (id: string) => void
  onAddTab: () => void
  onRenameTab: (id: string, name: string) => void
  onDeleteTab: (id: string) => void
  onDuplicateTab: (id: string) => void
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingId && inputRef.current) inputRef.current.focus()
  }, [editingId])

  const commitRename = () => {
    if (editingId && editName.trim()) {
      onRenameTab(editingId, editName.trim())
    }
    setEditingId(null)
  }

  return (
    <div className="flex items-center gap-0.5 overflow-x-auto scrollbar-thin px-1 sm:px-2">
      {tabs.map((tab) => (
        <div
          key={tab.id}
          className={`group flex items-center gap-1 px-3 py-1.5 rounded-t-lg border-b-2 cursor-pointer transition-colors shrink-0 ${
            tab.id === activeTabId
              ? 'bg-card border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/30'
          }`}
          onClick={() => tab.id !== activeTabId && onSelectTab(tab.id)}
        >
          {editingId === tab.id ? (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <input
                ref={inputRef}
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename()
                  if (e.key === 'Escape') setEditingId(null)
                }}
                onBlur={commitRename}
                className="text-xs bg-transparent border-b border-primary outline-none w-24 py-0"
              />
              <button type="button" onClick={commitRename} className="text-primary hover:opacity-80">
                <Check className="h-3 w-3" />
              </button>
            </div>
          ) : (
            <>
              <span className="text-xs font-medium max-w-[120px] truncate">{tab.name}</span>
              <span className="text-[9px] text-muted-foreground">({tab.widgets.length})</span>
              <div className="hidden group-hover:flex items-center gap-0.5 ml-1">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    setEditingId(tab.id)
                    setEditName(tab.name)
                  }}
                  className="text-muted-foreground hover:text-primary"
                >
                  <Pencil className="h-2.5 w-2.5" />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDuplicateTab(tab.id)
                  }}
                  className="text-muted-foreground hover:text-primary"
                  title="Duplicate tab"
                >
                  <Copy className="h-2.5 w-2.5" />
                </button>
                {tabs.length > 1 && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteTab(tab.id)
                    }}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      ))}
      <button
        type="button"
        onClick={onAddTab}
        className="flex items-center gap-1 px-2 py-1.5 text-muted-foreground hover:text-primary transition-colors shrink-0"
        title="Add new tab"
      >
        <Plus className="h-3.5 w-3.5" />
        <span className="text-[10px]">New Tab</span>
      </button>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/*  Presets Dropdown                                                          */
/* -------------------------------------------------------------------------- */

function PresetsDropdown({ onSelect }: { onSelect: (preset: PresetDef) => void }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted/50 transition-colors"
      >
        <LayoutGrid className="h-4 w-4" />
        Presets
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 w-56 rounded-md border bg-popover p-1 shadow-md">
            {LAYOUT_PRESETS.map((preset) => (
              <button
                key={preset.name}
                type="button"
                onClick={() => {
                  onSelect(preset)
                  setOpen(false)
                }}
                className="w-full text-left px-3 py-2 text-sm rounded hover:bg-accent transition-colors"
              >
                <div className="font-medium">{preset.name}</div>
                <div className="text-xs text-muted-foreground">{preset.widgets.length} widgets</div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/*  Main Component                                                            */
/* -------------------------------------------------------------------------- */

export default function MarketPage() {
  const [tabs, setTabs] = useState<TabData[]>(loadTabs)
  const [activeTabId, setActiveTabId] = useState(() => tabs[0]?.id ?? 'default')
  const [settingsWidgetId, setSettingsWidgetId] = useState<string | null>(null)
  const { width, containerRef, mounted } = useContainerWidth()
  const { setGroupSymbol } = useSymbolLink()

  const activeTab = useMemo(() => tabs.find((t) => t.id === activeTabId) ?? tabs[0], [tabs, activeTabId])

  const updateTab = useCallback((tabId: string, updater: (tab: TabData) => TabData) => {
    setTabs((prev) => {
      const next = prev.map((t) => (t.id === tabId ? updater(t) : t))
      saveTabs(next)
      return next
    })
  }, [])

  const handleLayoutChange = useCallback(
    (newLayout: readonly LayoutItem[]) => {
      updateTab(activeTabId, (tab) => ({ ...tab, layouts: [...newLayout] }))
    },
    [activeTabId, updateTab],
  )

  const handleAddWidget = useCallback(
    (widgetId: string) => {
      updateTab(activeTabId, (tab) => {
        if (tab.widgets.includes(widgetId)) return tab
        const def = getWidgetDef(widgetId)
        if (!def) return tab
        const maxY = tab.layouts.reduce((max, l) => Math.max(max, l.y + l.h), 0)
        const newLayout: LayoutItem = {
          i: widgetId,
          x: 0,
          y: maxY,
          w: def.defaultW,
          h: def.defaultH,
          minW: def.minW,
          minH: def.minH,
        }
        const newConfigs = { ...tab.widgetConfigs }
        if (isConfigurable(widgetId) && !newConfigs[widgetId]) {
          newConfigs[widgetId] = { symbol: CONFIGURABLE_DEFAULTS[widgetId] ?? 'SPY' }
        }
        return {
          ...tab,
          widgets: [...tab.widgets, widgetId],
          layouts: [...tab.layouts, newLayout],
          widgetConfigs: newConfigs,
        }
      })
    },
    [activeTabId, updateTab],
  )

  const handleRemoveWidget = useCallback(
    (widgetId: string) => {
      updateTab(activeTabId, (tab) => ({
        ...tab,
        widgets: tab.widgets.filter((w) => w !== widgetId),
        layouts: tab.layouts.filter((l) => l.i !== widgetId),
      }))
    },
    [activeTabId, updateTab],
  )

  const handleWidgetConfigChange = useCallback(
    (widgetId: string, key: string, value: string) => {
      updateTab(activeTabId, (tab) => {
        const newConfigs = {
          ...tab.widgetConfigs,
          [widgetId]: { ...(tab.widgetConfigs[widgetId] ?? {}), [key]: value },
        }

        // MCP-3: If widget has a linkGroup, broadcast the symbol to the group
        const linkGroup = newConfigs[widgetId]?.linkGroup as LinkGroup | undefined
        if (key === 'symbol' && linkGroup) {
          setGroupSymbol(linkGroup, value)
        }

        return { ...tab, widgetConfigs: newConfigs }
      })
      setSettingsWidgetId(null)
    },
    [activeTabId, updateTab, setGroupSymbol],
  )

  // MCP-3: Handle link group assignment from settings dialog
  const handleLinkGroupChange = useCallback(
    (widgetId: string, group: LinkGroup | null) => {
      updateTab(activeTabId, (tab) => {
        const existing = tab.widgetConfigs[widgetId] ?? {}
        const updated = { ...existing }
        if (group) {
          updated.linkGroup = group
        } else {
          delete updated.linkGroup
        }
        return {
          ...tab,
          widgetConfigs: { ...tab.widgetConfigs, [widgetId]: updated },
        }
      })
    },
    [activeTabId, updateTab],
  )

  // MCP-5: Apply a preset to the current tab
  const handleApplyPreset = useCallback(
    (preset: PresetDef) => {
      updateTab(activeTabId, (tab) => {
        const newConfigs: Record<string, Record<string, string>> = {}
        for (const wid of preset.widgets) {
          if (isConfigurable(wid)) {
            newConfigs[wid] = { symbol: CONFIGURABLE_DEFAULTS[wid] ?? 'SPY' }
          }
        }
        return {
          ...tab,
          widgets: [...preset.widgets],
          layouts: [...preset.layouts],
          widgetConfigs: newConfigs,
        }
      })
    },
    [activeTabId, updateTab],
  )

  // MCP-4: Handle watchlist ticker click to update linked widgets
  const handleWatchlistTickerClick = useCallback(
    (ticker: string) => {
      // Update all link groups to the new ticker
      (['A', 'B', 'C'] as LinkGroup[]).forEach((g) => setGroupSymbol(g, ticker))
    },
    [setGroupSymbol],
  )

  const handleAddTab = useCallback(() => {
    const id = generateId()
    const newTab: TabData = {
      id,
      name: `Tab ${tabs.length + 1}`,
      widgets: [],
      layouts: [],
      widgetConfigs: {},
    }
    const next = [...tabs, newTab]
    setTabs(next)
    saveTabs(next)
    setActiveTabId(id)
  }, [tabs])

  const handleRenameTab = useCallback(
    (id: string, name: string) => {
      updateTab(id, (tab) => ({ ...tab, name }))
    },
    [updateTab],
  )

  const handleDeleteTab = useCallback(
    (id: string) => {
      setTabs((prev) => {
        const next = prev.filter((t) => t.id !== id)
        if (next.length === 0) next.push(DEFAULT_TAB)
        saveTabs(next)
        if (activeTabId === id) setActiveTabId(next[0].id)
        return next
      })
    },
    [activeTabId],
  )

  const handleDuplicateTab = useCallback((id: string) => {
    const source = tabs.find((t) => t.id === id)
    if (!source) return
    const newId = generateId()
    const duplicate: TabData = { ...source, id: newId, name: `${source.name} (copy)` }
    const next = [...tabs, duplicate]
    setTabs(next)
    saveTabs(next)
    setActiveTabId(newId)
  }, [tabs])

  const filteredLayouts = useMemo(
    () => activeTab.layouts.filter((l) => activeTab.widgets.includes(l.i)),
    [activeTab],
  )

  const getWidgetConfig = useCallback(
    (widgetId: string): Record<string, string> => activeTab.widgetConfigs[widgetId] ?? {},
    [activeTab],
  )

  const renderWidget = useCallback(
    (widgetId: string) => {
      const config = getWidgetConfig(widgetId)
      const symbol = config.symbol ?? CONFIGURABLE_DEFAULTS[widgetId] ?? 'SPY'

      // MCP-4: Special handling for watchlist widget
      if (widgetId === 'watchlist') {
        const WLComp = STATIC_WIDGETS['watchlist']
        return (
          <Suspense fallback={<WidgetSkeleton />}>
            <WLComp onTickerClick={handleWatchlistTickerClick} />
          </Suspense>
        )
      }

      const ConfigurableComponent = CONFIGURABLE_WIDGETS[widgetId]
      if (ConfigurableComponent) {
        return (
          <Suspense fallback={<WidgetSkeleton />}>
            <ConfigurableComponent symbol={symbol} />
          </Suspense>
        )
      }

      const StaticComponent = STATIC_WIDGETS[widgetId]
      if (StaticComponent) {
        return (
          <Suspense fallback={<WidgetSkeleton />}>
            <StaticComponent />
          </Suspense>
        )
      }

      return (
        <div className="flex items-center justify-center h-full text-[10px] text-muted-foreground">
          Widget not found
        </div>
      )
    },
    [getWidgetConfig, handleWatchlistTickerClick],
  )

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader
        icon={LineChart}
        title="Market Command Center"
        description={`${activeTab.widgets.length} widgets on "${activeTab.name}" — drag to rearrange, add or remove widgets`}
      >
        <div className="flex items-center gap-2">
          <PresetsDropdown onSelect={handleApplyPreset} />
          <WidgetCatalog activeWidgetIds={activeTab.widgets} onAddWidget={handleAddWidget} />
        </div>
      </PageHeader>

      <div className="border-b bg-card/50 rounded-t-lg sticky top-0 z-10">
        <TabBar
          tabs={tabs}
          activeTabId={activeTabId}
          onSelectTab={setActiveTabId}
          onAddTab={handleAddTab}
          onRenameTab={handleRenameTab}
          onDeleteTab={handleDeleteTab}
          onDuplicateTab={handleDuplicateTab}
        />
      </div>

      <div
        className="flex-1 min-h-[480px] overflow-auto p-1 sm:p-2 rounded-b-lg border border-t-0 border-border bg-background"
        ref={containerRef as React.RefObject<HTMLDivElement>}
      >
        {activeTab.widgets.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <p className="text-sm mb-2">No widgets on this tab yet</p>
            <p className="text-xs mb-4">Click &quot;Add Widget&quot; or choose a Preset to build your &quot;{activeTab.name}&quot; dashboard</p>
          </div>
        ) : mounted ? (
          (() => {
            const Grid = ResponsiveGridLayout as React.ComponentType<any>
            return (
              <Grid
                className="layout"
                width={width}
                layouts={{ lg: filteredLayouts }}
                breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
                cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
                rowHeight={40}
                dragConfig={{ enabled: true, handle: '.drag-handle' }}
                resizeConfig={{ enabled: true }}
                onLayoutChange={handleLayoutChange}
                margin={[8, 8]}
              >
            {activeTab.widgets.map((widgetId) => {
              const def = getWidgetDef(widgetId)
              if (!def) return null
              const configurable = isConfigurable(widgetId)
              const config = getWidgetConfig(widgetId)
              const linkGroup = config.linkGroup as LinkGroup | undefined

              return (
                <div key={widgetId}>
                  <WidgetWrapper
                    title={
                      configurable && config.symbol ? `${def.label} (${config.symbol})` : def.label
                    }
                    icon={def.icon}
                    onRemove={() => handleRemoveWidget(widgetId)}
                    hasSettings={configurable}
                    onSettings={() => setSettingsWidgetId(widgetId)}
                    linkGroupColor={linkGroup ? LINK_GROUP_COLORS[linkGroup] : undefined}
                  >
                    {renderWidget(widgetId)}
                  </WidgetWrapper>
                </div>
              )
            })}
              </Grid>
            )
          })()
        ) : null}
      </div>

      {settingsWidgetId && (
        <WidgetSettingsDialog
          widgetId={settingsWidgetId}
          widgetLabel={getWidgetDef(settingsWidgetId)?.label ?? ''}
          currentSymbol={
            getWidgetConfig(settingsWidgetId).symbol ??
            CONFIGURABLE_DEFAULTS[settingsWidgetId] ??
            'SPY'
          }
          currentLinkGroup={(getWidgetConfig(settingsWidgetId).linkGroup as LinkGroup) ?? null}
          onSave={(symbol) => handleWidgetConfigChange(settingsWidgetId, 'symbol', symbol)}
          onLinkGroupChange={(group) => handleLinkGroupChange(settingsWidgetId, group)}
          onClose={() => setSettingsWidgetId(null)}
        />
      )}
    </div>
  )
}
