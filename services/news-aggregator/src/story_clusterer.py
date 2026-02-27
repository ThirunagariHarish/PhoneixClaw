import hashlib
import logging

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 85


def cluster_headlines(headlines: list[dict]) -> list[dict]:
    """Group similar headlines by fuzzy title matching.
    Assigns cluster_id and cluster_size to each headline."""
    if not headlines:
        return headlines

    clusters: list[list[int]] = []
    assigned = set()

    for i, h1 in enumerate(headlines):
        if i in assigned:
            continue
        cluster = [i]
        assigned.add(i)
        for j in range(i + 1, len(headlines)):
            if j in assigned:
                continue
            score = fuzz.token_sort_ratio(h1.get("title", ""), headlines[j].get("title", ""))
            if score >= SIMILARITY_THRESHOLD:
                cluster.append(j)
                assigned.add(j)
        clusters.append(cluster)

    for cluster_indices in clusters:
        representative_title = headlines[cluster_indices[0]].get("title", "")
        cluster_id = hashlib.md5(representative_title[:80].encode()).hexdigest()[:16]
        for idx in cluster_indices:
            headlines[idx]["cluster_id"] = cluster_id
            headlines[idx]["cluster_size"] = len(cluster_indices)

    logger.info("Clustered %d headlines into %d groups", len(headlines), len(clusters))
    return headlines
