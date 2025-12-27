import subprocess
import os
import time

def run_test_stage(users, spawn_rate, duration, prefix):
    base_path = os.path.dirname(os.path.abspath(__file__))
    target_file = os.path.join(base_path, "locustfile.py")
    host = "http://127.0.0.1:5000"
    
    cmd = f"locust -f \"{target_file}\" --headless -u {users} -r {spawn_rate} --run-time {duration} --host {host} --csv={prefix}"
    
    print(f"\n🔥 [階段測試] 模擬人數: {users}, 持續: {duration}...")
    try:
        subprocess.run(cmd, shell=True, check=True)
        print(f"✅ {prefix} 測試完成。")
    except Exception as e:
        print(f"❌ 測試中斷: {e}")

def main():
    print("🚀 開始多階段壓力測試自動化...")
    
    # 階段 1: 穩定載入測試 (20人)
    run_test_stage(20, 5, "30s", "stage1_normal")
    
    # 休息一下讓 AI API 喘口氣
    time.sleep(5)
    
    # 階段 2: 高負載測試 (50人) - 測試系統會不會崩潰
    run_test_stage(50, 10, "30s", "stage2_heavy")

    print("\n📊 所有階段完成！請查看生成的 stage1_... 與 stage2_... 檔案。")

if __name__ == "__main__":
    main()