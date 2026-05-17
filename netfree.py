import requests
import base64
import os
import ssl
import urllib3
import re
import time

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
BLOCK

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
3. BLOCK if any of the following logos are clearly visible:
- Israeli channels: kan 11, Keshet 12, Reshet 13, Channel 14, N12, Walla, Ynet
- International: CNN, BBC, Fox News, Sky News, Al Jazeera, 
  Reuters, AP, NBC, MSNBC, ABC News, CBS News
4. A clearly visible exposed stomach on a non-baby person.

IMPORTANT:
- Babies and toddlers → ALLOW.
- Men and boys → ALLOW.
- Unclear gender → ALLOW.
- Covered stomach → ALLOW.
- Unclear logo → ALLOW.
- Technical problems → ALLOW.

Return ONLY:
ALLOW
or
BLOCK
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
                max_tokens=5
            )

            decision = (
                ai_resp.choices[0]
                .message
                .content
                .strip()
                .upper()
            )

            if decision not in ["ALLOW", "BLOCK"]:
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

        try:

            decision = analyze_single_image(frame_path)

            print(f"🖼️ Frame {i + 1}: {decision}")

            if decision == "BLOCK":
                return "BLOCK"

        finally:

            # מחיקת הקובץ אחרי שימוש
            try:
                os.remove(frame_path)
            except:
                pass

    # אם לא הצלחנו לבדוק כלום → ALLOW
    if total_checked == 0:
        return "ALLOW"

    return "ALLOW"

# =========================================================
# ROUTES
# =========================================================

@app.route('/')
def home():
    return render_template('index.html')

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
            "decision": result
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