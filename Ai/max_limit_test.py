import subprocess
import os
import time

def run_limit_stage(users, spawn_rate, duration, prefix):
    base_path = os.path.dirname(os.path.abspath(__file__))
    target_file = os.path.join(base_path, "locustfile.py")
    host = "http://127.0.0.1:5000"
    
    # --headless: 不啟動網頁介面
    # -u: 使用者總數
    # -r: 每秒產生人數
    cmd = f"locust -f \"{target_file}\" --headless -u {users} -r {spawn_rate} --run-time {duration} --host {host} --csv={prefix}"
    
    print(f"\n🚀 [衝刺測試] 目標人數: {users} 人 | 每秒增加: {spawn_rate} 人...")
    try:
        subprocess.run(cmd, shell=True, check=True)
        print(f"✅ {prefix} 階段完成。")
    except Exception as e:
        print(f"❌ 系統可能已達上限或中斷: {e}")

def main():
    print("🔥 開始探測系統最高極限 (Stress Peak Test)...")
    print("注意：此測試可能會導致 Groq API 暫時停用或電腦風扇加速轉動。")
    
    # 階段 1: 輕量衝刺 (100人)
    run_limit_stage(100, 20, "20s", "limit_100")
    time.sleep(10)
    
    # 階段 2: 中量加壓 (200人)
    run_limit_stage(200, 40, "20s", "limit_200")
    time.sleep(10)
    
    # 階段 3: 極限挑戰 (300人)
    run_limit_stage(300, 60, "20s", "limit_300")

    # 階段 4: 極限挑戰 (400人)
    run_limit_stage(400, 60, "20s", "limit_400")

    # 階段 5: 極限挑戰 (500人)
    run_limit_stage(500, 60, "20s", "limit_500")

    print("\n🏁 極限測試結束！請查看 limit_100, limit_200, limit_300 的數據。")
    print("重點檢查：哪一個階段開始出現 Failure Count > 0？")

if __name__ == "__main__":
    main()