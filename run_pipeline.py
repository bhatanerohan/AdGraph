"""
Ad-to-Brief Copilot Pipeline
Run this script, then view results in FiftyOne at localhost:5151.

Usage:
  uv run python run_pipeline.py --query "luxury cinematic" --index-id 69cfff9fff83935c54b822a0
"""
import argparse
import os
import time
from collections import Counter

import fiftyone as fo
from dotenv import load_dotenv

from ad_brief_copilot.twelvelabs_api import (
    get_client,
    search_videos,
    extract_traits,
    extract_scene_chapters,
    generate_brief,
)

load_dotenv()

DATASET_NAME = "ad-campaign-refs"


def step1_search(client, index_id, query, top_k, dataset):
    print(f"\n--- Step 1: Searching for '{query}' ---")
    results = search_videos(client, index_id, query, top_k)
    score_map = {r["video_id"]: r["score"] for r in results}

    for sample in dataset:
        vid = sample["twelvelabs_video_id"]
        if vid in score_map:
            sample["relevance_score"] = score_map[vid]
            sample.save()

    view = dataset.match(
        fo.ViewField("twelvelabs_video_id").is_in(list(score_map.keys()))
    )
    print(f"  Found {len(results)} matching videos")
    for r in results:
        print(f"  - {r['video_id']} (score: {r['score']:.3f})")
    return view


def step2_extract(api_key, view):
    print(f"\n--- Step 2: Extracting traits for {len(view)} videos ---")
    for sample in view:
        vid = sample["twelvelabs_video_id"]
        print(f"  Analyzing {sample.filepath.split('/')[-1]}...", end=" ", flush=True)

        traits = extract_traits(api_key, vid)
        sample["hook_type"] = traits.get("hook_type")
        sample["pacing"] = traits.get("pacing")
        sample["tone"] = traits.get("tone")
        sample["cta_style"] = traits.get("cta_style")
        sample["visual_style"] = traits.get("visual_style")
        sample["first_3_seconds"] = traits.get("first_3_seconds")
        sample["talent_type"] = traits.get("talent_type")
        sample["product_visibility"] = traits.get("product_visibility")

        chapters = extract_scene_chapters(api_key, vid)
        if chapters:
            sample["chapters"] = chapters

        sample.save()
        print("done")
        time.sleep(0.5)

    print(f"  Traits extracted for {len(view)} videos")


def step3_synthesize(view, dataset):
    print(f"\n--- Step 3: Synthesizing patterns ---")
    trait_fields = ["hook_type", "pacing", "tone", "cta_style", "visual_style", "talent_type", "product_visibility"]
    trait_values = {f: [] for f in trait_fields}

    for sample in view:
        for field in trait_fields:
            try:
                value = sample[field]
                if value:
                    trait_values[field].append(value)
            except Exception:
                pass

    n = max(len(v) for v in trait_values.values()) if any(trait_values.values()) else 0

    rows = []
    dominant_info = {}
    for field in trait_fields:
        counter = Counter(trait_values[field])
        label = field.replace("_", " ").title()
        if counter:
            dominant, count = counter.most_common(1)[0]
            rows.append(f"| {label} | {dominant} | {count}/{n} |")
            dominant_info[field] = (dominant, count)
        else:
            rows.append(f"| {label} | N/A | 0/{n} |")

    insights = []
    labels = {
        "hook_type": lambda d, c: f"- {c} of {n} ads use a **{d}** hook approach",
        "pacing": lambda d, c: f"- **{d}** pacing dominates with {c}/{n} videos",
        "tone": lambda d, c: f"- The prevailing tone is **{d}** ({c}/{n} videos)",
        "cta_style": lambda d, c: f"- Most ads use a **{d}** CTA style ({c}/{n})",
        "visual_style": lambda d, c: f"- **{d}** is the dominant visual style ({c}/{n})",
        "talent_type": lambda d, c: f"- Most ads feature **{d}** talent ({c}/{n})",
        "product_visibility": lambda d, c: f"- Product visibility is typically **{d}** ({c}/{n})",
    }
    for field, fn in labels.items():
        if field in dominant_info:
            d, c = dominant_info[field]
            insights.append(fn(d, c))

    markdown = (
        f"## Pattern Analysis ({n} videos)\n\n"
        f"| Trait | Dominant | Count |\n"
        f"|---|---|---|\n"
        + "\n".join(rows)
        + f"\n\n### Key Insights\n"
        + "\n".join(insights)
    )

    dataset.info["pattern_summary"] = markdown
    dataset.save()

    print(markdown)
    return markdown


def step4_brief(api_key, view, dataset, brand_context=""):
    print(f"\n--- Step 4: Generating creative brief ---")
    pattern_summary = dataset.info.get("pattern_summary", "No patterns available.")

    # Use first video in view as reference
    top_sample = view.first()
    top_vid = top_sample["twelvelabs_video_id"]
    print(f"  Using {top_sample.filepath.split('/')[-1]} as reference video")

    brief = generate_brief(api_key, top_vid, pattern_summary, brand_context)

    dataset.info["creative_brief"] = brief
    dataset.save()

    print(f"\n{'='*60}")
    print("CREATIVE BRIEF")
    print(f"{'='*60}")
    print(brief)
    return brief


def main():
    parser = argparse.ArgumentParser(description="Ad-to-Brief Copilot Pipeline")
    parser.add_argument("--query", required=True, help="Search query (e.g. 'luxury cinematic')")
    parser.add_argument("--index-id", required=True, help="Twelve Labs index ID")
    parser.add_argument("--top-k", type=int, default=6, help="Number of search results")
    parser.add_argument("--brand-context", default="", help="Optional brand context for brief")
    args = parser.parse_args()

    api_key = os.getenv("TWELVE_LABS_API_KEY")
    if not api_key:
        raise ValueError("TWELVE_LABS_API_KEY not set in .env")

    client = get_client(api_key)
    dataset = fo.load_dataset(DATASET_NAME)

    view = step1_search(client, args.index_id, args.query, args.top_k, dataset)
    step2_extract(api_key, view)
    step3_synthesize(view, dataset)
    step4_brief(api_key, view, dataset, args.brand_context)

    print(f"\n--- Done! View results in FiftyOne at localhost:5151 ---")
    print(f"  All traits, chapters, patterns, and brief are saved to the dataset.")
    print(f"  Refresh the FiftyOne app to see updated fields in the sidebar.")


if __name__ == "__main__":
    main()
