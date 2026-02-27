import TradingViewEmbed from './TradingViewEmbed'

export default function ForexCrossRatesWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-forex-cross-rates.js"
      config={{
        width: "100%",
        height: "100%",
        currencies: ["EUR", "USD", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD"],
        isTransparent: true,
        colorTheme: "dark",
        locale: "en",
      }}
    />
  )
}
