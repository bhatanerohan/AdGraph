import os
from dotenv import load_dotenv
from twelvelabs import TwelveLabs

load_dotenv()


def search_videos(query: str, index_id: str, top_k: int = 3):
    api_key = os.getenv("TWELVE_LABS_API_KEY")
    client = TwelveLabs(api_key=api_key)

    results = client.search.query(
        index_id=index_id,
        query_text=query,
        search_options=["visual"],
    )

    print(f"Top {top_k} results for '{query}':\n")
    for i, clip in enumerate(list(results)[:top_k], start=1):
        print(f"{i}. Video ID : {clip.video_id}")
        print(f"   Start    : {clip.start:.2f}s")
        print(f"   End      : {clip.end:.2f}s")
        print(f"   Score    : {clip.score:.4f}")
        print()


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: uv run python video_search.py <index_id> <query>")
        sys.exit(1)

    search_videos(query=sys.argv[2], index_id=sys.argv[1])
