"""
gemini_service.py — AI Engine for MarketCraft AI

Wraps the Gemini API (google-genai SDK, model: gemini-2.5-flash) to power:
  - Campaign Understanding Agent   (parses an imported campaign report)
  - Social Media Content Generation Agent
  - Marketing Content Generation Agent
  - SEO Optimization Agent
  - Creative Design Generation Agent  (poster/banner/video copy + image prompts)
  - Content Validation & Preview Module
  - AI-generated marketing images (Gemini image generation, optional)

All agents share one JSON-generation call for speed/consistency, with a
fully offline fallback so the app keeps working end-to-end without a
valid API key.
"""
import os
import io
import json
import re
import random

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from google import genai
from google.genai import types

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

_client = None


def get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
            raise RuntimeError("GEMINI_API_KEY is not set. Add your key to the .env file.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _extract_json(text: str) -> dict:
    """Pull the first well-formed JSON object out of a model response."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model response.")
    return json.loads(text[start:end + 1])


# ---------------------------------------------------------------------------
# 1) Campaign Understanding Agent
# ---------------------------------------------------------------------------

UNDERSTANDING_INSTRUCTION = """You are MarketCraft AI's Campaign Understanding Agent.
You receive the raw text of a campaign report (produced by an upstream Campaign
Planning Agent) and must extract structured campaign information from it.

Respond with STRICT JSON ONLY, matching this schema exactly:
{
  "campaign_name": "string",
  "product_name": "string",
  "product_description": "string",
  "category": "string",
  "campaign_objective": "string (e.g. Awareness, Engagement, Conversions, Launch)",
  "target_audience": "string, one-line summary",
  "audience_demographics": "string (age range, gender, income, occupation, location)",
  "brand_tone": "string (e.g. Playful, Premium, Bold, Friendly, Professional)",
  "keywords": ["string", "string", "string"],
  "recommended_platforms": ["Instagram", "Facebook", "LinkedIn", "Twitter/X", "Google Ads"],
  "budget": "string",
  "key_message": "string",
  "unique_selling_points": ["string", "string"]
}
Infer sensible values for any field not explicitly present in the text, based on context.
Do not include any commentary outside the JSON object.
"""


def understand_campaign(raw_text: str) -> dict:
    """Campaign Understanding Agent: turns raw report text into structured data."""
    try:
        client = get_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[f"CAMPAIGN REPORT TEXT:\n\n{raw_text[:12000]}"],
            config=types.GenerateContentConfig(
                system_instruction=UNDERSTANDING_INSTRUCTION,
                temperature=0.4,
                response_mime_type="application/json",
            ),
        )
        return _extract_json(response.text)
    except Exception:
        return _offline_understanding(raw_text)


def _offline_understanding(raw_text: str) -> dict:
    """Heuristic fallback used when no valid Gemini API key is configured."""
    first_line = next((l.strip() for l in raw_text.splitlines() if l.strip()), "New Campaign")
    words = re.findall(r"[A-Za-z]{4,}", raw_text)
    keywords = list(dict.fromkeys(w.lower() for w in words))[:6] or ["marketing", "growth", "brand"]
    return {
        "campaign_name": first_line[:60],
        "product_name": first_line[:40],
        "product_description": raw_text[:220].strip(),
        "category": "General",
        "campaign_objective": "Engagement",
        "target_audience": "Digitally active consumers interested in the product category",
        "audience_demographics": "Age 22-40, mixed gender, urban/metro, middle-to-upper income",
        "brand_tone": "Friendly & Confident",
        "keywords": keywords,
        "recommended_platforms": ["Instagram", "Facebook", "LinkedIn", "Google Ads"],
        "budget": "Not specified",
        "key_message": first_line[:120],
        "unique_selling_points": ["Fast", "Reliable", "Great value"],
        "_offline_mode": True,
    }


# ---------------------------------------------------------------------------
# 2) Content Generation Agents (Social / Marketing / SEO / Creative) + Validation
# ---------------------------------------------------------------------------

# Maps the platform names shown as checkboxes on the Review page to the JSON
# keys used throughout the app, plus the schema fragment + offline generator
# for each — this is what lets us generate content for ONLY the platform(s)
# the user actually selected (one selected -> one block back; several
# selected -> that many blocks back).
PLATFORM_KEY_MAP = {
    "Instagram": "instagram",
    "Facebook": "facebook",
    "LinkedIn": "linkedin",
    "Twitter/X": "twitter_x",
    "Google Ads": "google_ads",
    "YouTube": "youtube",
}

PLATFORM_KEY_MAP_INV = {v: k for k, v in PLATFORM_KEY_MAP.items()}

PLATFORM_SCHEMA_SNIPPETS = {
    "instagram": '"instagram": {"caption": "string with emojis", "hashtags": ["string", "..."]}',
    "facebook": '"facebook": {"post": "string"}',
    "linkedin": '"linkedin": {"post": "string, professional tone"}',
    "twitter_x": '"twitter_x": {"post": "string, under 280 chars"}',
    "google_ads": '"google_ads": {"headlines": ["string (<=30 chars)", "string", "string"], "descriptions": ["string (<=90 chars)", "string"]}',
    "youtube": '"youtube": {"title": "string", "description": "string", "tags": ["string", "..."]}',
}


def _offline_platform_block(key, product, audience, usp, kws):
    if key == "instagram":
        return {
            "caption": f"✨ Meet {product} — built for {audience}. {usp}, every time. #LevelUp",
            "hashtags": [f"#{k.replace(' ', '')}" for k in kws[:5]] or ["#NewLaunch"],
        }
    if key == "facebook":
        return {"post": f"Introducing {product}! Designed with {audience} in mind, delivering {usp}. Discover more today."}
    if key == "linkedin":
        return {"post": f"We're excited to announce {product} — a solution built to bring {usp} to {audience}. Learn how it can help your business."}
    if key == "twitter_x":
        return {"post": f"{product} is here. {usp}. Built for {audience}. 🚀"}
    if key == "google_ads":
        return {
            "headlines": [f"{product} — {usp}", f"Try {product} Today", "Built For You"],
            "descriptions": [f"Discover {product}, made for {audience}.", f"Experience {usp} with {product}."],
        }
    if key == "youtube":
        return {
            "title": f"Introducing {product} — {usp}",
            "description": f"Learn all about {product} and how it brings {usp} to {audience}. Subscribe for more updates!",
            "tags": [k.replace(" ", "") for k in kws[:5]],
        }
    return {}


def _selected_platform_keys(campaign_info: dict) -> list:
    """Returns the internal platform keys the user actually selected on the
    Review page, in the checkbox display order. Falls back to all platforms
    if none were selected (e.g. older campaigns saved before this feature)."""
    selected_names = campaign_info.get("recommended_platforms") or []
    keys = [PLATFORM_KEY_MAP[name] for name in PLATFORM_KEY_MAP if name in selected_names]
    return keys or list(PLATFORM_KEY_MAP.values())


def _build_generation_instruction(platform_keys: list) -> str:
    social_fields = ",\n    ".join(PLATFORM_SCHEMA_SNIPPETS[k] for k in platform_keys)
    platform_label_list = ", ".join(k for k in platform_keys)
    return f"""You are MarketCraft AI — an autonomous marketing content studio made up of
five specialist agents working together: the Social Media Content Generation Agent,
the Marketing Content Generation Agent, the SEO Optimization Agent, the Creative Design
Generation Agent, and the Content Validation & Preview Module.

Given structured campaign information, generate a COMPLETE marketing kit ready for
publishing across platforms. Match the brand tone and audience precisely. Be specific,
punchy, and platform-native (no generic filler).

The user has selected ONLY these platforms for this kit: {platform_label_list}.
Generate social_media content for EXACTLY these platforms and no others — do not add
extra platform keys, and do not omit any of the listed ones.

Respond with STRICT JSON ONLY, matching this schema exactly:
{{
  "social_media": {{
    {social_fields}
  }},
  "marketing_content": {{
    "headlines": ["string", "string", "string"],
    "taglines": ["string", "string"],
    "ctas": ["string", "string", "string"],
    "short_description": "string, 1-2 sentences",
    "long_description": "string, 4-6 sentences"
  }},
  "seo": {{
    "keywords": ["string", "..."],
    "hashtags": ["#string", "..."],
    "meta_title": "string (<=60 chars)",
    "meta_description": "string (<=155 chars)"
  }},
  "creative_design": {{
    "image_prompts": [
      {{"platform": "Instagram Post", "prompt": "detailed AI image generation prompt"}},
      {{"platform": "Facebook Post", "prompt": "detailed AI image generation prompt"}},
      {{"platform": "LinkedIn Post", "prompt": "detailed AI image generation prompt"}},
      {{"platform": "Twitter/X Post", "prompt": "detailed AI image generation prompt"}},
      {{"platform": "Google Ads Post", "prompt": "detailed AI image generation prompt"}},
      {{"platform": "YouTube Post", "prompt": "detailed AI image generation prompt"}}
    ],
    "video_ad_script": {{
      "scenes": [
        {{"scene": 1, "visual": "string", "voiceover": "string", "duration_sec": 5}}
      ]
    }}
  }},
  "validation": {{
    "consistency_score": 90,
    "brand_alignment_score": 88,
    "platform_compatibility_score": 92,
    "overall_score": 90,
    "notes": ["string", "string"],
    "issues": ["string"]
  }}
}}
video_ad_script.scenes must contain 4 to 6 scenes summing to roughly 15-30 seconds.
All scores are integers 0-100. Do not include commentary outside the JSON object.
"""


def generate_marketing_kit(campaign_info: dict) -> dict:
    """Runs all content-generation agents in a single grounded call, generating
    social_media content for ONLY the platform(s) selected on the Review page."""
    platform_keys = _selected_platform_keys(campaign_info)
    brief = json.dumps(campaign_info, indent=2)
    try:
        client = get_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[f"CAMPAIGN INFORMATION:\n\n{brief}"],
            config=types.GenerateContentConfig(
                system_instruction=_build_generation_instruction(platform_keys),
                temperature=0.75,
                response_mime_type="application/json",
            ),
        )
        result = _extract_json(response.text)
        # Defensive: keep only the selected platforms even if the model added extras.
        sm = result.get("social_media", {})
        result["social_media"] = {k: sm[k] for k in platform_keys if k in sm}
        return result
    except Exception:
        return _offline_kit(campaign_info)


def _offline_kit(campaign_info: dict) -> dict:
    """Deterministic offline fallback so the full pipeline still works
    without a valid Gemini API key. Only builds social_media content for the
    platform(s) selected on the Review page."""
    product = campaign_info.get("product_name") or "our product"
    tone = campaign_info.get("brand_tone") or "Friendly"
    audience = campaign_info.get("target_audience") or "your audience"
    usp = (campaign_info.get("unique_selling_points") or ["quality", "value"])[0]
    kws = campaign_info.get("keywords") or ["marketing", "growth", "brand"]
    platform_keys = _selected_platform_keys(campaign_info)

    return {
        "social_media": {
            key: _offline_platform_block(key, product, audience, usp, kws)
            for key in platform_keys
        },
        "marketing_content": {
            "headlines": [f"{product}: {usp}, Reimagined", f"Say Hello To {product}", f"{usp} Starts Here"],
            "taglines": [f"{product}. {usp}. Simple.", "Made for you."],
            "ctas": ["Shop Now", "Learn More", "Get Started"],
            "short_description": f"{product} delivers {usp} for {audience}.",
            "long_description": f"{product} was designed from the ground up for {audience}. "
                                 f"With a focus on {usp}, it fits seamlessly into daily life while "
                                 f"staying true to a {tone.lower()} brand tone. Whether you're "
                                 f"discovering it for the first time or coming back for more, "
                                 f"{product} is built to deliver.",
        },
        "seo": {
            "keywords": kws,
            "hashtags": [f"#{k.replace(' ', '')}" for k in kws[:6]],
            "meta_title": f"{product} — {usp}"[:60],
            "meta_description": f"Discover {product}, built for {audience} with a focus on {usp}."[:155],
        },
        "creative_design": {
            "image_prompts": [
                {"platform": f"{name} Post", "prompt": f"Studio product photo of {product}, {tone.lower()} aesthetic, targeting {name}"} 
                for name in PLATFORM_KEY_MAP.keys()
            ],
            "video_ad_script": {
                "scenes": [
                    {"scene": 1, "visual": f"Close-up of {product}", "voiceover": f"Meet {product}.", "duration_sec": 4},
                    {"scene": 2, "visual": f"{audience} using the product", "voiceover": f"Built for {audience}.", "duration_sec": 6},
                    {"scene": 3, "visual": "Feature highlight montage", "voiceover": f"Delivering {usp}, every time.", "duration_sec": 6},
                    {"scene": 4, "visual": "Logo + CTA on screen", "voiceover": "Get started today.", "duration_sec": 4},
                ]
            },
        },
        "validation": {
            "consistency_score": 82,
            "brand_alignment_score": 80,
            "platform_compatibility_score": 85,
            "overall_score": 82,
            "notes": ["Generated in offline fallback mode — add a valid GEMINI_API_KEY for fully tailored, higher-fidelity content."],
            "issues": [],
        },
        "_offline_mode": True,
    }


# ---------------------------------------------------------------------------
# 3) Creative Design Generation Agent — AI marketing images
# ---------------------------------------------------------------------------

def generate_creative_image(prompt: str, out_path: str) -> bool:
    """Generates a marketing image, trying multiple engines in order so the
    UI reliably gets a real AI image instead of a placeholder:
      1) Gemini image generation (if GEMINI_API_KEY is valid)
      2) Pollinations.ai (free, keyless hosted diffusion models — Flux/SD)
    Returns True on success (file written to out_path), False if every
    engine failed and it fell back to an offline placeholder image."""
    if _generate_with_gemini(prompt, out_path):
        return True
    if _generate_with_pollinations(prompt, out_path):
        return True
    _offline_placeholder_image(prompt, out_path)
    return False


def _generate_with_gemini(prompt: str, out_path: str) -> bool:
    try:
        client = get_client()
        response = client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=[prompt],
        )
        for part in response.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                with open(out_path, "wb") as f:
                    f.write(part.inline_data.data)
                return True
        return False
    except Exception:
        return False


def _generate_with_pollinations(prompt: str, out_path: str) -> bool:
    """Fallback engine: Pollinations.ai exposes free, keyless hosted
    diffusion models (Flux by default) over a simple HTTP GET. Used
    automatically whenever Gemini image generation isn't available so the
    "Generate" button always produces a real AI image."""
    try:
        import urllib.parse
        import requests

        encoded_prompt = urllib.parse.quote(prompt[:800])
        seed = random.randint(0, 999_999)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width=800&height=800&nologo=true&model=flux&seed={seed}"
        )
        resp = requests.get(url, timeout=45)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type or len(resp.content) < 1000:
            return False
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return True
    except Exception:
        return False



def _offline_placeholder_image(prompt: str, out_path: str):
    """Draws a simple on-brand placeholder so the UI always has something
    to show when live image generation isn't available."""
    from PIL import Image, ImageDraw, ImageFont

    palettes = [
        ((124, 109, 242), (242, 141, 168)),
        ((90, 176, 214), (167, 232, 199)),
        ((245, 166, 90), (240, 108, 108)),
        ((108, 201, 168), (108, 148, 240)),
    ]
    c1, c2 = random.choice(palettes)
    w, h = 800, 800
    img = Image.new("RGB", (w, h), c1)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    label = (prompt[:70] + "...") if len(prompt) > 70 else prompt
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    draw.rectangle([40, h - 140, w - 40, h - 40], fill=(255, 255, 255, 180))
    draw.text((60, h - 120), "MarketCraft AI — Preview Creative", fill=(40, 40, 40), font=font)
    draw.text((60, h - 90), label, fill=(80, 80, 80), font=font)
    draw.text((60, h - 65), "(offline placeholder — connect GEMINI_API_KEY for real AI images)", fill=(120, 120, 120), font=font)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG")
