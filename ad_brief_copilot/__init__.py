import os
import json
import re
import time
from collections import Counter

import fiftyone.operators as foo
import fiftyone.operators.types as types
from fiftyone import ViewField as F

from .twelvelabs_api import get_client, search_videos, extract_traits, generate_brief as tl_generate_brief


class SearchAdReferences(foo.Operator):
    @property
    def config(self):
        return foo.OperatorConfig(
            name="search_ad_references",
            label="Search Ad References",
        )

    def resolve_input(self, ctx):
        inputs = types.Object()
        inputs.str("query", required=True, label="Search Query")
        inputs.str("index_id", required=True, label="Twelve Labs Index ID")
        inputs.int("top_k", default=10, label="Number of Results")
        return types.Property(inputs)

    def execute(self, ctx):
        api_key = ctx.secret("TWELVE_LABS_API_KEY") or os.getenv("TWELVE_LABS_API_KEY")
        client = get_client(api_key)

        query = ctx.params["query"]
        index_id = ctx.params["index_id"]
        top_k = ctx.params.get("top_k", 10)

        results = search_videos(client, index_id, query, top_k)

        score_map = {r["video_id"]: r["score"] for r in results}

        view = ctx.dataset.match(
            F("twelvelabs_video_id").is_in(list(score_map.keys()))
        )

        for sample in view:
            sample["relevance_score"] = score_map.get(
                sample["twelvelabs_video_id"], 0.0
            )
            sample.save()

        ctx.ops.set_view(view=view)

        return {"message": f"Found {len(results)} matching videos"}

    def resolve_output(self, ctx):
        outputs = types.Object()
        outputs.str("message", label="Result")
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
        api_key = ctx.secret("TWELVE_LABS_API_KEY") or os.getenv("TWELVE_LABS_API_KEY")
        client = get_client(api_key)

        count = 0
        for sample in ctx.view:
            video_id = sample.get("twelvelabs_video_id")
            if not video_id:
                continue

            traits = extract_traits(client, video_id)

            sample["hook_type"] = traits.get("hook_type")
            sample["pacing"] = traits.get("pacing")
            sample["tone"] = traits.get("tone")
            sample["cta_style"] = traits.get("cta_style")
            sample["visual_style"] = traits.get("visual_style")
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
        trait_fields = ["hook_type", "pacing", "tone", "cta_style", "visual_style"]
        trait_values = {field: [] for field in trait_fields}

        for sample in ctx.view:
            for field in trait_fields:
                value = sample.get(field)
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
            "top_video_id",
            required=True,
            label="Reference Video ID (from search results)",
        )
        inputs.str(
            "brand_context",
            required=False,
            label="Brand/Product Context (optional)",
        )
        return types.Property(inputs)

    def execute(self, ctx):
        api_key = ctx.secret("TWELVE_LABS_API_KEY") or os.getenv("TWELVE_LABS_API_KEY")
        client = get_client(api_key)

        top_video_id = ctx.params["top_video_id"]
        brand_context = ctx.params.get("brand_context", "")

        pattern_summary = ctx.dataset.info.get(
            "pattern_summary", "No pattern analysis available."
        )

        brief_text = tl_generate_brief(
            client, top_video_id, pattern_summary, brand_context
        )

        return {"brief": brief_text}

    def resolve_output(self, ctx):
        outputs = types.Object()
        outputs.str("brief", label="Creative Brief", view=types.MarkdownView())
        return types.Property(outputs)


def register(p):
    p.register(SearchAdReferences)
    p.register(ExtractAdTraits)
    p.register(SynthesizePatterns)
    p.register(GenerateBrief)
