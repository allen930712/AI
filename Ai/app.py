import os, json, re, traceback, requests 
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage,
    TemplateSendMessage, ButtonsTemplate, URITemplateAction # <-- 新增 Template 相關
)
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct" 

# ========= Groq 客戶端初始化 =========
try:
    groq_client = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    print(f"⚠️ Groq 客戶端初始化失敗：{e}")
    groq_client = None


# ========= 工具區 =========
def _norm(s):
    return re.sub(r"\s+", "", str(s)).lower()

def _join(val):
    if isinstance(val, list):
        return "\n".join(map(str, val))
    return str(val)

def load_all_json():
    kb = {}
    data_path = "data"
    
    for root, dirs, files in os.walk(data_path):
        for file in files:
            if file.endswith(".json"):
                file_path = os.path.join(root, file)
                
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        kb.update(data)
                except Exception as e:
                    print(f"⚠️ 讀取 {file_path} 失敗：{e}")
    return kb

# ========= RAG 檢索：提取本地上下文 (保持不變) =========
def retrieve_local_chunks(user_text: str) -> str:
    kb = load_all_json()
    norm_text = _norm(user_text)
    
    related_chunks = []

    for topic, info in kb.items():
        kws = info.get("關鍵字", [])
        
        is_topic_matched = (_norm(topic) in norm_text)
        is_keyword_matched = False
        
        if isinstance(kws, list):
            if any(_norm(kw) in norm_text for kw in kws):
                is_keyword_matched = True
        elif isinstance(kws, dict):
            for arr in kws.values():
                if any(_norm(kw) in norm_text for kw in arr):
                    is_keyword_matched = True
                    break
        
        if is_topic_matched or is_keyword_matched:
            for key, val in info.items():
                # 關鍵：這裡排除 URL_LINKS，讓 AI 專注於文字，連結由 Line Template 處理
                if key not in ["關鍵字", "圖片", "URL_LINKS"]: 
                    related_chunks.append(f"[{key}]：{_join(val)}")

    if related_chunks:
        return "\n--- 知識庫參考資訊 ---\n" + "\n".join(related_chunks) + "\n-------------------------\n"
    return ""

# (圖片檢索函式保持不變)
# ========= 圖片檢索：提取圖片 URL 列表 =========
def retrieve_image_urls(user_text: str) -> list[str] | None:
    kb = load_all_json()
    norm_text = _norm(user_text)

    for topic, info in kb.items():
        kws = info.get("關鍵字", [])

        is_topic_matched = (_norm(topic) in norm_text)
        is_keyword_matched = False
        
        if isinstance(kws, list):
            if any(_norm(kw) in norm_text for kw in kws):
                is_keyword_matched = True
        elif isinstance(kws, dict):
            for arr in kws.values():
                if any(_norm(kw) in norm_text for kw in arr):
                    is_keyword_matched = True
                    break
        
        if is_topic_matched or is_keyword_matched:
            image_urls = info.get("圖片")
            if image_urls and isinstance(image_urls, list):
                return image_urls

    return None

# ========= 新增：連結檢索：提取 Template URL 列表 =========
def retrieve_url_links(user_text: str) -> list[dict] | None:
    kb = load_all_json()
    norm_text = _norm(user_text)

    for topic, info in kb.items():
        kws = info.get("關鍵字", [])
        
        is_topic_matched = (_norm(topic) in norm_text) or any(_norm(kw) in norm_text for kw in kws)
        
        if is_topic_matched:
            url_links = info.get("URL_LINKS")
            if url_links and isinstance(url_links, list):
                return url_links

    return None


# ========= Groq RAG 核心處理邏輯 (使用 Groq SDK) =========
memory = {}

def GPT_response(user_id, user_text):
    if groq_client is None:
        return "抱歉，AI 服務器初始化失敗，請檢查 API 密鑰。"

    local_context = retrieve_local_chunks(user_text)

    if user_id not in memory:
        memory[user_id] = []
    
    system_prompt = (
        "你是一個親切且專業的 AI 助理，請用繁體中文回覆。 "
        "你的主要任務是根據提供的「知識庫參考資訊」來回答使用者問題。 "
        "請嚴格且優先使用參考資訊中的內容來組織回覆，不要臆測。 "
        "如果參考資訊中找不到答案或該資訊不夠完整，請禮貌地告知使用者資料庫中沒有相關細節。 "
        "請保持回覆流暢自然，並務必使用更為口語化、親切的語氣重新組織和潤飾答案。"
    )
    
    full_system_content = system_prompt + local_context

    current_user_message = {"role": "user", "content": user_text}
    # 限制歷史為 -5 筆，幫助控制 Token 數
    history_messages = memory[user_id][-5:]
    
    context = (
        [{"role": "system", "content": full_system_content}] +
        history_messages +
        [current_user_message]
    )

    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=context,
            temperature=0.4, # 調整為 0.4 提高穩定性
            max_tokens=800
        )
        
        reply = completion.choices[0].message.content.strip()
            
        memory[user_id].append(current_user_message)
        memory[user_id].append({"role": "assistant", "content": reply})
        
        return reply
        
    except Exception as e:
        print(f"Groq API 錯誤 (SDK): {e}\nTraceback: {traceback.format_exc()}")
        return "抱歉，AI 服務器處理請求時發生錯誤，請檢查 API 密鑰和模型名稱。"


# ========= LINE Webhook (包含圖片/連結回覆邏輯) =========
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text.strip()
    
    # 1. 檢索所有內容
    image_urls = retrieve_image_urls(user_text)
    url_links = retrieve_url_links(user_text) # <-- 新增
    
    reply_message = "發生錯誤，請稍後再試。" 
    
    # 嘗試獲取文字回覆
    try:
        reply_message = GPT_response(user_id, user_text)
    except Exception:
        print(f"GPT_response 失敗: {traceback.format_exc()}")

    # 嘗試發送所有訊息
    try:
        # 3. 構建訊息列表，第一個是文字回覆
        messages = [TextSendMessage(text=reply_message)]
        
        # 4. 加入圖片回覆
        if image_urls:
            for url in image_urls:
                 messages.append(ImageSendMessage(original_content_url=url, preview_image_url=url))
        
        # 5. 加入 Template 連結回覆 (解決連結失效問題)
        if url_links:
            actions = [
                URITemplateAction(label=link['標題'], uri=link['網址'])
                for link in url_links
            ]
            
            # Line Template 按鈕數量限制為 4 個
            messages.append(
                TemplateSendMessage(
                    alt_text='相關連結資訊',
                    template=ButtonsTemplate(
                        title='相關介紹與下載',
                        text='點擊下方按鈕以查看相關檔案或詳細介紹。',
                        actions=actions[:4] 
                    )
                )
            )
        
        # 6. 回覆所有訊息
        line_bot_api.reply_message(event.reply_token, messages)
        
    except Exception as e:
        print(f"LINE API 回覆失敗: {e}\nTraceback: {traceback.format_exc()}")
        final_text = f"🚨 系統連線成功，但部分訊息無法傳送。這是文字回覆：\n{reply_message}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=final_text))


if __name__ == "__main__":
    app.run(port=5000)