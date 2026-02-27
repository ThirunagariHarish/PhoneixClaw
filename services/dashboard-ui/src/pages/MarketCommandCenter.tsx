import { useState, useCallback, useMemo } from 'react'
import { ResponsiveGridLayout, useContainerWidth, type LayoutItem } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'

import WidgetCatalog, { WIDGET_DEFINITIONS, type WidgetDef } from '@/components/market-widgets/WidgetCatalog'
import WidgetWrapper from '@/components/market-widgets/WidgetWrapper'
import FearGreedWidget from '@/components/market-widgets/FearGreedWidget'
import VixWidget from '@/components/market-widgets/VixWidget'
import Mag7Widget from '@/components/market-widgets/Mag7Widget'
import MarketHeatmapWidget from '@/components/market-widgets/MarketHeatmapWidget'
import TrendingVideosWidget from '@/components/market-widgets/TrendingVideosWidget'
import BreakingNewsWidget from '@/components/market-widgets/BreakingNewsWidget'
import SocialFeedWidget from '@/components/market-widgets/SocialFeedWidget'
import GlobalIndicesWidget from '@/components/market-widgets/GlobalIndicesWidget'
import CryptoWidget from '@/components/market-widgets/CryptoWidget'
import SectorPerformanceWidget from '@/components/market-widgets/SectorPerformanceWidget'
import EconomicCalendarWidget from '@/components/market-widgets/EconomicCalendarWidget'
import EarningsCalendarWidget from '@/components/market-widgets/EarningsCalendarWidget'
import MarketBreadthWidget from '@/components/market-widgets/MarketBreadthWidget'
import FuturesWidget from '@/components/market-widgets/FuturesWidget'
import CommoditiesWidget from '@/components/market-widgets/CommoditiesWidget'
import ForexWidget from '@/components/market-widgets/ForexWidget'
import BondYieldsWidget from '@/components/market-widgets/BondYieldsWidget'
import TopMoversWidget from '@/components/market-widgets/TopMoversWidget'
import PlatformSentimentWidget from '@/components/market-widgets/PlatformSentimentWidget'
import TradingViewChartWidget from '@/components/market-widgets/TradingViewChartWidget'
import RSSFeedWidget from '@/components/market-widgets/RSSFeedWidget'
import MarketClockWidget from '@/components/market-widgets/MarketClockWidget'
import StockScreenerWidget from '@/components/market-widgets/StockScreenerWidget'
import ForexCrossRatesWidget from '@/components/market-widgets/ForexCrossRatesWidget'
import CryptoScreenerWidget from '@/components/market-widgets/CryptoScreenerWidget'
import TechnicalAnalysisWidget from '@/components/market-widgets/TechnicalAnalysisWidget'
import SymbolInfoWidget from '@/components/market-widgets/SymbolInfoWidget'
import MiniChartWidget from '@/components/market-widgets/MiniChartWidget'
import HotlistsWidget from '@/components/market-widgets/HotlistsWidget'
import PutCallRatioWidget from '@/components/market-widgets/PutCallRatioWidget'
import IPOCalendarWidget from '@/components/market-widgets/IPOCalendarWidget'
import RelativeVolumeWidget from '@/components/market-widgets/RelativeVolumeWidget'
import FiftyTwoWeekWidget from '@/components/market-widgets/FiftyTwoWeekWidget'
import SectorRotationWidget from '@/components/market-widgets/SectorRotationWidget'
import OptionsExpiryWidget from '@/components/market-widgets/OptionsExpiryWidget'
import TradingChecklistWidget from '@/components/market-widgets/TradingChecklistWidget'
import QuickNotesWidget from '@/components/market-widgets/QuickNotesWidget'

const WIDGET_COMPONENTS: Record<string, React.ComponentType> = {
  'fear-greed': FearGreedWidget,
  'vix': VixWidget,
  'mag7': Mag7Widget,
  'heatmap': MarketHeatmapWidget,
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
  'tv-chart': TradingViewChartWidget,
  'rss-feed': RSSFeedWidget,
  'market-clock': MarketClockWidget,
  'stock-screener': StockScreenerWidget,
  'forex-cross-rates': ForexCrossRatesWidget,
  'crypto-screener': CryptoScreenerWidget,
  'technical-analysis': TechnicalAnalysisWidget,
  'symbol-info': SymbolInfoWidget,
  'mini-chart': MiniChartWidget,
  'hotlists': HotlistsWidget,
  'put-call-ratio': PutCallRatioWidget,
  'ipo-calendar': IPOCalendarWidget,
  'rvol': RelativeVolumeWidget,
  '52week': FiftyTwoWeekWidget,
  'sector-rotation': SectorRotationWidget,
  'options-expiry': OptionsExpiryWidget,
  'trading-checklist': TradingChecklistWidget,
  'quick-notes': QuickNotesWidget,
}

