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

line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct" 

# ========= 1. [優化第5點] 知識庫全域快取與預載入 =========
GLOBAL_KB = {}

def preload_knowledge_base():
    """啟動時加載所有 JSON，避免每次請求都進行硬碟 I/O"""
    global GLOBAL_KB
    kb = {}
    data_path = "data"
    if not os.path.exists(data_path):
        print(f"⚠️ 找不到資料夾: {data_path}")
        return
    
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
    GLOBAL_KB = kb
    print(f"✅ 知識庫載入完成，共 {len(GLOBAL_KB)} 個主題")

# 立即執行預載入
preload_knowledge_base()

# ========= Groq 客戶端初始化 =========
try:
    groq_client = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    print(f" Groq 客戶端初始化失敗：{e}")
    groq_client = None


# ========= 工具區 =========
def _norm(s):
    return re.sub(r"\s+", "", str(s)).lower()

def _join(val):
    if isinstance(val, list):
        return "\n".join(map(str, val))
    return str(val)

# ========= 2. [優化第5點] 高效 RAG 檢索邏輯 =========
def retrieve_local_content(user_text: str):
    #整合檢索：同時返回文字上下文、圖片與連結。
    #使用預載入的 GLOBAL_KB，並優化關鍵字匹配算法。
    norm_text = _norm(user_text)
    related_chunks = []
    image_urls = None
    url_links = None

    for topic, info in GLOBAL_KB.items():
        kws = info.get("關鍵字", [])
        
        # 標題或關鍵字匹配
        topic_match = (_norm(topic) in norm_text)
        kw_match = False
        if isinstance(kws, list):
            kw_match = any(_norm(kw) in norm_text for kw in kws)
        
        if topic_match or kw_match:
            # 提取文字內容 (排除非文字欄位)
            for key, val in info.items():
                if key not in ["關鍵字", "圖片", "URL_LINKS"]: 
                    related_chunks.append(f"[{key}]：{_join(val)}")
            
            # 提取圖片 (若存在)
            if not image_urls:
                image_urls = info.get("圖片")
            
            # 提取連結 (若存在)
            if not url_links:
                url_links = info.get("URL_LINKS")

    context_str = ""
    if related_chunks:
        context_str = "\n--- 知識庫參考資訊 ---\n" + "\n".join(related_chunks) + "\n-------------------------\n"
    
    return context_str, image_urls, url_links

# ========= 3. [優化第3點] 上下文與 Token 管理器 =========
memory = {}
MAX_HISTORY_CHAR = 2000 # 粗略限制對話歷史長度（防止 Token 溢出）

def manage_history(user_id, new_message):
    """管理使用者的對話歷史，實施滑動窗口截斷"""
    if user_id not in memory:
        memory[user_id] = []
    
    memory[user_id].append(new_message)
    
    # 計算當前總長度（粗略以字數計算）
    total_len = sum(len(m['content']) for m in memory[user_id])
    
    # 如果過長，刪除最舊的對話（保留最新的訊息）
    while total_len > MAX_HISTORY_CHAR and len(memory[user_id]) > 2:
        removed = memory[user_id].pop(0)
        total_len -= len(removed['content'])

def GPT_response(user_id, user_text, local_context):
    if groq_client is None:
        return "抱歉，AI 服務器初始化失敗。"

    system_prompt = (
        "你是一個親切且專業的明新科大 AI 助理，請用繁體中文回覆。\n"
        "你的任務是根據「知識庫參考資訊」回答問題。若資訊不足，請基於一般常識回覆並引導使用者詢問學校相關部門。\n"
        "請務必口語化、親切，像是一個學長姐在回答問題。"
    )
    
    full_system_content = system_prompt + local_context

    # 獲取最近的對話歷史 (限制最多 8 筆以節省 Token)
    history_messages = memory.get(user_id, [])[-8:]
    
    context = (
        [{"role": "system", "content": full_system_content}] +
        history_messages +
        [{"role": "user", "content": user_text}]
    )

    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=context,
            temperature=0.4,
            max_tokens=800
        )
        
        reply = completion.choices[0].message.content.strip()
        
        # 存入記憶 (包含使用者輸入與助理回覆)
        manage_history(user_id, {"role": "user", "content": user_text})
        manage_history(user_id, {"role": "assistant", "content": reply})
        
        return reply
        
    except Exception as e:
        print(f"Groq 錯誤: {e}")
        return "抱歉，我現在腦袋有點打結，請稍後再問我一次！"


# ========= LINE Webhook =========
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
    
    # 1. 檢索優化：一次性提取所有相關資料
    local_context, image_urls, url_links = retrieve_local_content(user_text)
    
    # 2. 獲取 AI 回覆
    reply_message = GPT_response(user_id, user_text, local_context)

    # 3. 構建 LINE 訊息
    try:
        messages = [TextSendMessage(text=reply_message)]
        
        # 圖片處理
        if image_urls:
            for url in image_urls[:2]: # 限制最多發送 2 張圖片以免洗版
                 messages.append(ImageSendMessage(original_content_url=url, preview_image_url=url))
        
        # 連結處理 (Template)
        if url_links:
            actions = [
                URITemplateAction(label=link['標題'][:20], uri=link['網址']) # Label 限制 20 字
                for link in url_links[:4] # 最多 4 個按鈕
            ]
            messages.append(
                TemplateSendMessage(
                    alt_text='點擊查看相關連結',
                    template=ButtonsTemplate(
                        title='相關介紹與下載',
                        text='點擊下方按鈕以查看詳細資訊：',
                        actions=actions
                    )
                )
            )
        
        line_bot_api.reply_message(event.reply_token, messages)
        
    except Exception as e:
        print(f"LINE 回覆失敗: {e}")
        # 備援計畫：僅傳送文字
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_message))


if __name__ == "__main__":
    # 建議生產環境改用 Gunicorn
    app.run(host='0.0.0.0', port=5000)