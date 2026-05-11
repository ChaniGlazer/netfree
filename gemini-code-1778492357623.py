import requests

# החליפי בכתובת שקיבלת מ-Render
url_on_render = "http://127.0.0.1:5000/analyze"

data = {
    "url": "https://www.youtube.com/watch?v=IrAWsyR1emY"
}

response = requests.post(url_on_render, json=data)
print(response.json())