const STORAGE_KEY = 'market-dashboard-layout'
const WIDGETS_KEY = 'market-dashboard-widgets'

const DEFAULT_WIDGETS = ['fear-greed', 'global-indices', 'top-movers', 'breaking-news', 'mag7', 'sector-perf']

const DEFAULT_LAYOUT: LayoutItem[] = [
  { i: 'fear-greed', x: 0, y: 0, w: 3, h: 4, minW: 2, minH: 3 },
  { i: 'global-indices', x: 3, y: 0, w: 5, h: 4, minW: 4, minH: 3 },
  { i: 'top-movers', x: 8, y: 0, w: 4, h: 4, minW: 3, minH: 3 },
  { i: 'breaking-news', x: 0, y: 4, w: 4, h: 5, minW: 3, minH: 4 },
  { i: 'mag7', x: 4, y: 4, w: 4, h: 5, minW: 3, minH: 4 },
  { i: 'sector-perf', x: 8, y: 4, w: 4, h: 5, minW: 3, minH: 4 },
]

function loadSavedWidgets(): string[] {
  try {
    const saved = localStorage.getItem(WIDGETS_KEY)
    if (saved) return JSON.parse(saved)
  } catch {}
  return DEFAULT_WIDGETS
}

function loadSavedLayout(): LayoutItem[] {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch {}
  return DEFAULT_LAYOUT
}

function getWidgetDef(id: string): WidgetDef | undefined {
  return WIDGET_DEFINITIONS.find(w => w.id === id)
}

export default function MarketCommandCenter() {
  const [activeWidgets, setActiveWidgets] = useState<string[]>(loadSavedWidgets)
  const [layouts, setLayouts] = useState<LayoutItem[]>(loadSavedLayout)
  const { width, containerRef, mounted } = useContainerWidth()

  const handleLayoutChange = useCallback((newLayout: readonly LayoutItem[]) => {
    const mutable = [...newLayout]
    setLayouts(mutable)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(mutable))
  }, [])

  const handleAddWidget = useCallback((widgetId: string) => {
    if (activeWidgets.includes(widgetId)) return
    const def = getWidgetDef(widgetId)
    if (!def) return

    const maxY = layouts.reduce((max, l) => Math.max(max, l.y + l.h), 0)

    const newLayout: LayoutItem = {
      i: widgetId,
      x: 0,
      y: maxY,
      w: def.defaultW,
      h: def.defaultH,
      minW: def.minW,
      minH: def.minH,
    }

    const updatedWidgets = [...activeWidgets, widgetId]
    const updatedLayouts = [...layouts, newLayout]

    setActiveWidgets(updatedWidgets)
    setLayouts(updatedLayouts)
    localStorage.setItem(WIDGETS_KEY, JSON.stringify(updatedWidgets))
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updatedLayouts))
  }, [activeWidgets, layouts])

  const handleRemoveWidget = useCallback((widgetId: string) => {
    const updatedWidgets = activeWidgets.filter(w => w !== widgetId)
    const updatedLayouts = layouts.filter(l => l.i !== widgetId)

    setActiveWidgets(updatedWidgets)
    setLayouts(updatedLayouts)
    localStorage.setItem(WIDGETS_KEY, JSON.stringify(updatedWidgets))
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updatedLayouts))
  }, [activeWidgets, layouts])

  const filteredLayouts = useMemo(() => {
    return layouts.filter(l => activeWidgets.includes(l.i))
  }, [layouts, activeWidgets])

  return (
    <div className="h-[calc(100vh-3.5rem)] overflow-auto bg-background">
      <div className="flex items-center justify-between px-4 py-2 border-b sticky top-0 bg-background/95 backdrop-blur z-10">
        <div>
          <h1 className="text-sm font-semibold">Market Command Center</h1>
          <p className="text-[10px] text-muted-foreground">{activeWidgets.length} widgets active -- drag to reorder, resize from corners</p>
        </div>
        <WidgetCatalog activeWidgetIds={activeWidgets} onAddWidget={handleAddWidget} />
      </div>

      <div className="p-2" ref={containerRef as React.RefObject<HTMLDivElement>}>
        {activeWidgets.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <p className="text-sm mb-2">No widgets added yet</p>
            <p className="text-xs">Click "Add Widget" to build your market dashboard</p>
          </div>
        ) : mounted ? (
          <ResponsiveGridLayout
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
            {activeWidgets.map(widgetId => {
              const def = getWidgetDef(widgetId)
              const Component = WIDGET_COMPONENTS[widgetId]
              if (!def || !Component) return null

              return (
                <div key={widgetId}>
                  <WidgetWrapper
                    title={def.label}
                    icon={def.icon}
                    onRemove={() => handleRemoveWidget(widgetId)}
                  >
                    <Component />
                  </WidgetWrapper>
                </div>
              )
            })}
          </ResponsiveGridLayout>
        ) : null}
      </div>
    </div>
  )
}
