import yt_dlp
import cv2
import base64
import os
import ssl
import urllib3
from openai import OpenAI
from dotenv import load_dotenv

# הגדרות נטפרי
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
if (not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None)):
    ssl._create_default_https_context = ssl._create_unverified_context

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_multiple_frames(url, num_frames=3):
    """שולף מספר פריימים מזמנים שונים בסרטון"""
    print(f"מתחבר לזרם הוידאו כדי לדגום {num_frames} פריימים...")
    ydl_opts = {'format': 'best[ext=mp4]/best', 'quiet': True, 'nocheckcertificate': True}
    
    frames_b64 = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_url = info['url']
            duration = info.get('duration', 60) # אורך הסרטון בשניות
            
            cap = cv2.VideoCapture(video_url)
            
            # דגימה ב-20%, 50% ו-80% מאורך הסרטון
            for i in range(1, num_frames + 1):
                timestamp = (duration * 1000) * (i / (num_frames + 1))
                cap.set(cv2.CAP_PROP_POS_MSEC, timestamp)
                success, frame = cap.read()
                if success:
                    _, buffer = cv2.imencode('.jpg', frame)
                    frames_b64.append(base64.b64encode(buffer).decode('utf-8'))
                    # שמירה לבדיקה ידנית
                    cv2.imwrite(f"debug_frame_{i}.jpg", frame)
            
            cap.release()
            return frames_b64
    except Exception as e:
        print(f"שגיאה: {e}")
    return []

def analyze_video_multi_frame(url):
    frames = get_multiple_frames(url)
    
    if not frames:
        return "שגיאה: לא הצלחתי לדגום תוכן מהוידאו."

    print("הפריימים נשלפו. שולח ניתוח משולב ל-AI...")
    
    # בניית הודעה עם מספר תמונות
    image_contents = [{"type": "text", "text": "These are 3 different frames from the same video. If ANY of them shows a woman or a news studio, reply 'BLOCK'. Otherwise 'ALLOW'. Explain in Hebrew."}]
    
    for b64 in frames:
        image_contents.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    ai_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": image_contents}],
        max_tokens=200
    )
    return ai_resp.choices[0].message.content.strip()

if __name__ == "__main__":
    test_link = "https://www.youtube.com/watch?v=IrAWsyR1emY"
    print(analyze_video_multi_frame(test_link))