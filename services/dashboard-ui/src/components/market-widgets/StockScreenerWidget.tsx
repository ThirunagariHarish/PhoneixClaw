import TradingViewEmbed from './TradingViewEmbed'

export default function StockScreenerWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-screener.js"
      config={{
        width: "100%",
        height: "100%",
        defaultColumn: "overview",
        defaultScreen: "most_capitalized",
        market: "america",
        showToolbar: true,
        colorTheme: "dark",
        locale: "en",
        isTransparent: true,
      }}
    />
  )
}
