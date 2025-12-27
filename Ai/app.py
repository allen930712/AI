import os, json, re, traceback, requests 
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage,
    TemplateSendMessage, ButtonsTemplate, URITemplateAction 
)
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
app = Flask(__name__)

# --- 初始化 LINE 與 Groq ---
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct" 

# ========= 1. 知識庫預載入 (確保掃描電機系 JSON) =========
GLOBAL_KB = {}
def preload_knowledge_base():
    global GLOBAL_KB
    kb = {}
    data_path = "data"
    if not os.path.exists(data_path):
        print(f"⚠️ 找不到資料夾: {data_path}")
        return
    for root, dirs, files in os.walk(data_path):
        for file in files:
            if file.endswith(".json"):
                try:
                    with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                        kb.update(json.load(f))
                except: pass
    GLOBAL_KB = kb
    print(f"✅ 知識庫載入完成，共 {len(GLOBAL_KB)} 筆資料")

preload_knowledge_base()

# ========= 2. AI 邏輯與 RAG 檢索 =========
try:
    groq_client = Groq(api_key=GROQ_API_KEY)
except:
    groq_client = None

def _norm(s): return re.sub(r"\s+", "", str(s)).lower()

def retrieve_local_content(user_text):
    norm_text = _norm(user_text)
    related_chunks = []
    # 針對電機系與電子系的精準比對邏輯
    for topic, info in GLOBAL_KB.items():
        kws = info.get("關鍵字", [])
        if _norm(topic) in norm_text or any(_norm(kw) in norm_text for kw in kws):
            for key, val in info.items():
                if key not in ["關鍵字", "圖片", "URL_LINKS"]:
                    related_chunks.append(f"[{key}]：{val}")
    return "\n".join(related_chunks)

def GPT_response(user_text, context):
    if not groq_client: return "AI 離線中"
    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": f"你是一位專業助理。請根據以下資訊回答問題：\n{context}"},
                {"role": "user", "content": user_text}
            ],
            temperature=0.2
        )
        return completion.choices[0].message.content.strip()
    except: return "AI 暫時無法回應"

# ========= 3. [核心修正] 增加測試專用路由，解決 404 問題 =========
@app.route("/test_press", methods=['POST'])
def test_press():
    try:
        # 接收來自 locustfile.py 的簡單 JSON
        data = request.json
        u_text = data.get("text", "電機系老師")
        
        # 執行 RAG 檢索與 AI 生成
        context = retrieve_local_content(u_text)
        reply = GPT_response(u_text, context)
        
        print(f"⚡ [壓測成功] 訊息: {u_text}")
        return {"status": "success", "reply": reply[:10]}, 200
    except Exception as e:
        print(f"❌ 測試端點內部錯誤: {e}")
        return {"status": "error"}, 500

# ========= 4. 原始 LINE Webhook 路徑 =========
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    context = retrieve_local_content(user_text)
    reply = GPT_response(user_text, context)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)