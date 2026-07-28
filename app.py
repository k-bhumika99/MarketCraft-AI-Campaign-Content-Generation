"""
app.py — MarketCraft AI: Campaign Content Generation Agent
Flask application entrypoint.
"""
import os
import re
import uuid
from functools import wraps
from datetime import timedelta

from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    session, Response,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import db
import report_parser
import gemini_service
import kit_export

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=14)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB upload cap
# Session cookie hardening: SameSite=Lax keeps the login cookie attached on
# normal top-level navigations (so Sign In/Sign Up redirects always carry the
# session), while COOKIE_SECURE is only forced on when the app is actually
# served over HTTPS — forcing it on unconditionally would silently break
# sign-in on plain-HTTP localhost/dev servers.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FORCE_HTTPS_COOKIES", "").lower() == "true"

db.init_db()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GENERATED_DIR = os.path.join(app.root_path, "static", "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.", "error")
            return redirect(url_for("signin", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_user():
    user = None
    if session.get("user_id"):
        user = db.get_user_by_id(session["user_id"])
    return {"current_user": user}


# ---------------------------------------------------------------------------
# Marketing pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    recent = db.list_campaigns(limit=6)
    return render_template("index.html", recent=recent)


@app.route("/dashboard")
@login_required
def dashboard():
    stats = db.get_dashboard_stats(session.get("user_id"))
    return render_template("dashboard.html", stats=stats)


@app.route("/history")
@login_required
def history():
    campaigns = db.list_campaigns(user_id=session.get("user_id"), limit=200)
    return render_template("history.html", campaigns=campaigns)


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


# ---------------------------------------------------------------------------
# 1) Campaign Report Import Module
# ---------------------------------------------------------------------------

@app.route("/upload", methods=["GET"])
@login_required
def upload_form():
    return render_template("upload.html")


@app.route("/upload", methods=["POST"])
@login_required
def upload_report():
    mode = request.form.get("mode", "file")

    if mode == "file":
        f = request.files.get("report_file")
        if not f or not f.filename:
            flash("Please choose a campaign report (PDF, DOCX, or TXT) to upload.", "error")
            return redirect(url_for("upload_form"))
        if not report_parser.allowed_file(f.filename):
            flash("Unsupported file type. Please upload a PDF, DOCX, or TXT report.", "error")
            return redirect(url_for("upload_form"))
        try:
            file_bytes = f.read()
            raw_text = report_parser.extract_text(file_bytes, f.filename)
        except report_parser.ReportParseError as exc:
            flash(str(exc), "error")
            return redirect(url_for("upload_form"))
        source_filename = secure_filename(f.filename)
        source_type = os.path.splitext(source_filename)[1].lstrip(".").upper()
    else:
        raw_text = request.form.get("manual_text", "").strip()
        if len(raw_text) < 40:
            flash("Please provide a bit more detail about the campaign (at least a few sentences).", "error")
            return redirect(url_for("upload_form"))
        source_filename = "manual-entry.txt"
        source_type = "MANUAL"

    campaign_id = db.create_campaign(session.get("user_id"), source_filename, source_type, raw_text)

    # Campaign Understanding Agent
    campaign_info = gemini_service.understand_campaign(raw_text)
    db.save_campaign_understanding(campaign_id, campaign_info)

    return redirect(url_for("review_campaign", campaign_id=campaign_id))


# ---------------------------------------------------------------------------
# 2) Campaign Understanding Agent — review / confirm before generation
# ---------------------------------------------------------------------------

@app.route("/campaign/<int:campaign_id>/review", methods=["GET"])
@login_required
def review_campaign(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash("Campaign not found.", "error")
        return redirect(url_for("upload_form"))
    warnings = report_parser.validate_data(campaign["campaign_info"])
    return render_template("review.html", campaign=campaign, warnings=warnings)


@app.route("/campaign/<int:campaign_id>/generate", methods=["POST"])
@login_required
def generate_kit(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash("Campaign not found.", "error")
        return redirect(url_for("upload_form"))

    # Allow last-minute edits from the review form before generation.
    info = dict(campaign["campaign_info"])
    for field in ["campaign_name", "product_name", "product_description", "category",
                  "campaign_objective", "target_audience", "audience_demographics",
                  "brand_tone", "budget", "key_message"]:
        val = request.form.get(field)
        if val is not None:
            info[field] = val.strip()
    keywords_raw = request.form.get("keywords")
    if keywords_raw is not None:
        info["keywords"] = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    platforms = request.form.getlist("platforms")
    if platforms:
        info["recommended_platforms"] = platforms

    db.save_campaign_understanding(campaign_id, info)

    # Run the content generation agents (Social / Marketing / SEO / Creative / Validation)
    content = gemini_service.generate_marketing_kit(info)
    validation = content.get("validation", {}) or {}
    platform_count = len(info.get("recommended_platforms", []))
    db.save_generated_kit(campaign_id, content, brand_score=validation.get("overall_score"),
                           platform_count=platform_count)

    return redirect(url_for("campaign_detail", campaign_id=campaign_id))


# ---------------------------------------------------------------------------
# 3) Marketing kit — preview / validation / creative images
# ---------------------------------------------------------------------------

@app.route("/campaign/<int:campaign_id>")
@login_required
def campaign_detail(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash("Campaign not found.", "error")
        return redirect(url_for("upload_form"))
    if campaign["status"] != "ready":
        return redirect(url_for("review_campaign", campaign_id=campaign_id))
    return render_template("campaign_detail.html", campaign=campaign)


@app.route("/campaign/<int:campaign_id>/platform/<platform_key>")
@login_required
def platform_content(campaign_id, platform_key):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash("Campaign not found.", "error")
        return redirect(url_for("history"))
    if campaign["status"] != "ready":
        return redirect(url_for("review_campaign", campaign_id=campaign_id))
        
    c = campaign.get("content", {})
    sm = c.get("social_media", {})
    if platform_key not in sm:
        flash(f"No content found for platform: {platform_key}", "error")
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))
        
    content_data = sm[platform_key]
    
    # Mapping details for rendering
    platform_details = {
        "instagram": {"title": "Instagram", "emoji": "📸", "url": "https://instagram.com"},
        "facebook": {"title": "Facebook", "emoji": "👍", "url": "https://facebook.com"},
        "linkedin": {"title": "LinkedIn", "emoji": "💼", "url": "https://linkedin.com"},
        "twitter_x": {"title": "Twitter / X", "emoji": "✖️", "url": "https://x.com"},
        "google_ads": {"title": "Google Ads", "emoji": "🔎", "url": "https://ads.google.com"},
        "youtube": {"title": "YouTube", "emoji": "▶️", "url": "https://youtube.com"}
    }
    
    details = platform_details.get(platform_key, {"title": platform_key.title(), "emoji": "📱", "url": "#"})
    
    return render_template(
        "platform_content.html", 
        campaign=campaign, 
        platform_key=platform_key,
        content_data=content_data,
        platform_title=details["title"],
        platform_emoji=details["emoji"],
        platform_url=details["url"]
    )


@app.route("/campaign/<int:campaign_id>/image", methods=["POST"])
@login_required
def generate_image(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    prompt = request.json.get("prompt") if request.is_json else request.form.get("prompt")
    if not prompt:
        return jsonify({"error": "Prompt required"}), 400

    filename = f"campaign_{campaign_id}_{uuid.uuid4().hex[:8]}.png"
    out_path = os.path.join(GENERATED_DIR, filename)
    live = gemini_service.generate_creative_image(prompt, out_path)

    return jsonify({
        "url": url_for("static", filename=f"generated/{filename}"),
        "live": live,
    })


@app.route("/campaign/<int:campaign_id>/delete", methods=["POST"])
@login_required
def delete_campaign(campaign_id):
    db.delete_campaign(campaign_id)
    flash("Campaign deleted.", "success")
    return redirect(url_for("history"))


# ---------------------------------------------------------------------------
# 4) Export & Asset Management Module
# ---------------------------------------------------------------------------

@app.route("/campaign/<int:campaign_id>/export/<fmt>")
@login_required
def export_kit(campaign_id, fmt):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash("Campaign not found.", "error")
        return redirect(url_for("history"))

    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", campaign.get("product_name") or "campaign").strip("_") or "campaign"

    if fmt == "txt":
        data = kit_export.campaign_txt(campaign)
        return Response(data, mimetype="text/plain", headers={
            "Content-Disposition": f"attachment; filename={safe_name}_marketing_kit.txt"
        })
    if fmt == "pdf":
        data = kit_export.campaign_pdf(campaign)
        return Response(data, mimetype="application/pdf", headers={
            "Content-Disposition": f"attachment; filename={safe_name}_marketing_kit.pdf"
        })
    if fmt == "docx":
        data = kit_export.campaign_docx(campaign)
        return Response(data, mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={
            "Content-Disposition": f"attachment; filename={safe_name}_marketing_kit.docx"
        })

    flash("Unsupported export format.", "error")
    return redirect(url_for("campaign_detail", campaign_id=campaign_id))


@app.route("/api/campaign/<int:campaign_id>")
@login_required
def api_campaign(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        return jsonify({"error": "not found"}), 404
    return jsonify(campaign["content"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("index"))
        
    next_url = request.args.get("next") or request.form.get("next") or ""
        
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = []
        if not full_name:
            errors.append("Please tell us your name.")
        if not email or not EMAIL_RE.match(email):
            errors.append("Enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")
        if email and db.get_user_by_email(email):
            errors.append("An account with this email already exists — sign in instead.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("signup.html", next_url=next_url)

        try:
            password_hash = generate_password_hash(password)
            user_id = db.create_user(full_name, email, password_hash)
            session.permanent = True
            session["user_id"] = user_id
            flash(f"Welcome to MarketCraft AI, {full_name.split(' ')[0]}! 🎉", "success")
            return redirect(next_url or url_for("index"))
        except Exception:
            flash("Something went wrong creating your account. Please try again.", "error")

    return render_template("signup.html", next_url=next_url)


@app.route("/signin", methods=["GET", "POST"])
def signin():
    if session.get("user_id"):
        return redirect(url_for("index"))
        
    next_url = request.args.get("next") or request.form.get("next") or ""
        
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            user = db.get_user_by_email(email)
            if not user or not check_password_hash(user["password_hash"], password):
                flash("Incorrect email or password.", "error")
            else:
                session.permanent = True
                session["user_id"] = user["id"]
                flash(f"Welcome back, {user['full_name'].split(' ')[0]}! 👋", "success")
                return redirect(next_url or url_for("index"))
        except Exception:
            flash("Something went wrong signing you in. Please try again.", "error")

    return render_template("signin.html", next_url=next_url)


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been signed out.", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port, debug=True)
