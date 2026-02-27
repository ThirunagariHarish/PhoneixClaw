import TradingViewEmbed from './TradingViewEmbed'

export default function SymbolInfoWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-symbol-info.js"
      config={{
        symbol: "NASDAQ:AAPL",
        width: "100%",
        isTransparent: true,
        colorTheme: "dark",
        locale: "en",
      }}
    />
  )
}
