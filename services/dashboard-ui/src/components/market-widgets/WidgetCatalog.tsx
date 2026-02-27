import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Plus, Gauge, TrendingUp, BarChart3, Sparkles, Newspaper, Youtube,
  Twitter, Globe, Bitcoin, PieChart, Calendar, LineChart, Landmark,
  DollarSign, ArrowUpDown, HeartPulse, CandlestickChart, Rss,
  Clock, Flame, Rocket, Search, Activity, BarChart2, ArrowUpCircle,
  RefreshCw, StickyNote, CheckSquare, CalendarClock, Info, TrendingDown,
  Zap, ScrollText, BookOpen, Building2, Layers, Grid3X3, Target,
  Calculator, Scale, Timer, Keyboard, Sigma, Radar, AreaChart,
  Sunrise, MapPin, GitBranch, Thermometer, Wallet,
} from 'lucide-react'

export interface WidgetDef {
  id: string
  label: string
  description: string
  icon: React.ElementType
  category: string
  defaultW: number
  defaultH: number
  minW: number
  minH: number
}

export const WIDGET_DEFINITIONS: WidgetDef[] = [
  { id: 'fear-greed', label: 'Fear & Greed Index', description: 'CNN market sentiment gauge', icon: Gauge, category: 'Market Pulse', defaultW: 3, defaultH: 4, minW: 2, minH: 3 },
  { id: 'vix', label: 'VIX Volatility', description: 'CBOE Volatility Index chart', icon: TrendingUp, category: 'Market Pulse', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  { id: 'market-breadth', label: 'Market Breadth', description: 'Major indices performance', icon: BarChart3, category: 'Market Pulse', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  { id: 'market-clock', label: 'Market Clock', description: 'Global exchange hours', icon: Clock, category: 'Market Pulse', defaultW: 3, defaultH: 3, minW: 2, minH: 2 },
  { id: 'global-indices', label: 'Global Indices', description: 'Worldwide market overview', icon: Globe, category: 'Indices & Performance', defaultW: 5, defaultH: 4, minW: 4, minH: 3 },
  { id: 'mag7', label: 'Mag 7 Tracker', description: 'Magnificent Seven stocks', icon: Sparkles, category: 'Indices & Performance', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'sector-perf', label: 'Sector Performance', description: 'S&P 500 sector ETFs', icon: PieChart, category: 'Indices & Performance', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'futures', label: 'Futures Market', description: 'ES, NQ, YM, RTY futures', icon: CandlestickChart, category: 'Indices & Performance', defaultW: 6, defaultH: 2, minW: 4, minH: 2 },
  { id: 'breaking-news', label: 'Breaking News', description: 'Real-time market news feed', icon: Newspaper, category: 'News & Social', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'trending-videos', label: 'Trending Trading Videos', description: 'Popular trading YouTube channels', icon: Youtube, category: 'News & Social', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'social-feed', label: 'Political Social Feed', description: 'Market-moving social posts', icon: Twitter, category: 'News & Social', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'rss-feed', label: 'RSS News Feed', description: 'Custom financial RSS feeds', icon: Rss, category: 'News & Social', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'crypto', label: 'Crypto Overview', description: 'BTC, ETH, SOL and more', icon: Bitcoin, category: 'Assets', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  { id: 'commodities', label: 'Commodities', description: 'Gold, Oil, Silver, Nat Gas', icon: Flame, category: 'Assets', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  { id: 'forex', label: 'Currency Pairs', description: 'Major FX pairs', icon: DollarSign, category: 'Assets', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  { id: 'bond-yields', label: 'Bond Yields', description: 'US Treasury yield curve', icon: Landmark, category: 'Assets', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  { id: 'top-movers', label: 'Top Movers', description: 'Biggest gainers and losers', icon: ArrowUpDown, category: 'Trading Intel', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'earnings-cal', label: 'Earnings Calendar', description: 'Upcoming earnings reports', icon: Calendar, category: 'Trading Intel', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  { id: 'econ-cal', label: 'Economic Calendar', description: 'Economic events & releases', icon: Calendar, category: 'Trading Intel', defaultW: 5, defaultH: 5, minW: 4, minH: 4 },
  { id: 'heatmap', label: 'Market Heatmap', description: 'S&P 500 stock heatmap', icon: BarChart3, category: 'Charts', defaultW: 6, defaultH: 6, minW: 4, minH: 4 },
  { id: 'tv-chart', label: 'TradingView Chart', description: 'Advanced interactive chart', icon: LineChart, category: 'Charts', defaultW: 6, defaultH: 6, minW: 4, minH: 4 },
  { id: 'platform-sentiment', label: 'Platform Sentiment', description: 'Your Discord sentiment data', icon: HeartPulse, category: 'Platform', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  // TradingView embed widgets
  { id: 'stock-screener', label: 'Stock Screener', description: 'Filter stocks by technicals & fundamentals', icon: Search, category: 'Screeners', defaultW: 6, defaultH: 6, minW: 4, minH: 4 },
  { id: 'forex-cross-rates', label: 'Forex Cross Rates', description: 'Major currency pair rates matrix', icon: DollarSign, category: 'Screeners', defaultW: 5, defaultH: 5, minW: 4, minH: 4 },
  { id: 'crypto-screener', label: 'Crypto Screener', description: 'Screen crypto by market cap, volume, change', icon: Bitcoin, category: 'Screeners', defaultW: 6, defaultH: 6, minW: 4, minH: 4 },
  { id: 'technical-analysis', label: 'Technical Analysis', description: 'Buy/Sell/Neutral gauge for any symbol', icon: Activity, category: 'Charts', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'symbol-info', label: 'Symbol Info', description: 'Compact ticker card with price & volume', icon: Info, category: 'Market Pulse', defaultW: 3, defaultH: 2, minW: 2, minH: 2 },
  { id: 'mini-chart', label: 'Mini Chart', description: 'Small chart with price action', icon: LineChart, category: 'Charts', defaultW: 3, defaultH: 3, minW: 2, minH: 2 },
  { id: 'hotlists', label: 'Hotlists', description: 'Most active, top gainers/losers, volume leaders', icon: Zap, category: 'Trading Intel', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  // API-backed widgets
  { id: 'put-call-ratio', label: 'Put/Call Ratio', description: 'Options P/C ratio for SPY & QQQ', icon: BarChart2, category: 'Trading Intel', defaultW: 3, defaultH: 5, minW: 2, minH: 4 },
  { id: 'ipo-calendar', label: 'IPO Calendar', description: 'Recent and notable IPO listings', icon: Rocket, category: 'Trading Intel', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'rvol', label: 'Relative Volume', description: 'Stocks with volume spikes vs 20-day avg', icon: BarChart3, category: 'Trading Intel', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: '52week', label: '52-Week Highs/Lows', description: 'Stocks near 52-week extremes', icon: ArrowUpCircle, category: 'Trading Intel', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'sector-rotation', label: 'Sector Rotation', description: 'Multi-timeframe sector performance', icon: RefreshCw, category: 'Indices & Performance', defaultW: 5, defaultH: 5, minW: 4, minH: 4 },
  // Local/static widgets
  { id: 'options-expiry', label: 'Options Expiry', description: 'Upcoming options expiration dates', icon: CalendarClock, category: 'Trading Intel', defaultW: 3, defaultH: 4, minW: 2, minH: 3 },
  { id: 'trading-checklist', label: 'Trading Checklist', description: 'Personal pre-trade checklist', icon: CheckSquare, category: 'Platform', defaultW: 3, defaultH: 5, minW: 2, minH: 4 },
  { id: 'quick-notes', label: 'Quick Notes', description: 'Sticky notes for trade ideas & reminders', icon: StickyNote, category: 'Platform', defaultW: 3, defaultH: 5, minW: 2, minH: 4 },
  // v2 - TradingView embeds
  { id: 'ticker-tape', label: 'Ticker Tape', description: 'Scrolling real-time price ticker bar', icon: ScrollText, category: 'Market Pulse', defaultW: 12, defaultH: 2, minW: 6, minH: 1 },
  { id: 'top-stories', label: 'Top Stories', description: 'TradingView curated market news briefs', icon: BookOpen, category: 'News & Social', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'fundamental-data', label: 'Fundamental Data', description: 'Company financials: P/E, EPS, revenue', icon: Building2, category: 'Screeners', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'company-profile', label: 'Company Profile', description: 'Company description, sector, industry', icon: Building2, category: 'Screeners', defaultW: 4, defaultH: 4, minW: 3, minH: 3 },
  { id: 'crypto-heatmap', label: 'Crypto Heatmap', description: 'Visual crypto market by cap & performance', icon: Grid3X3, category: 'Charts', defaultW: 6, defaultH: 6, minW: 4, minH: 4 },
  { id: 'etf-heatmap', label: 'ETF Heatmap', description: 'ETF performance & dividend heatmap', icon: Layers, category: 'Charts', defaultW: 6, defaultH: 6, minW: 4, minH: 4 },
  // v2 - API-backed widgets
  { id: 'gex', label: 'Gamma Exposure (GEX)', description: 'Dealer gamma exposure & flip point', icon: Sigma, category: 'SPX Day Trading', defaultW: 4, defaultH: 6, minW: 3, minH: 5 },
  { id: 'market-internals', label: 'Market Internals', description: 'TICK, TRIN, ADD, VIX breadth signals', icon: Radar, category: 'SPX Day Trading', defaultW: 4, defaultH: 6, minW: 3, minH: 5 },
  { id: 'vix-term', label: 'VIX Term Structure', description: 'VIX contango vs backwardation regime', icon: AreaChart, category: 'SPX Day Trading', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'premarket-gaps', label: 'Premarket Gap Scanner', description: 'Stocks gapping up/down pre-market', icon: Sunrise, category: 'SPX Day Trading', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'spx-levels', label: 'SPX Key Levels', description: 'Pivots, S/R, VWAP for SPY', icon: MapPin, category: 'SPX Day Trading', defaultW: 3, defaultH: 6, minW: 2, minH: 5 },
  { id: 'options-flow', label: 'Options Flow', description: 'Call/put volume, OI, unusual activity', icon: GitBranch, category: 'SPX Day Trading', defaultW: 4, defaultH: 6, minW: 3, minH: 5 },
  { id: 'correlations', label: 'Correlation Matrix', description: '30-day cross-asset correlations', icon: Grid3X3, category: 'SPX Day Trading', defaultW: 5, defaultH: 5, minW: 4, minH: 4 },
  { id: 'volatility', label: 'Volatility Dashboard', description: 'IV rank, HV, IV-HV spread', icon: Thermometer, category: 'SPX Day Trading', defaultW: 4, defaultH: 6, minW: 3, minH: 5 },
  { id: 'premarket-movers', label: 'Premarket Movers', description: 'Top extended-hours gainers & losers', icon: Sunrise, category: 'SPX Day Trading', defaultW: 4, defaultH: 5, minW: 3, minH: 4 },
  { id: 'day-pnl', label: 'Day Trade P&L', description: "Today's trades, P&L, and win rate", icon: Wallet, category: 'Platform', defaultW: 4, defaultH: 6, minW: 3, minH: 5 },
  // v2 - Custom frontend widgets
  { id: 'position-calc', label: 'Position Size Calculator', description: 'Calculate shares from risk & stop', icon: Calculator, category: 'Tools', defaultW: 3, defaultH: 5, minW: 2, minH: 4 },
  { id: 'risk-reward', label: 'Risk/Reward Visualizer', description: 'Entry/stop/target R:R analysis', icon: Scale, category: 'Tools', defaultW: 3, defaultH: 5, minW: 2, minH: 4 },
  { id: 'session-timer', label: 'Trading Sessions', description: 'Global session times & overlap', icon: Timer, category: 'Market Pulse', defaultW: 3, defaultH: 5, minW: 2, minH: 4 },
  { id: 'keyboard-shortcuts', label: 'Keyboard Shortcuts', description: 'Custom trading hotkey reference', icon: Keyboard, category: 'Tools', defaultW: 3, defaultH: 5, minW: 2, minH: 4 },
]

const CATEGORIES = [...new Set(WIDGET_DEFINITIONS.map(w => w.category))]

interface Props {
  activeWidgetIds: string[]
  onAddWidget: (widgetId: string) => void
}

export default function WidgetCatalog({ activeWidgetIds, onAddWidget }: Props) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="sm" className="gap-1.5">
          <Plus className="h-4 w-4" /> Add Widget
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle>Add Widget</DialogTitle>
        </DialogHeader>
        <ScrollArea className="h-[60vh] pr-4">
          <div className="space-y-6">
            {CATEGORIES.map(cat => (
              <div key={cat}>
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">{cat}</h3>
                <div className="grid grid-cols-2 gap-2">
                  {WIDGET_DEFINITIONS.filter(w => w.category === cat).map(w => {
                    const isActive = activeWidgetIds.includes(w.id)
                    const Icon = w.icon
                    return (
                      <button
                        key={w.id}
                        disabled={isActive}
                        onClick={() => onAddWidget(w.id)}
                        className={`flex items-start gap-3 p-3 rounded-lg border text-left transition-all ${
                          isActive
                            ? 'opacity-50 cursor-not-allowed bg-muted/30'
                            : 'hover:border-purple-500/40 hover:bg-purple-500/5 cursor-pointer'
                        }`}
                      >
                        <Icon className="h-5 w-5 text-purple-500 shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium truncate">{w.label}</p>
                            {isActive && <Badge variant="outline" className="text-[8px]">Active</Badge>}
                          </div>
                          <p className="text-[10px] text-muted-foreground">{w.description}</p>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
