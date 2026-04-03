import json
import re
import time

from twelvelabs import TwelveLabs


TRAIT_EXTRACTION_PROMPT = """Analyze this ad video and return ONLY a JSON object with these exact fields:
{
  "hook_type": "<one of: question, stat, emotion, product-first>",
  "pacing": "<one of: fast-cuts, slow-build, single-shot>",
  "tone": "<one of: aspirational, humorous, urgent, educational>",
  "cta_style": "<one of: direct, soft, none>",
  "visual_style": "<one of: cinematic, lo-fi, text-heavy, product-closeup>",
  "first_3_seconds": "<one sentence describing exactly what happens in the first 3 seconds>",
  "talent_type": "<one of: none, actor, ugc-creator, brand-mascot>",
  "product_visibility": "<one of: early, late, throughout, none>"
}
Return only the JSON object, no other text."""

BRIEF_GENERATION_PROMPT = """You are a creative strategist. Here is a pattern analysis of top-performing reference ads:

{pattern_summary}

{brand_context_section}

Using this video as additional creative inspiration, generate a creative brief with:
1. Recommended hook approach (and why, based on the patterns above)
2. Pacing template
3. CTA strategy
4. Three distinct ad concepts inspired by these patterns

Format the output as clean markdown."""


def get_client(api_key: str) -> TwelveLabs:
    return TwelveLabs(api_key=api_key)


def search_videos(client: TwelveLabs, index_id: str, query: str, top_k: int) -> list[dict]:
    results = client.search.query(
        index_id=index_id,
        query_text=query,
        search_options=["visual"],
        group_by="video",
        page_limit=top_k,
    )

    output = []
    for item in results:
        output.append({
            "video_id": item.id,
            "score": item.score if hasattr(item, "score") else 0.0,
        })

    return output


def extract_traits(api_key: str, video_id: str) -> dict:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"extract_traits called with api_key type={type(api_key).__name__}, video_id={video_id}")
    logger.warning(f"TwelveLabs imported from: {TwelveLabs.__module__}")

    client = get_client(api_key)
    logger.warning(f"client type={type(client).__name__}, has analyze={hasattr(client, 'analyze')}")

    response = client.analyze(
        video_id=video_id,
        prompt=TRAIT_EXTRACTION_PROMPT,
    )
    response_text = response.data

    try:
        return json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {}


def extract_scene_chapters(api_key: str, video_id: str) -> list[dict]:
    """Extract timestamped chapters from the video."""
    try:
        client = get_client(api_key)
        response = client.analyze(
            video_id=video_id,
            prompt="List the chapters of this video as a JSON array with fields: title, summary, start, end. Return only valid JSON.",
        )
        text = response.data
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return []
    except Exception:
        return []


def generate_brief(api_key: str, video_id: str, pattern_summary: str, brand_context: str = "") -> str:
    brand_context_section = ""
    if brand_context:
        brand_context_section = f"Brand/Product Context: {brand_context}"

    prompt = BRIEF_GENERATION_PROMPT.format(
        pattern_summary=pattern_summary,
        brand_context_section=brand_context_section,
    )

    client = get_client(api_key)
    response = client.analyze(
        video_id=video_id,
        prompt=prompt,
    )
    return response.data


def index_videos_from_urls(api_key: str, index_name: str, video_urls: list[str]) -> dict:
    """
    Creates a new Twelve Labs index with Marengo + Pegasus, uploads the given video URLs,
    polls until all tasks complete, and returns {"index_id": ..., "video_map": {url: video_id}}.
    """
    client = get_client(api_key)

    index = client.indexes.create(
        index_name=index_name,
        models=[
            {"model_name": "marengo3.0", "model_options": ["visual", "audio"]},
            {"model_name": "pegasus1.2", "model_options": ["visual", "audio"]},
        ],
    )

    video_map = {}
    for url in video_urls:
        task = client.tasks.create(index_id=index.id, video_url=url)
        task_id = task.id
        print(f"  Uploading {url.split('/')[-1]} (task {task_id})...")
        while True:
            status = client.tasks.retrieve(task_id)
            if status.status == "ready":
                video_map[url] = status.video_id
                print(f"  ✓ {url.split('/')[-1]} → {status.video_id}")
                break
            elif status.status == "failed":
                video_map[url] = None
                print(f"  ✗ {url.split('/')[-1]} failed")
                break
            time.sleep(5)

    return {"index_id": index.id, "video_map": video_map}
