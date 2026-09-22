#!/usr/bin/env python3
"""
desktop_app.py — Desktop Application Launcher สำหรับระบบ คิวอิ่ม (Q-Im)
รันระบบเป็นโปรแกรมเดสก์ท็อปแบบแยกไฟล์อิสระ (Standalone Desktop Launcher)

การใช้งาน:
    python desktop_app.py
    python desktop_app.py --mode=admin
    python desktop_app.py --mode=kitchen --fullscreen
"""

import argparse
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urljoin
from urllib.request import urlopen

# โหลด .env
from dotenv import load_dotenv
load_dotenv()


def find_free_port(start_port: int = 5001, max_tries: int = 50) -> int:
    """ค้นหา Port ที่ว่างสำหรับรัน Local Server"""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            result = sock.connect_ex(("127.0.0.1", port))
            if result != 0:
                return port
    return start_port


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    """รอให้เซิร์ฟเวอร์พร้อมให้บริการก่อนเปิดหน้าต่าง Desktop"""
    start_time = time.time()
    health_url = urljoin(url, "/healthz")
    while time.time() - start_time < timeout:
        try:
            with urlopen(health_url, timeout=1.0) as resp:
                if resp.status in (200, 204):
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def start_flask_server(port: int):
    """รัน Flask ใน Background Thread พร้อมคืน handle สำหรับปิดเซิร์ฟเวอร์"""
    from werkzeug.serving import make_server
    from app import create_app

    # บังคับ config สำหรับ local desktop mode โดยไม่กระทบค่าหลักใน .env
    override_config = {
        "APP_ENV": "development",
        "PUBLIC_BASE_URL": "",  # ปลดล็อค domain restriction สำหรับ local desktop
    }
    app = create_app(config=override_config)

    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def open_browser_app_mode(url: str):
    """
    Fallback เมื่อไม่มี pywebview:
    เปิดหน้าต่างแอปเดสก์ท็อปผ่าน App-Mode (ไม่มีแถบ URL/Tabs) ด้วย Chrome, Edge หรือ Brave
    """
    system = platform.system()
    app_flag = f"--app={url}"

    browser_candidates = []
    if system == "Darwin":  # macOS
        browser_candidates = [
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", app_flag],
            ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", app_flag],
            ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", app_flag],
        ]
    elif system == "Windows":
        browser_candidates = [
            [os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"), app_flag],
            [os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), app_flag],
            [os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), app_flag],
        ]
    elif system == "Linux":
        browser_candidates = [
            ["google-chrome", app_flag],
            ["chromium-browser", app_flag],
            ["chromium", app_flag],
        ]

    for candidate in browser_candidates:
        executable = candidate[0]
        if os.path.exists(executable) or system == "Linux":
            try:
                proc = subprocess.Popen(candidate)
                return proc
            except Exception:
                continue

    # หากไม่พบ Chrome/Edge ให้เปิดด้วย default browser
    import webbrowser
    webbrowser.open(url)
    return None


def run_desktop_app(mode: str = "customer", port: int = None, fullscreen: bool = False, force_browser: bool = False):
    port = port or find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    # กำหนด URL เริ่มต้นตามโหมดการใช้งาน
    routes = {
        "customer": "/",
        "admin": "/admin/login",
        "staff": "/admin/login",
        "kitchen": "/admin/login",
        "dashboard": "/admin/dashboard",
    }
    target_path = routes.get(mode.lower(), "/")
    target_url = urljoin(base_url, target_path)

    print("=" * 60)
    print("🍲  คิวอิ่ม (Q-Im) — Desktop Application")
    print(f"📍 Local Server Port: {port}")
    print(f"🎯 Target URL: {target_url}")
    print(f"🛠️  Mode: {mode}")
    print("=" * 60)

    # 1. สตาร์ท Local Flask Server
    print("⏳ กำลังเริ่มระบบเซิร์ฟเวอร์ภายในเครื่อง...")
    server = start_flask_server(port)

    # 2. รอจนกระทั่งเซิร์ฟเวอร์พร้อม
    if not wait_for_server(base_url, timeout=10.0):
        print("❌ เกิดข้อผิดพลาด: เซิร์ฟเวอร์ไม่ตอบสนองภายในเวลาที่กำหนด")
        server.shutdown()
        sys.exit(1)

    print("✅ เซิร์ฟเวอร์พร้อมใช้งานแล้ว กำลังเปิดหน้าต่าง Desktop...")

    # 3. ตรวจสอบว่ามี pywebview หรือไม่
    has_webview = False
    if not force_browser:
        try:
            import webview
            has_webview = True
        except ImportError:
            has_webview = False

    if has_webview:
        import webview
        print("🖥️  รันด้วย Native GUI Window (pywebview)")
        window = webview.create_window(
            title="คิวอิ่ม (Q-Im) — ระบบสั่งอาหารและจัดการคิว",
            url=target_url,
            width=1280,
            height=850,
            min_size=(900, 600),
            resizable=True,
            fullscreen=fullscreen,
            confirm_close=False,
        )

        def on_closed():
            print("\n🚪 กำลังปิดหน้าต่างและหยุดการทำงานของเซิร์ฟเวอร์...")
            server.shutdown()

        window.events.closed += on_closed
        webview.start()
        print("👋 ปิดโปรแกรมเรียบร้อยแล้ว")
    else:
        # Fallback Mode
        print("💡 [Info] ยังไม่ได้ติดตั้ง pywebview ในระบบ")
        print("   -> ระบบจะเปิดเป็น Desktop Window App-Mode ให้อัตโนมัติ")
        print("   -> สามารถติดตั้ง pywebview เพิ่มเติมเพื่อความสมบูรณ์แบบได้ด้วยคำสั่ง:")
        print("      pip install pywebview\n")

        browser_proc = open_browser_app_mode(target_url)
        print("✨ เปิดหน้าต่างเดสก์ท็อปเรียบร้อยแล้ว กด Ctrl+C ในเทอร์มินัลเพื่อปิดโปรแกรม")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🚪 กำลังหยุดการทำงานของเซิร์ฟเวอร์...")
            server.shutdown()
            if browser_proc:
                try:
                    browser_proc.terminate()
                except Exception:
                    pass
            print("👋 ปิดโปรแกรมเรียบร้อยแล้ว")


def parse_args():
    parser = argparse.ArgumentParser(
        description="คิวอิ่ม (Q-Im) — Desktop Application Launcher",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["customer", "admin", "staff", "kitchen", "dashboard"],
        default="customer",
        help="โหมดเริ่มต้นของแอปพลิเคชัน (customer: สั่งอาหาร/ดูคิว, admin/staff: เจ้าหน้าที่, kitchen: จอครัว)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="พอร์ตสำหรับรันเซิร์ฟเวอร์ภายในเครื่อง (ค่าเริ่มต้น: ค้นหาพอร์ตว่างอัตโนมัติ)",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="เปิดแอปพลิเคชันแบบเต็มจอ (เหมาะสำหรับ Kitchen Display Screen)",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="บังคับเปิดในหน้าต่าง Browser App Mode แทน pywebview",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_desktop_app(
        mode=args.mode,
        port=args.port,
        fullscreen=args.fullscreen,
        force_browser=args.browser,
    )
