import json
import re

from twelvelabs import TwelveLabs


TRAIT_EXTRACTION_PROMPT = """Analyze this ad video and return ONLY a JSON object with these exact fields:
{"hook_type": "<one of: question, stat, emotion, product-first>", "pacing": "<one of: fast-cuts, slow-build, single-shot>", "tone": "<one of: aspirational, humorous, urgent, educational>", "cta_style": "<one of: direct, soft, none>", "visual_style": "<one of: cinematic, lo-fi, text-heavy, product-closeup>"}
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


def extract_traits(client: TwelveLabs, video_id: str) -> dict:
    response = client.generate.text(
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


def generate_brief(client: TwelveLabs, video_id: str, pattern_summary: str, brand_context: str = "") -> str:
    brand_context_section = ""
    if brand_context:
        brand_context_section = f"Brand/Product Context: {brand_context}"

    prompt = BRIEF_GENERATION_PROMPT.format(
        pattern_summary=pattern_summary,
        brand_context_section=brand_context_section,
    )

    response = client.generate.text(
        video_id=video_id,
        prompt=prompt,
    )
    return response.data
