import TradingViewEmbed from './TradingViewEmbed'

export default function HotlistsWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-hotlists.js"
      config={{
        colorTheme: "dark",
        dateRange: "1D",
        exchange: "US",
        showChart: true,
        locale: "en",
        largeChartUrl: "",
        isTransparent: true,
        showSymbolLogo: true,
        showFloatingTooltip: false,
        width: "100%",
        height: "100%",
        plotLineColorGrowing: "rgba(41, 98, 255, 1)",
        plotLineColorFalling: "rgba(255, 77, 92, 1)",
        gridLineColor: "rgba(42, 46, 57, 0)",
        scaleFontColor: "rgba(134, 137, 147, 1)",
        belowLineFillColorGrowing: "rgba(41, 98, 255, 0.12)",
        belowLineFillColorFalling: "rgba(255, 77, 92, 0.12)",
        belowLineFillColorGrowingBottom: "rgba(41, 98, 255, 0)",
        belowLineFillColorFallingBottom: "rgba(255, 77, 92, 0)",
        symbolActiveColor: "rgba(41, 98, 255, 0.12)",
      }}
    />
  )
}
