"""Compute text embeddings for Discord messages using sentence-transformers.

Usage:
    python tools/compute_text_embeddings.py --input output/enriched.parquet --output output/preprocessed/
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to enriched parquet")
    parser.add_argument("--output", required=True, help="Output directory for embeddings")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(args.input)
    print(f"Loaded {len(df)} rows")

    text_col = None
    for col in ["entry_message_raw", "raw_message", "message", "content"]:
        if col in df.columns:
            text_col = col
            break

    if text_col is None:
        print("No text column found, generating zero embeddings")
        embeddings = np.zeros((len(df), 384), dtype=np.float32)
        np.save(output_dir / "text_embeddings.npy", embeddings)
        return

    texts = df[text_col].fillna("").astype(str).tolist()
    print(f"Encoding {len(texts)} messages...")

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts, show_progress_bar=True, batch_size=64)
        embeddings = np.array(embeddings, dtype=np.float32)
    except ImportError:
        print("sentence-transformers not installed, using TF-IDF fallback")
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD

        tfidf = TfidfVectorizer(max_features=5000, stop_words="english")
        X_tfidf = tfidf.fit_transform(texts)
        svd = TruncatedSVD(n_components=384)
        embeddings = svd.fit_transform(X_tfidf).astype(np.float32)

    np.save(output_dir / "text_embeddings.npy", embeddings)
    print(f"Saved text embeddings: shape={embeddings.shape} to {output_dir / 'text_embeddings.npy'}")


if __name__ == "__main__":
    main()
