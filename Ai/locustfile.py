import random
from locust import HttpUser, task, between

class AdvancedPressTest(HttpUser):
    # 模擬每位使用者停頓 1 到 3 秒，更接近真人行為
    wait_time = between(1, 3)

    @task(5)  # 權重最高：核心功能測試
    def test_department_query(self):
        """情境 1：精準系所查詢 (測試 RAG 檢索效率)"""
        questions = [
            "電機系老師有哪些？",
            "電子系的課程安排",
            "半導體學院在哪裡？",
            "資工系的系主任是誰？"
        ]
        self._post_test(random.choice(questions))

    @task(3)
    def test_general_query(self):
        """情境 2：一般校園諮詢 (測試 AI 彙整能力)"""
        questions = [
            "明新科大的交通方式？",
            "學校附近有什麼好吃的？",
            "圖書館幾點開門？"
        ]
        self._post_test(random.choice(questions))

    @task(2)
    def test_oos_query(self):
        """情境 3：邊界測試 (測試系統在無資料時的反應)"""
        questions = [
            "今天天氣好嗎？",
            "你會寫程式嗎？",
            "明新科大有超能力學院嗎？"
        ]
        self._post_test(random.choice(questions))

    def _post_test(self, text):
        payload = {
            "text": text,
            "userId": f"user_{random.randint(1, 999)}"
        }
        # 向我們之前建置的 /test_press 端點發送請求
        self.client.post("/test_press", json=payload)