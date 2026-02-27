import TradingViewEmbed from './TradingViewEmbed'

export default function TechnicalAnalysisWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js"
      config={{
        interval: "1D",
        width: "100%",
        height: "100%",
        isTransparent: true,
        symbol: "NASDAQ:AAPL",
        showIntervalTabs: true,
        displayMode: "single",
        colorTheme: "dark",
        locale: "en",
      }}
    />
  )
}
