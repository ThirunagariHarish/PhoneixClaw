import TradingViewEmbed from './TradingViewEmbed'

export default function ETFHeatmapWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-etf-heatmap.js"
      config={{
        dataSource: "AllUSEtf",
        blockSize: "aum",
        blockColor: "change",
        grouping: "asset_class",
        locale: "en",
        symbolUrl: "",
        colorTheme: "dark",
        hasTopBar: false,
        isDataSetEnabled: false,
        isZoomEnabled: true,
        hasSymbolTooltip: true,
        width: "100%",
        height: "100%",
      }}
    />
  )
}
