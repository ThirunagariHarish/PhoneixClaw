import TradingViewEmbed from './TradingViewEmbed'

export default function TopStoriesWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-timeline.js"
      config={{
        feedMode: "all_symbols",
        isTransparent: true,
        displayMode: "regular",
        width: "100%",
        height: "100%",
        colorTheme: "dark",
        locale: "en",
      }}
    />
  )
}
