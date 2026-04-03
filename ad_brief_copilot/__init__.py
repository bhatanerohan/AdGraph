import os
import sys
import json
import re
import time
from collections import Counter
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/Desktop/Hack/12labs/.env"))

# Ensure the project venv's packages take priority
_venv_site = os.path.expanduser("~/Desktop/Hack/12labs/.venv/lib/python3.11/site-packages")
if _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

import fiftyone as fo
import fiftyone.operators as foo
import fiftyone.operators.types as types
from fiftyone import ViewField as F

from .twelvelabs_api import get_client, search_videos, extract_traits, extract_scene_chapters, generate_brief as tl_generate_brief, index_videos_from_urls


class SearchAdReferences(foo.Operator):
    @property
    def config(self):
        return foo.OperatorConfig(
            name="search_ad_references",
            label="Search Ad References",
        )

    def resolve_input(self, ctx):
        inputs = types.Object()
        inputs.str("query", required=True, label="Describe the campaign you want references for")
        inputs.int("top_k", default=6, label="Number of Results")
        return types.Property(inputs)

    def execute(self, ctx):
        import math
        from twelvelabs import TwelveLabs as TL

        api_key = ctx.secret("TWELVE_LABS_API_KEY") or os.getenv("TWELVE_LABS_API_KEY")
        client = TL(api_key=api_key)

        query = ctx.params["query"]
        index_id = ctx.dataset.info.get("index_id", "")
        top_k = ctx.params.get("top_k", 6)

        # Get text embedding for the query
        resp = client.embed.create(model_name="marengo3.0", text=query)
        query_vec = resp.text_embedding.segments[0].float_ if resp.text_embedding and resp.text_embedding.segments else []

        if not query_vec:
            return {"message": "Failed to create text embedding"}

        # Score each video by embedding cosine similarity
        scored = []
        for sample in ctx.dataset:
            try:
                vid_id = sample["twelvelabs_video_id"]
            except (KeyError, AttributeError):
                continue

            asset = client.indexes.indexed_assets.retrieve(index_id, vid_id, embedding_option=["visual"])
            vid_vec = None
            for seg in (asset.embedding.video_embedding.segments or []):
                if seg.embedding_scope == "video" and seg.float_:
                    vid_vec = seg.float_
                    break
            if not vid_vec:
                clips = [s.float_ for s in (asset.embedding.video_embedding.segments or []) if s.embedding_scope == "clip" and s.float_]
                if clips:
                    dim = len(clips[0])
                    vid_vec = [sum(v[i] for v in clips) / len(clips) for i in range(dim)]

            if vid_vec:
                dot = sum(x * y for x, y in zip(query_vec, vid_vec))
                na = math.sqrt(sum(x * x for x in query_vec))
                nb = math.sqrt(sum(x * x for x in vid_vec))
                score = dot / (na * nb) if na and nb else 0.0
                scored.append({"video_id": vid_id, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:top_k]
        score_map = {r["video_id"]: r["score"] for r in results}

        for sample in ctx.dataset:
            try:
                vid_id = sample["twelvelabs_video_id"]
                sample["relevance_score"] = score_map.get(vid_id, 0.0)
                sample.save()
            except (KeyError, AttributeError):
                pass

        view = ctx.dataset.sort_by("relevance_score", reverse=True)
        ctx.ops.set_view(view=view)

        # Build a video_id → filename map
        id_to_name = {}
        for sample in ctx.dataset:
            try:
                vid_id = sample["twelvelabs_video_id"]
                id_to_name[vid_id] = sample.filepath.split("/")[-1]
            except (KeyError, AttributeError):
                pass

        top = results[0] if results else None
        msg = f"## Embedding Similarity Results\n\n"
        msg += f"Query: **{query}**\n\n"
        msg += "| Rank | Ad | Score |\n|---|---|---|\n"
        for i, r in enumerate(results):
            name = id_to_name.get(r["video_id"], r["video_id"])
            msg += f"| {i+1} | {name} | {r['score']:.4f} |\n"
        if top:
            top_name = id_to_name.get(top["video_id"], top["video_id"])
            msg += f"\n**Top reference ad:** {top_name}"
        return {"message": msg}

    def resolve_output(self, ctx):
        outputs = types.Object()
        outputs.str("message", label="Result", view=types.MarkdownView())
        return types.Property(outputs)


class ExtractAdTraits(foo.Operator):
    @property
    def config(self):
        return foo.OperatorConfig(
            name="extract_ad_traits",
            label="Extract Ad Traits",
        )

    def resolve_input(self, ctx):
        inputs = types.Object()
        return types.Property(inputs)

    def execute(self, ctx):
        from twelvelabs import TwelveLabs as TL

        api_key = ctx.secret("TWELVE_LABS_API_KEY") or os.getenv("TWELVE_LABS_API_KEY")
        client = TL(api_key=api_key)

        trait_prompt = (
            'Analyze this ad video and return ONLY a JSON object with these exact fields: '
            '{"hook_type": "<one of: question, stat, emotion, product-first>", '
            '"pacing": "<one of: fast-cuts, slow-build, single-shot>", '
            '"tone": "<one of: aspirational, humorous, urgent, educational>", '
            '"cta_style": "<one of: direct, soft, none>", '
            '"visual_style": "<one of: cinematic, lo-fi, text-heavy, product-closeup>", '
            '"first_3_seconds": "<one sentence describing exactly what happens in the first 3 seconds>", '
            '"talent_type": "<one of: none, actor, ugc-creator, brand-mascot>", '
            '"product_visibility": "<one of: early, late, throughout, none>"} '
            'Return only the JSON object, no other text.'
        )

        count = 0
        for sample in ctx.view:
            try:
                video_id = sample["twelvelabs_video_id"]
            except AttributeError:
                continue
            if not video_id:
                continue

            # Extract traits via analyze
            resp = client.analyze(video_id=video_id, prompt=trait_prompt)
            raw = resp.data
            try:
                traits = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
                traits = json.loads(match.group()) if match else {}

            sample["hook_type"] = traits.get("hook_type")
            sample["pacing"] = traits.get("pacing")
            sample["tone"] = traits.get("tone")
            sample["cta_style"] = traits.get("cta_style")
            sample["visual_style"] = traits.get("visual_style")
            sample["first_3_seconds"] = traits.get("first_3_seconds")
            sample["talent_type"] = traits.get("talent_type")
            sample["product_visibility"] = traits.get("product_visibility")

            # Extract chapters
            try:
                ch_resp = client.analyze(
                    video_id=video_id,
                    prompt="List the chapters of this video as a JSON array with fields: title, summary, start, end. Return only valid JSON.",
                )
                ch_match = re.search(r'\[.*\]', ch_resp.data, re.DOTALL)
                if ch_match:
                    sample["chapters"] = json.loads(ch_match.group())
            except Exception:
                pass

            sample.save()
            count += 1
            time.sleep(0.5)

        ctx.ops.reload_dataset()

        return {"message": f"Extracted traits for {count} videos"}

    def resolve_output(self, ctx):
        outputs = types.Object()
        outputs.str("message", label="Result")
        return types.Property(outputs)


class SynthesizePatterns(foo.Operator):
    @property
    def config(self):
        return foo.OperatorConfig(
            name="synthesize_patterns",
            label="Synthesize Patterns",
        )

    def resolve_input(self, ctx):
        inputs = types.Object()
        return types.Property(inputs)

    def execute(self, ctx):
        trait_fields = ["hook_type", "pacing", "tone", "cta_style", "visual_style", "talent_type", "product_visibility"]
        trait_values = {field: [] for field in trait_fields}

        for sample in ctx.view:
            for field in trait_fields:
                try:
                    value = sample[field]
                except AttributeError:
                    value = None
                if value:
                    trait_values[field].append(value)

        n = max(len(v) for v in trait_values.values()) if trait_values else 0

        rows = []
        dominant_info = {}
        for field in trait_fields:
            counter = Counter(trait_values[field])
            if counter:
                dominant, count = counter.most_common(1)[0]
                label = field.replace("_", " ").title()
                rows.append(f"| {label} | {dominant} | {count}/{n} |")
                dominant_info[field] = (dominant, count)
            else:
                label = field.replace("_", " ").title()
                rows.append(f"| {label} | N/A | 0/{n} |")

        table_rows = "\n".join(rows)

        insights = []
        if "hook_type" in dominant_info:
            d, c = dominant_info["hook_type"]
            insights.append(f"- {c} of {n} ads use a **{d}** hook approach")
        if "pacing" in dominant_info:
            d, c = dominant_info["pacing"]
            insights.append(f"- **{d}** pacing dominates with {c}/{n} videos")
        if "tone" in dominant_info:
            d, c = dominant_info["tone"]
            insights.append(f"- The prevailing tone is **{d}** ({c}/{n} videos)")
        if "cta_style" in dominant_info:
            d, c = dominant_info["cta_style"]
            insights.append(f"- Most ads use a **{d}** CTA style ({c}/{n})")
        if "visual_style" in dominant_info:
            d, c = dominant_info["visual_style"]
            insights.append(f"- **{d}** is the dominant visual style ({c}/{n})")
        if "talent_type" in dominant_info:
            d, c = dominant_info["talent_type"]
            insights.append(f"- Most ads feature **{d}** talent ({c}/{n})")
        if "product_visibility" in dominant_info:
            d, c = dominant_info["product_visibility"]
            insights.append(f"- Product visibility is typically **{d}** ({c}/{n})")

        insights_text = "\n".join(insights)

        markdown = (
            f"## Pattern Analysis ({n} videos)\n\n"
            f"| Trait | Dominant | Count |\n"
            f"|---|---|---|\n"
            f"{table_rows}\n\n"
            f"### Key Insights\n"
            f"{insights_text}"
        )

        ctx.dataset.info["pattern_summary"] = markdown
        ctx.dataset.save()

        return {"summary": markdown}

    def resolve_output(self, ctx):
        outputs = types.Object()
        outputs.str("summary", label="Pattern Summary", view=types.MarkdownView())
        return types.Property(outputs)


class GenerateBrief(foo.Operator):
    @property
    def config(self):
        return foo.OperatorConfig(
            name="generate_brief",
            label="Generate Creative Brief",
        )

    def resolve_input(self, ctx):
        inputs = types.Object()
        inputs.str(
            "brand_context",
            required=True,
            label="Brand/Product Context (e.g. 'luxury electric vehicle launch')",
        )
        return types.Property(inputs)

    def execute(self, ctx):
        from twelvelabs import TwelveLabs as TL

        api_key = ctx.secret("TWELVE_LABS_API_KEY") or os.getenv("TWELVE_LABS_API_KEY")
        client = TL(api_key=api_key)

        brand_context = ctx.params["brand_context"]

        # Auto-pick the top-scored video from the current view
        best_sample = None
        best_score = -1
        for sample in ctx.view:
            try:
                score = sample["relevance_score"]
                if score is not None and score > best_score:
                    best_score = score
                    best_sample = sample
            except (KeyError, AttributeError):
                pass

        # Fallback to first sample if no scores
        if best_sample is None:
            best_sample = ctx.view.first()

        top_video_id = best_sample["twelvelabs_video_id"]

        pattern_summary = ctx.dataset.info.get(
            "pattern_summary", "No pattern analysis available."
        )

        prompt = (
            f"You are a creative strategist. Here is a pattern analysis of top-performing reference ads:\n\n"
            f"{pattern_summary}\n\n"
            f"Brand/Product Context: {brand_context}\n\n"
            f"Using this video as additional creative inspiration, generate a creative brief with:\n"
            f"1. Recommended hook approach (and why, based on the patterns above)\n"
            f"2. Pacing template\n"
            f"3. CTA strategy\n"
            f"4. Three distinct ad concepts inspired by these patterns\n\n"
            f"Format the output as clean markdown."
        )

        response = client.analyze(video_id=top_video_id, prompt=prompt)
        brief_text = response.data

        return {"brief": brief_text}

    def resolve_output(self, ctx):
        outputs = types.Object()
        outputs.str("brief", label="Creative Brief", view=types.MarkdownView())
        return types.Property(outputs)


class IndexVideos(foo.Operator):
    @property
    def config(self):
        return foo.OperatorConfig(
            name="index_videos",
            label="Index Videos into Twelve Labs",
        )

    def resolve_input(self, ctx):
        inputs = types.Object()
        inputs.str("index_name", required=True, label="Index Name")
        inputs.str(
            "video_urls",
            required=True,
            label="Video URLs (one per line)",
            description="Paste public video URLs, one per line",
        )
        return types.Property(inputs)

    def execute(self, ctx):
        api_key = ctx.secret("TWELVE_LABS_API_KEY") or os.getenv("TWELVE_LABS_API_KEY")
        index_name = ctx.params["index_name"]
        raw_urls = ctx.params["video_urls"]
        video_urls = [u.strip() for u in raw_urls.splitlines() if u.strip()]

        result = index_videos_from_urls(api_key, index_name, video_urls)

        index_id = result["index_id"]
        video_map = result["video_map"]

        # Add indexed videos to current dataset
        dataset = ctx.dataset
        for url, vid_id in video_map.items():
            if vid_id is None:
                continue
            # Check if sample with this video_id already exists
            existing = dataset.match(F("twelvelabs_video_id") == vid_id)
            if len(existing) == 0:
                sample = fo.Sample(filepath=url)
                sample["twelvelabs_video_id"] = vid_id
                sample["source_url"] = url
                dataset.add_sample(sample)

        dataset.save()
        ctx.ops.reload_dataset()

        indexed_count = sum(1 for v in video_map.values() if v is not None)
        return {
            "message": f"Created index '{index_name}' (ID: {index_id}). Indexed {indexed_count}/{len(video_urls)} videos."
        }

    def resolve_output(self, ctx):
        outputs = types.Object()
        outputs.str("message", label="Result")
        return types.Property(outputs)


def register(p):
    p.register(IndexVideos)
    p.register(SearchAdReferences)
    p.register(ExtractAdTraits)
    p.register(SynthesizePatterns)
    p.register(GenerateBrief)
