import TradingViewEmbed from './TradingViewEmbed'

export default function TickerTapeWidget() {
  return (
    <TradingViewEmbed
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js"
      config={{
        symbols: [
          { proName: "FOREXCOM:SPXUSD", title: "S&P 500" },
          { proName: "FOREXCOM:NSXUSD", title: "US 100" },
          { proName: "BITSTAMP:BTCUSD", title: "Bitcoin" },
          { proName: "BITSTAMP:ETHUSD", title: "Ethereum" },
          { proName: "FX_IDC:EURUSD", title: "EUR to USD" },
          { proName: "FX_IDC:USDJPY", title: "USD to JPY" },
          { proName: "AMEX:SPY", title: "SPY" },
          { proName: "NASDAQ:QQQ", title: "QQQ" },
          { proName: "AMEX:DIA", title: "DIA" },
          { proName: "AMEX:IWM", title: "IWM" },
        ],
        showSymbolLogo: true,
        isTransparent: true,
        displayMode: "adaptive",
        colorTheme: "dark",
        locale: "en",
      }}
    />
  )
}
