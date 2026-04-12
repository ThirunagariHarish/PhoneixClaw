import TradingViewEmbed from './TradingViewEmbed'

/**
 * TradingView advanced chart widget.
 * Uses the raw symbol without a hardcoded exchange prefix — TradingView
 * auto-resolves the correct exchange for most US equities. Callers can
 * still pass an explicit prefix like "NYSE:IBM" if needed.
 */
export default function TradingViewChartWidget({ symbol = 'AAPL' }: { symbol?: string }) {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
      configKey={symbol}
      config={{
        autosize: true,
        symbol,
        interval: "D",
        timezone: "Etc/UTC",
        theme: "dark",
        style: "1",
        locale: "en",
        allow_symbol_change: true,
        calendar: false,
        support_host: "https://www.tradingview.com",
      }}
    />
  )
}
