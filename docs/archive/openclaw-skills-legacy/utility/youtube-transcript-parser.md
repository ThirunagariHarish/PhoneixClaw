# YouTube Transcript Parser

## Purpose
Extract and parse YouTube video transcripts for behavior learning, sentiment analysis, or content summarization.

## Category
utility

## Triggers
- When user provides YouTube URL for analysis
- When building behavior profile from trader/influencer videos
- When extracting trading ideas or sentiment from video content
- When agent needs to process video content as text

## Inputs
- `url`: string — YouTube video URL or video ID
- `language`: string — Preferred transcript language (default: "en")
- `include_timestamps`: boolean — Include timestamps in output (default: true)
- `format`: string — "text", "json", "srt" (default: "text")
- `max_length`: number — Max chars to return (default: no limit)

## Outputs
- `transcript`: string — Full transcript text (or truncated)
- `segments`: object[] — [{start, end, text}] if include_timestamps
- `duration_seconds`: number — Video duration
- `title`: string — Video title
- `channel`: string — Channel name
- `metadata`: object — url, language, format, fetched_at

## Steps
1. Parse URL to extract video ID
2. Fetch transcript via YouTube transcript API (youtube-transcript-api or similar)
3. If language specified: request that language; fallback to auto-generated if needed
4. Parse transcript into segments with start/end times
5. If format="text": concatenate segments; if "json": return structured; if "srt": format as SRT
6. Fetch video metadata (title, channel, duration) from YouTube API or oEmbed
7. Apply max_length truncation if specified
8. Return transcript, segments, duration_seconds, title, channel, metadata
9. Cache transcripts by video ID to avoid repeated fetches
10. Handle private/deleted videos gracefully

## Example
```
Input: url="https://www.youtube.com/watch?v=abc123", language="en", format="text"
Output: {
  transcript: "Hey everyone, today we're looking at NVDA...",
  segments: [{start: 0, end: 5.2, text: "Hey everyone..."}, ...],
  duration_seconds: 1200,
  title: "NVDA Trade Setup - March 2025",
  channel: "TradingWithJohn",
  metadata: {url: "https://youtube.com/watch?v=abc123", language: "en", fetched_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- youtube-transcript-api (Python) or youtube-transcript (npm) for extraction
- Some videos have no transcript; return clear error
- Auto-generated transcripts may have errors; consider confidence scores if available
