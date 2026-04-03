# Ad-to-Brief Copilot

A FiftyOne plugin that turns a library of ad videos into data-driven creative briefs using Twelve Labs' Marengo and Pegasus models.

**Problem:** Creative strategists manually watch dozens of reference ads before writing a brief. It's slow, subjective, and doesn't scale.

**Solution:** Describe the campaign you're planning. The plugin finds the most relevant reference ads using Marengo embeddings, extracts structured creative traits with Pegasus, synthesizes dominant patterns, and generates a complete creative brief — all inside FiftyOne.

## How It Works

```
"phone launch campaign"
        ↓
Marengo text embedding + video embeddings → cosine similarity ranking
        ↓
Pegasus analyze() per video → 8 structured traits (hook, pacing, tone, CTA, etc.)
        ↓
Python aggregation → dominant pattern summary
        ↓
Pegasus analyze() + top video + patterns + brand context → creative brief
```

## Operators

| Operator | What it does | Twelve Labs API |
|---|---|---|
| **Search Ad References** | Ranks videos by embedding similarity to your campaign description | Marengo `embed.create()` + `indexed_assets.retrieve()` |
| **Extract Ad Traits** | Classifies each video across 8 creative dimensions | Pegasus `analyze()` |
| **Synthesize Patterns** | Aggregates traits, finds what top ads have in common | Pure Python (Counter) |
| **Generate Creative Brief** | Writes a full brief grounded in patterns + reference video | Pegasus `analyze()` |

## Extracted Traits

Each video gets classified on:
- **Hook type** — question, stat, emotion, product-first
- **Pacing** — fast-cuts, slow-build, single-shot
- **Tone** — aspirational, humorous, urgent, educational
- **CTA style** — direct, soft, none
- **Visual style** — cinematic, lo-fi, text-heavy, product-closeup
- **First 3 seconds** — free text description of the opening hook
- **Talent type** — none, actor, ugc-creator, brand-mascot
- **Product visibility** — early, late, throughout, none

## Setup

### Requirements
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [ffmpeg](https://ffmpeg.org/) (for FiftyOne video playback)
- Twelve Labs API key

### Install dependencies

```bash
uv sync
```

### Index your ad videos

Edit `VIDEO_URLS` in `index_ads.py` with public video URLs (e.g. from HuggingFace), then:

```bash
uv run python index_ads.py
```

This creates a Twelve Labs index with Marengo + Pegasus and builds the FiftyOne dataset.

### Install the plugin

```bash
# Symlink for development
ln -s $(pwd)/ad_brief_copilot ~/fiftyone/__plugins__/ad-brief-copilot
```

### Launch

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python launch.py
```

Open `localhost:5151` in your browser.

## Demo

1. Press `~` to open the operator panel
2. **Search Ad References** — type `phone launch campaign`
3. **Extract Ad Traits** — runs Pegasus on each video (~30s each)
4. **Synthesize Patterns** — see the trait breakdown table
5. **Generate Creative Brief** — type your brand context, get a full brief

Try different queries to see how the output changes:
- `luxury car cinematic` → aspirational, cinematic brief
- `fast-paced UGC product demo` → punchy, direct brief
- `phone launch campaign` → tech-focused, product-first brief

## Project Structure

```
├── ad_brief_copilot/
│   ├── fiftyone.yml          # Plugin metadata
│   ├── __init__.py           # 5 FiftyOne operators
│   ├── twelvelabs_api.py     # Twelve Labs SDK wrappers + embedding functions
│   └── README.md             # Plugin docs
├── index_ads.py              # One-time setup: index videos + create dataset
├── launch.py                 # Launch FiftyOne app with dataset
├── run_pipeline.py           # CLI alternative to run the full pipeline
└── videos/                   # Downloaded ad videos (gitignored)
```

## Tech Stack

- **Twelve Labs Marengo 3.0** — multimodal embeddings for semantic video search
- **Twelve Labs Pegasus 1.2** — video analysis and text generation
- **FiftyOne** — visual data platform + plugin system
- **Python 3.11** — no additional ML dependencies needed

## Team

Built for the Twelve Labs x Voxel51 Hackathon, April 2026.
