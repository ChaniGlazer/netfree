import requests
import base64
import os
import ssl
import urllib3
import re
from openai import OpenAI
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

# ביטול אזהרות SSL (כמו בקוד המקורי שלך)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
if (not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None)):
    ssl._create_default_https_context = ssl._create_unverified_context

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})



# יצירת תיקיית public אם אינה קיימת
PUBLIC_DIR = os.path.join(os.getcwd(), 'public')
if not os.path.exists(PUBLIC_DIR):
    os.makedirs(PUBLIC_DIR)

def get_video_id(url):
    pattern = r'(?:v=|\/|be\/)([0-9A-Za-z_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def download_and_save_frames(video_id):
    """מוריד 3 תמונות מנקודות זמן שונות ושומר בתיקיית public"""
    frames_paths = []
    # hq1, hq2, hq3 הן תמונות מנקודות זמן שונות ביוטיוב (התחלה, אמצע, סוף)
    urls = [
        f"https://img.youtube.com/vi/{video_id}/hq1.jpg",
        f"https://img.youtube.com/vi/{video_id}/hq2.jpg",
        f"https://img.youtube.com/vi/{video_id}/hq3.jpg"
    ]
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for i, url in enumerate(urls):
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=10)
            if response.status_code == 200:
                filename = f"{video_id}_frame_{i+1}.jpg"
                filepath = os.path.join(PUBLIC_DIR, filename)
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                frames_paths.append(filepath)
        except Exception as e:
            print(f"Error downloading frame {i}: {e}")
            
    return frames_paths

def analyze_single_image(image_path):
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')

    ai_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict binary content safety classifier for a Jewish religious community platform. "
                    "Your final output must start with exactly one word: 'BLOCK' or 'ALLOW', followed by a brief explanation in Hebrew. "
                    "CRITICAL TECHNICAL RULE: YouTube often returns a black or gray placeholder image when the video thumbnail is unavailable. "
                    "A black image, gray image, very dark image, or any image with no clear visible content is a TECHNICAL FAILURE — respond ALLOW immediately. "
                    "Do NOT block for technical reasons. Only BLOCK based on actual visible content. "
                    "IMPORTANT: Men and boys are always ALLOWED unless clearly shirtless. Never block a man who is wearing any clothing on his upper body."
                )
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "FIRST CHECK: Is this image black, gray, nearly empty, or a generic placeholder with no real content? "
                            "If yes — respond ALLOW immediately (technical failure). Do not apply any content rules.\n\n"
                            "Analyze this image and decide BLOCK or ALLOW.\n\n"
                            "━━━ BLOCK only if one of these is clearly true ━━━\n\n"
                            "1. WOMEN / GIRLS: Any real woman or girl is visible — regardless of how modest she is.\n"
                            "2. SHIRTLESS MAN: A man who is clearly shirtless — chest or upper body visibly exposed with no shirt. "
                            "A clothed man (t-shirt, suit, sportswear, hoodie, etc.) must be ALLOWED. "
                            "NEVER block a man just for being a man.\n"
                            "3. IMMODEST ANIMATION: Animated or illustrated female figure where body curves are clearly visible in a revealing or tight outfit.\n"
                            "4. FOOTBALL / BASKETBALL: Gameplay, training, tutorials, or logos related to football or basketball.\n"
                            "5. SECULAR TV CHANNEL: Logos of secular channels (Channel 12, 13, 11, N12, Kan, CNN, BBC, Fox, etc.) or a professional news studio setting.\n\n"
                            "━━━ ALLOW in every other case ━━━\n\n"
                            "If you are not certain — respond ALLOW.\n"
                            "If the image is broken, black, or a placeholder — respond ALLOW.\n\n"
                            "Explain your decision briefly in Hebrew."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                    }
                ],
            }
        ],
        max_tokens=150
    )
    return ai_resp.choices[0].message.content.strip()


def analyze_video_logic(url):
    video_id = get_video_id(url)
    if not video_id:
        return "שגיאה: לא הצלחתי לזהות את מזהה הסרטון."

    frames = download_and_save_frames(video_id)

    if not frames:
        return "ALLOW: לא ניתן להוריד תמונות — הסרטון נפתח (כשל טכני בלבד)."

    results = []
    for i, frame_path in enumerate(frames):
        decision = analyze_single_image(frame_path)
        results.append(f"תמונה {i+1}: {decision}")

        if "BLOCK" in decision.upper():
            return f"BLOCK (בדיקה {i+1}): {decision}"

    combined_results = "\n".join(results)
    return f"ALLOW: כל התמונות נבדקו ואושרו.\n{combined_results}"

# --- נתיבי השרת ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    result = analyze_video_logic(url)
    return jsonify({"decision": result})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)