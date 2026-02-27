import TradingViewEmbed from './TradingViewEmbed'

export default function CompanyProfileWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-symbol-profile.js"
      config={{
        width: "100%",
        height: "100%",
        colorTheme: "dark",
        isTransparent: true,
        symbol: "NASDAQ:AAPL",
        locale: "en",
      }}
    />
  )
}
