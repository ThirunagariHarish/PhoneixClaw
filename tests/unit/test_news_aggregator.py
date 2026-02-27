from services.news_aggregator.src.importance_ranker import rank_headlines
from services.news_aggregator.src.story_clusterer import cluster_headlines


class TestStoryClustering:
    def test_clusters_similar_headlines(self):
        headlines = [
            {"title": "Apple earnings beat expectations"},
            {"title": "Apple earnings beat analyst expectations"},
            {"title": "Tesla deliveries down 10%"},
        ]
        result = cluster_headlines(headlines)
        assert len(result) == 3
        assert result[0]["cluster_id"] == result[1]["cluster_id"]
        assert result[0]["cluster_id"] != result[2]["cluster_id"]
        assert result[0]["cluster_size"] == 2
        assert result[2]["cluster_size"] == 1

    def test_single_headline_forms_own_cluster(self):
        headlines = [{"title": "Unique headline"}]
        result = cluster_headlines(headlines)
        assert len(result) == 1
        assert result[0]["cluster_size"] == 1
        assert "cluster_id" in result[0]

    def test_empty_list(self):
        result = cluster_headlines([])
        assert result == []


class TestImportanceRanker:
    def test_ranks_by_score(self):
        headlines = [
            {
                "title": "Breaking: Fed raises rates",
                "source_api": "finnhub",
                "tickers": ["SPY"],
                "sentiment_score": -0.8,
                "cluster_size": 3,
            },
            {
                "title": "Minor stock update",
                "source_api": "reddit",
                "tickers": [],
                "sentiment_score": 0,
                "cluster_size": 1,
            },
        ]
        ranked = rank_headlines(headlines)
        assert ranked[0]["title"] == "Breaking: Fed raises rates"
        assert ranked[0]["importance_score"] > ranked[1]["importance_score"]

    def test_all_get_scores(self):
        headlines = [
            {"title": "Headline A", "source_api": "newsapi", "tickers": [], "sentiment_score": 0, "cluster_size": 1},
            {
                "title": "Headline B", "source_api": "finnhub",
                "tickers": ["AAPL"], "sentiment_score": 0.5, "cluster_size": 2,
            },
        ]
        ranked = rank_headlines(headlines)
        assert all("importance_score" in h for h in ranked)
