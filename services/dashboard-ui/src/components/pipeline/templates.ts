import type { Node, Edge } from '@xyflow/react'

interface PipelineTemplate {
  name: string
  description: string
  nodes: Node[]
  edges: Edge[]
}

export const defaultTemplates: PipelineTemplate[] = [
  {
    name: 'Discord to Alpaca',
    description: 'Simple pipeline: Discord signals → Trade Parser → Alpaca execution',
    nodes: [
      { id: 'n1', type: 'dataSource', position: { x: 50, y: 150 }, data: { label: 'Discord', subtype: 'discord' } },
      { id: 'n2', type: 'processing', position: { x: 300, y: 150 }, data: { label: 'Trade Parser', subtype: 'parser' } },
      { id: 'n3', type: 'broker', position: { x: 550, y: 150 }, data: { label: 'Trading Account', broker_type: '' } },
    ],
    edges: [
      { id: 'e1-2', source: 'n1', target: 'n2', animated: true },
      { id: 'e2-3', source: 'n2', target: 'n3', animated: true },
    ],
  },
  {
    name: 'Sentiment → AI → Trade',
    description: 'Sentiment analysis pipeline with AI trade recommendation',
    nodes: [
      { id: 'n1', type: 'dataSource', position: { x: 50, y: 150 }, data: { label: 'Sentiment Feed', subtype: 'sentiment' } },
      { id: 'n2', type: 'processing', position: { x: 280, y: 150 }, data: { label: 'Sentiment Analyzer', subtype: 'sentiment_analyzer' } },
      { id: 'n3', type: 'aiModel', position: { x: 510, y: 100 }, data: { label: 'Option Analyzer', subtype: 'option_analyzer' } },
      { id: 'n4', type: 'aiModel', position: { x: 510, y: 220 }, data: { label: 'AI Recommender', subtype: 'trade_recommender' } },
      { id: 'n5', type: 'broker', position: { x: 770, y: 150 }, data: { label: 'Trading Account', broker_type: '' } },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2', animated: true },
      { id: 'e2', source: 'n2', target: 'n3', animated: true },
      { id: 'e3', source: 'n2', target: 'n4', animated: true },
      { id: 'e4', source: 'n3', target: 'n5', animated: true },
      { id: 'e5', source: 'n4', target: 'n5', animated: true },
    ],
  },
  {
    name: 'News → AI Trade',
    description: 'News headlines analyzed by AI for automated trading',
    nodes: [
      { id: 'n1', type: 'dataSource', position: { x: 50, y: 150 }, data: { label: 'News Feed', subtype: 'news' } },
      { id: 'n2', type: 'processing', position: { x: 280, y: 150 }, data: { label: 'Ticker Extractor', subtype: 'ticker_extractor' } },
      { id: 'n3', type: 'aiModel', position: { x: 510, y: 150 }, data: { label: 'LLM Analyzer', subtype: 'mistral' } },
      { id: 'n4', type: 'control', position: { x: 740, y: 150 }, data: { label: 'Market Hours', subtype: 'market_hours' } },
      { id: 'n5', type: 'broker', position: { x: 970, y: 150 }, data: { label: 'Trading Account', broker_type: '' } },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2', animated: true },
      { id: 'e2', source: 'n2', target: 'n3', animated: true },
      { id: 'e3', source: 'n3', target: 'n4', animated: true },
      { id: 'e4', source: 'n4', target: 'n5', animated: true },
    ],
  },
  {
    name: 'Multi-Source Confluence',
    description: 'Combine Discord, sentiment, and news for high-confidence trades',
    nodes: [
      { id: 'n1', type: 'dataSource', position: { x: 50, y: 50 }, data: { label: 'Discord', subtype: 'discord' } },
      { id: 'n2', type: 'dataSource', position: { x: 50, y: 180 }, data: { label: 'Sentiment', subtype: 'sentiment' } },
      { id: 'n3', type: 'dataSource', position: { x: 50, y: 310 }, data: { label: 'News', subtype: 'news' } },
      { id: 'n4', type: 'aiModel', position: { x: 350, y: 180 }, data: { label: 'AI Recommender', subtype: 'trade_recommender' } },
      { id: 'n5', type: 'control', position: { x: 600, y: 180 }, data: { label: 'Confidence > 0.7', subtype: 'condition', expression: 'confidence > 0.7' } },
      { id: 'n6', type: 'broker', position: { x: 850, y: 180 }, data: { label: 'Trading Account', broker_type: '' } },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n4', animated: true },
      { id: 'e2', source: 'n2', target: 'n4', animated: true },
      { id: 'e3', source: 'n3', target: 'n4', animated: true },
      { id: 'e4', source: 'n4', target: 'n5', animated: true },
      { id: 'e5', source: 'n5', target: 'n6', animated: true },
    ],
  },
]
