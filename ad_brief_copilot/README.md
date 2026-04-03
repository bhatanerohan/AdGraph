# Ad-to-Brief Copilot -- FiftyOne Plugin

The Ad-to-Brief Copilot is a FiftyOne plugin that leverages the Twelve Labs API to help creative teams analyze reference ads at scale. It searches for relevant ads by visual content, extracts creative traits (hook type, pacing, tone, CTA style, visual style), synthesizes patterns across your top-performing references, and generates a full creative brief grounded in data-driven insights.

## Requirements

- FiftyOne >= 0.21
- A Twelve Labs API key (set as `TWELVE_LABS_API_KEY` environment variable or FiftyOne secret)
- Ad videos pre-indexed in a Twelve Labs index

## Installation

```bash
fiftyone plugins create --from-dir ./ad_brief_copilot
```

## Dataset Setup

Before using the plugin, you need a FiftyOne dataset where each sample has a `twelvelabs_video_id` field linking it to an indexed video. Use the following helper script to create one from your Twelve Labs index:

```python
# setup_dataset.py
import os, fiftyone as fo
from dotenv import load_dotenv
from twelvelabs import TwelveLabs

load_dotenv()
client = TwelveLabs(api_key=os.getenv("TWELVE_LABS_API_KEY"))
INDEX_ID = "YOUR_INDEX_ID"  # replace with your index

dataset = fo.Dataset("ad-campaign-refs", overwrite=True)
for asset in client.indexes.indexed_assets.list(INDEX_ID):
    sample = fo.Sample(filepath=asset.system_metadata.filename or f"{asset.id}.mp4")
    sample["twelvelabs_video_id"] = asset.id
    dataset.add_sample(sample)
dataset.save()
print(f"Created dataset with {len(dataset)} samples")
```

## Usage

1. Launch the FiftyOne App:

```python
import fiftyone as fo

dataset = fo.load_dataset("ad-campaign-refs")
session = fo.launch_app(dataset)
```

2. Open the Operators panel in the FiftyOne App and run the four operators in sequence:

**Step 1 -- Search Ad References**
Type `search_ad_references` in the operator search bar. Enter your search query (e.g., "luxury car cinematic slow motion"), your Twelve Labs Index ID, and the number of results you want. This filters the dataset to matching videos and assigns relevance scores.

**Step 2 -- Extract Ad Traits**
Type `extract_ad_traits` in the operator search bar. This analyzes each video in the current view using Twelve Labs and populates trait fields (hook_type, pacing, tone, cta_style, visual_style) on every sample.

**Step 3 -- Synthesize Patterns**
Type `synthesize_patterns` in the operator search bar. This aggregates trait data across all videos in the view and produces a pattern analysis summary with dominant traits and key insights.

**Step 4 -- Generate Creative Brief**
Type `generate_brief` in the operator search bar. Provide a reference video ID (pick the top-scoring one from your search results) and optionally add brand/product context. The plugin generates a full creative brief based on the pattern analysis and the reference video.

## Demo Query Suggestions

Try these searches to get started:

- "luxury car cinematic slow motion"
- "UGC creator product reveal"
- "fast-paced energy drink ad"
