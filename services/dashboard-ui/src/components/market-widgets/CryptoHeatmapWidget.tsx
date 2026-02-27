import TradingViewEmbed from './TradingViewEmbed'

export default function CryptoHeatmapWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-crypto-coins-heatmap.js"
      config={{
        dataSource: "Crypto",
        blockSize: "market_cap_calc",
        blockColor: "change",
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
