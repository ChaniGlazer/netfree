import requests
import base64
import os
import ssl
import urllib3
import re
import time
import threading

from openai import OpenAI
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

# =========================================================
# SSL
# =========================================================

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if (
    not os.environ.get('PYTHONHTTPSVERIFY', '')
    and getattr(ssl, '_create_unverified_context', None)
):
    ssl._create_default_https_context = ssl._create_unverified_context

# =========================================================
# ENV
# =========================================================

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=20
)

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# =========================================================
# PUBLIC DIR
# =========================================================

PUBLIC_DIR = os.path.join(os.getcwd(), 'public')

if not os.path.exists(PUBLIC_DIR):
    os.makedirs(PUBLIC_DIR)

# =========================================================
# CLEANUP - מחיקת תמונות ישנות מעל שעה
# =========================================================

def cleanup_old_images():
    while True:
        try:
            now = time.time()
            for filename in os.listdir(PUBLIC_DIR):
                filepath = os.path.join(PUBLIC_DIR, filename)
                if os.path.isfile(filepath):
                    age = now - os.path.getmtime(filepath)
                    if age > 3600:  # מעל שעה
                        os.remove(filepath)
                        print(f"🗑️ נמחק: {filename}")
        except Exception as e:
            print(f"❌ Cleanup error: {e}")
        time.sleep(600)  # בודק כל 10 דקות

cleanup_thread = threading.Thread(target=cleanup_old_images, daemon=True)
cleanup_thread.start()

# =========================================================
# YOUTUBE VIDEO ID
# =========================================================

def get_video_id(url):
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11})',
        r'youtu\.be\/([0-9A-Za-z_-]{11})'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None

# =========================================================
# DOWNLOAD IMAGE
# =========================================================

def download_and_save_frame(video_id, index):
    """
    מוריד תמונה לפי אינדקס
    """

    thumbnail_sets = [
        [
            f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
            f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
            f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
        ],
        [
            f"https://img.youtube.com/vi/{video_id}/hq1.jpg",
            f"https://img.youtube.com/vi/{video_id}/hq2.jpg",
            f"https://img.youtube.com/vi/{video_id}/hq3.jpg"
        ]
    ]

    all_urls = thumbnail_sets[0] + thumbnail_sets[1]

    if index >= len(all_urls):
        return None

    url = all_urls[index]

    headers = {
        'User-Agent': 'Mozilla/5.0'
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            verify=False,
            timeout=10
        )

        if response.status_code != 200:
            return None

        # הגנה מתמונות ריקות/קטנות מדי
        if len(response.content) < 5000:
            return None

        filename = f"{video_id}_frame_{index + 1}.jpg"
        filepath = os.path.join(PUBLIC_DIR, filename)

        with open(filepath, 'wb') as f:
            f.write(response.content)

        return filepath

    except Exception as e:
        print(f"❌ Error downloading frame {index}: {e}")
        return None

# =========================================================
# AI ANALYZE IMAGE
# =========================================================

def analyze_single_image(image_path):
    """
    מנתח תמונה אחת עם GPT-4o
    """

    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(
            image_file.read()
        ).decode('utf-8')

    for attempt in range(3):

        try:

            ai_resp = client.chat.completions.create(
                model="gpt-4o",

                messages=[
                    {
                        "role": "system",
                        "content": """
You are a highly conservative image moderation system.

Your job is ONLY to decide:
ALLOW
or
BLOCK: <reason>

CRITICAL RULES:
- Default is ALWAYS ALLOW.
- NEVER guess, infer, estimate, hallucinate, or assume details.
- ONLY block when forbidden content is clearly and confidently visible.
- If uncertain even slightly → ALLOW.
- Ignore blurry, tiny, dark, cropped, partial, distant, unclear, or ambiguous content.
- Ignore reflections, silhouettes, shadows, emojis, dolls, toys, mannequins, tiny thumbnails, abstract art, and unclear figures.
- Only evaluate what is actually visible in the image.

BLOCK ONLY IF:
1. A real female older than about 5 is clearly visible.
2. A clear drawing/cartoon/illustration of a female older than about 5 is clearly visible.
3. A logo of ערוצי טלוויזיה חילוניים כגון is clearly visible:
   - ערוצי טלוויזיה חילוניים: Kan 11, Keshet 12, Reshet 13, Channel 14, N12, Walla, Ynet
   - International: CNN, BBC, Fox News, Sky News, Al Jazeera, Reuters, AP, NBC, MSNBC, ABC News, CBS News
   - WARNING: Do NOT confuse general Hebrew text, numbers, or circular shapes with news logos.
   - A logo must be an actual branded station logo, not just similar-looking text or shapes.
4. A clearly visible exposed stomach on a non-baby person.

IMPORTANT:
- Babies and toddlers → ALLOW.
- Men and boys → ALLOW.
- Unclear gender → ALLOW.
- Covered stomach → ALLOW.
- Unclear logo → ALLOW.
- Technical problems → ALLOW.

Return ONLY in one of these exact formats:
ALLOW
or
BLOCK: <reason in English, max 5 words>

Examples:
BLOCK: female clearly visible
BLOCK: CNN logo visible
BLOCK: exposed stomach visible
BLOCK: female cartoon visible
"""
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Analyze this image according to the moderation rules."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],

                temperature=0,
                max_tokens=20
            )

            decision = (
                ai_resp.choices[0]
                .message
                .content
                .strip()
            )

            if not decision.upper().startswith("ALLOW") and not decision.upper().startswith("BLOCK"):
                return "ALLOW"

            return decision

        except Exception as e:
            print(f"❌ GPT Error attempt {attempt + 1}: {e}")

            if attempt < 2:
                time.sleep(1)

    return "ALLOW"

# =========================================================
# MAIN VIDEO ANALYSIS
# =========================================================

def analyze_video_logic(url):

    video_id = get_video_id(url)

    if not video_id:
        return "ALLOW"

    total_checked = 0

    # בודק עד 7 thumbnails
    for i in range(7):

        frame_path = download_and_save_frame(video_id, i)

        if not frame_path:
            continue

        total_checked += 1

        decision = analyze_single_image(frame_path)

            print(f"🖼️ Frame {i + 1}: {decision}")

            if decision.upper().startswith("BLOCK"):
                filename = os.path.basename(frame_path)
                image_url = f"/public/{filename}"
                return {"decision": decision, "frame": i + 1, "image_url": image_url}

            # מחיקת הקובץ רק אם לא נחסם
            try:
                os.remove(frame_path)
            except:
                pass

    # אם לא הצלחנו לבדוק כלום → ALLOW
    if total_checked == 0:
        return {"decision": "ALLOW", "frame": None, "image_url": None}

    return {"decision": "ALLOW", "frame": None, "image_url": None}

# =========================================================
# ROUTES
# =========================================================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/public/<filename>')
def serve_image(filename):
    return app.send_static_file(f'../public/{filename}')

@app.route('/analyze', methods=['POST'])
def analyze():

    try:

        data = request.json

        if not data:
            return jsonify({
                "decision": "ALLOW"
            })

        url = data.get('url')

        if not url:
            return jsonify({
                "decision": "ALLOW"
            })

        result = analyze_video_logic(url)

        return jsonify({
            "decision": result["decision"],
            "frame": result["frame"],
            "image_url": result["image_url"]
        })

    except Exception as e:

        print(f"❌ Server Error: {e}")

        return jsonify({
            "decision": "ALLOW"
        })

# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host='0.0.0.0',
        port=port
    )