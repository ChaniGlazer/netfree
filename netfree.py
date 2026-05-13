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
# הגדרות SSL
# =========================================================

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if (
    not os.environ.get('PYTHONHTTPSVERIFY', '')
    and getattr(ssl, '_create_unverified_context', None)
):
    ssl._create_default_https_context = ssl._create_unverified_context

# =========================================================
# טעינת משתני סביבה
# =========================================================

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=20
)

# =========================================================
# הגדרות Flask
# =========================================================

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# =========================================================
# יצירת תיקיית public אם לא קיימת
# =========================================================

PUBLIC_DIR = os.path.join(os.getcwd(), 'public')

if not os.path.exists(PUBLIC_DIR):
    os.makedirs(PUBLIC_DIR)

# =========================================================
# חילוץ מזהה סרטון יוטיוב
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
# הורדת thumbnail מיוטיוב
# =========================================================

def download_and_save_frame(video_id, index):

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

        print(f"📥 מוריד תמונה {index + 1}")

        response = requests.get(
            url,
            headers=headers,
            verify=False,
            timeout=10
        )

        if response.status_code != 200:

            print(f"⚠️ הורדת תמונה נכשלה: {response.status_code}")
            return None

        # הגנה מתמונות קטנות/ריקות
        if len(response.content) < 1000:

            print("⚠️ התמונה קטנה מדי")
            return None

        filename = f"{video_id}_frame_{index + 1}.jpg"

        filepath = os.path.join(PUBLIC_DIR, filename)

        with open(filepath, 'wb') as f:
            f.write(response.content)

        print(f"✅ תמונה נשמרה: {filename}")

        return filepath

    except Exception as e:

        print(f"❌ שגיאה בהורדת תמונה: {e}")

        return None

# =========================================================
# ניתוח תמונה באמצעות GPT
# =========================================================

def analyze_single_image(image_path):

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

Your job is to decide:
ALLOW
or
BLOCK

If you BLOCK:
you MUST also provide a short reason.

Rules:
- Default is ALWAYS ALLOW.
- NEVER guess or infer.
- ONLY block when forbidden content is clearly visible.
- If uncertain even slightly → ALLOW.

BLOCK ONLY IF:
1. A real female older than about 5 is clearly visible.
2. A clear drawing/cartoon/illustration of a female older than about 5 is clearly visible.
3. A clearly recognizable secular TV/news logo is visible.
4. A clearly visible exposed stomach on a non-baby person.

Output format:
ALLOW

or

BLOCK | reason

Examples:
BLOCK | Real woman visible
BLOCK | TV news logo visible
BLOCK | Exposed stomach visible
ALLOW
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

            content = ai_resp.choices[0].message.content

            if not content:

                print("⚠️ GPT לא החזיר תוכן")

                return {
                    "decision": "ALLOW",
                    "reason": "אין תשובה מהמודל"
                }

            content = content.strip()

            print(f"🤖 תשובת GPT: {content}")

            if content.upper().startswith("BLOCK"):

                parts = content.split("|", 1)

                reason = (
                    parts[1].strip()
                    if len(parts) > 1
                    else "ללא סיבה"
                )

                return {
                    "decision": "BLOCK",
                    "reason": reason
                }

            return {
                "decision": "ALLOW",
                "reason": "עבר בהצלחה"
            }

        except Exception as e:

            print(f"❌ שגיאת GPT ניסיון {attempt + 1}: {e}")

            if attempt < 2:
                time.sleep(1)

    return {
        "decision": "ALLOW",
        "reason": "תקלה טכנית"
    }

# =========================================================
# לוגיקת בדיקת סרטון
# =========================================================

def analyze_video_logic(url):

    print("==================================================")
    print(f"🎬 התחלת בדיקת סרטון: {url}")

    video_id = get_video_id(url)

    if not video_id:

        print("⚠️ לא נמצא מזהה סרטון")

        return {
            "decision": "ALLOW",
            "reason": "לא נמצא מזהה סרטון"
        }

    print(f"🆔 מזהה סרטון: {video_id}")

    total_checked = 0

    # בדיקת עד 7 thumbnails
    for i in range(7):

        frame_path = download_and_save_frame(video_id, i)

        if not frame_path:
            continue

        total_checked += 1

        try:

            result = analyze_single_image(frame_path)

            decision = result["decision"]
            reason = result["reason"]

            print(f"🖼️ תמונה {i + 1}: {decision}")

            if decision == "BLOCK":

                print("🚫 הסרטון נחסם")
                print(f"📌 סיבת חסימה: {reason}")

                return {
                    "decision": "BLOCK",
                    "reason": reason
                }

        finally:

            # מחיקת קובץ זמני
            try:

                os.remove(frame_path)

                print(f"🗑️ נמחק קובץ זמני: {frame_path}")

            except:
                pass

    # אם לא נבדקה אף תמונה
    if total_checked == 0:

        print("⚠️ לא ניתן היה לבדוק תמונות")

        return {
            "decision": "ALLOW",
            "reason": "לא נמצאו תמונות לבדיקה"
        }

    print("✅ הסרטון אושר")

    return {
        "decision": "ALLOW",
        "reason": "כל התמונות עברו"
    }

# =========================================================
# דף הבית
# =========================================================

@app.route('/')
def home():

    return render_template('index.html')

# =========================================================
# API לבדיקה
# =========================================================

@app.route('/analyze', methods=['POST'])
def analyze():

    try:

        data = request.json

        if not data:

            return jsonify({
                "decision": "ALLOW",
                "reason": "לא התקבל מידע"
            })

        url = data.get('url')

        if not url:

            return jsonify({
                "decision": "ALLOW",
                "reason": "לא התקבל URL"
            })

        result = analyze_video_logic(url)

        return jsonify(result)

    except Exception as e:

        print(f"❌ שגיאת שרת: {e}")

        return jsonify({
            "decision": "ALLOW",
            "reason": "שגיאת שרת"
        })

# =========================================================
# הפעלת השרת
# =========================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    print("🚀 השרת הופעל")

    app.run(
        host='0.0.0.0',
        port=port
    )