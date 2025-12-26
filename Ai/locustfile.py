import json
from locust import HttpUser, task, between

class LineBotPressureTest(HttpUser):
    # 模擬使用者發送訊息後的思考時間（1~3秒）
    wait_time = between(1, 3)

    @task
    def send_webhook_message(self):
        """
        模擬 LINE Messaging API 發送的 Webhook POST 請求
        """
        # 模擬測試訊息：包含一個關鍵字以觸發 RAG 檢索
        payload = {
            "destination": "xxxxxxxxxx",
            "events": [
                {
                    "type": "message",
                    "message": {
                        "type": "text",
                        "id": "123456789",
                        "text": "電子系介紹"  # 這裡可以更改為不同的關鍵字進行測試
                    },
                    "timestamp": 1627310000000,
                    "source": {
                        "type": "user",
                        "userId": "U123456789abcdef"
                    },
                    "replyToken": "nH7wFpWTP9uJ9qn3"
                }
            ]
        }

        # 設定 Header：模擬 LINE 要求的簽章（您的程式目前只驗證格式，壓測時可帶入 mock 值）
        headers = {
            'Content-Type': 'application/json',
            'X-Line-Signature': 'pressure_test_mock_signature'
        }

        # 發送 POST 請求到您的 /callback 端點
        with self.client.post("/callback", json=payload, headers=headers, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")

    @task(1)
    def test_random_query(self):
        """
        模擬使用者詢問不在資料庫內的隨機問題，測試單純 AI 推理的效能
        """
        payload = {
            "events": [{
                "type": "message",
                "message": {"type": "text", "text": "今天天氣怎麼樣？"},
                "source": {"type": "user", "userId": "U_random_001"},
                "replyToken": "random_token"
            }]
        }
        headers = {'X-Line-Signature': 'mock'}
        self.client.post("/callback", json=payload, headers=headers)