# MarketCraft AI — Campaign Content Generation Agent

An autonomous marketing assistant that turns an approved campaign report into a complete,
platform-ready marketing kit: social posts, ad copy, SEO assets, creative concepts, AI-generated
marketing images, and video ad scripts.

This is the content-generation counterpart to a Campaign Planning Agent (e.g. **GrowthGPT**) —
built with the same Flask + SQLite + Jinja2 + Gemini stack and pastel glassmorphism UI language.

## Pipeline / Modules

1. **Campaign Report Import Module** — upload a PDF/DOCX/TXT report (or enter details manually),
   extracts and validates the text (`report_parser.py`).
2. **Campaign Understanding Agent** — Gemini parses the report into structured campaign data:
   objectives, audience, brand tone, keywords, platforms (`gemini_service.understand_campaign`).
3. **Review & confirm** — edit anything before generation (`templates/review.html`).
4. **Content generation agents** (single grounded Gemini call, `gemini_service.generate_marketing_kit`):
   - Social Media Content Generation Agent (Instagram, Facebook, LinkedIn, Twitter/X, Google Ads)
   - Marketing Content Generation Agent (headlines, taglines, CTAs, descriptions)
   - SEO Optimization Agent (keywords, hashtags, meta tags)
   - Creative Design Generation Agent (poster/banner copy, image prompts, story creative, video script)
5. **Content Validation & Preview Module** — consistency / brand-alignment / platform-fit scores.
6. **AI-generated marketing images** — on-demand Gemini image generation per creative prompt
   (`gemini_service.generate_creative_image`), with an offline placeholder generator so the UI
   always renders something even without a live API key.
7. **Export & Asset Management Module** — export the full kit as PDF, DOCX, or TXT (`kit_export.py`).

## Setup

```bash
cd marketcraft
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

`.env` already contains a `GEMINI_API_KEY` and is set to use **`gemini-2.5-flash`** for text
generation and `gemini-2.5-flash-image` for creative images. Replace the key with your own if needed.

```bash
python app.py
```

Visit `http://localhost:5002`, create an account, then **New Campaign Kit** to import a report.

## Offline fallback

Every AI call (`understand_campaign`, `generate_marketing_kit`, `generate_creative_image`) has a
deterministic offline fallback, so the full pipeline — upload → understand → generate → export —
keeps working even if the Gemini API key is missing, invalid, or rate-limited. Kits generated this
way are flagged in the UI.

## Tech stack

- **Backend:** Flask, SQLite (non-destructive `ALTER TABLE` migrations in `db.py`)
- **AI Engine:** `google-genai` SDK, `gemini-2.5-flash` (text) / `gemini-2.5-flash-image` (images)
- **Document processing:** PyMuPDF (PDF), python-docx (DOCX)
- **Export:** ReportLab (PDF), python-docx (DOCX)
- **Frontend:** Jinja2, vanilla JS, glassmorphism/pastel CSS (violet–rose gradient theme)
- **Auth:** Werkzeug session-based auth, `login_required` decorator, user-scoped queries
