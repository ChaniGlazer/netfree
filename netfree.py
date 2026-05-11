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
    """מבצע את לוגיקת ה-AI על תמונה ספציפית עם ה-Rules שלך"""
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')

    ai_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system", 
                "content": "You are a strict content filter."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": """Analyze this image very carefully and decide 'ALLOW' or 'BLOCK'.
                        
                        Rules for BLOCK:
                        1. A woman or a girl is clearly visible in the image.
                        2. Secular news logos are present (e.g., Channel 12, 13, 11, CNN, etc.).
                        3. The background is a professional TV/News studio.
                        
                        Rules for ALLOW:
                        1. Only men or boys are visible.
                        2. Landscapes, nature, or objects without any women.
                        3. If there is ONLY text but NO actual woman visible, ALLOW.
                        
                        Explain your decision briefly in Hebrew."""
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

    # 1. הורדת 3 תמונות ושמירתן ב-public
    frames = download_and_save_frames(video_id)
    
    if not frames:
        return "BLOCK: לא ניתן להוריד תמונות מהסרטון לבדיקה."

    # 2. מעבר על כל התמונות ובדיקה ב-AI
    results = []
    for i, frame_path in enumerate(frames):
        decision = analyze_single_image(frame_path)
        results.append(f"תמונה {i+1}: {decision}")
        
        # אם אחת מהתמונות נחסמה - חוסמים את הכל מיד
        if "BLOCK" in decision.upper():
            return f"נחסם (בדיקה {i+1}): {decision}"

    # אם הגענו לכאן, הכל עבר בהצלחה
    combined_results = "\n".join(results)
    return f"ALLOW: כל 3 הנקודות נבדקו ואושרו.\n{combined_results}"

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