#!/usr/bin/env python3
"""
scripts/build_desktop.py — สคริปต์ช่วยบิลด์ระบบ คิวอิ่ม ให้เป็น Desktop Executable (.app บน macOS หรือ .exe บน Windows)
การใช้งาน:
    python scripts/build_desktop.py
"""

import os
import platform
import subprocess
import sys


def build():
    print("🔨 เริ่มต้นกระบวนการบิลด์ Desktop Application...")

    # ตรวจสอบว่าติดตั้ง pyinstaller หรือยัง
    try:
        import PyInstaller
    except ImportError:
        print("❌ ไม่พบ PyInstaller ในระบบ กรุณาติดตั้งก่อนด้วยคำสั่ง:")
        print("   pip install pyinstaller pywebview")
        sys.exit(1)

    system = platform.system()
    sep = ";" if system == "Windows" else ":"

    # ไฟล์และโฟลเดอร์ที่ต้องรวมเข้ากับตัวแพ็กเกจ
    add_data = [
        f"templates{sep}templates",
        f"static{sep}static",
    ]

    if os.path.exists(".env"):
        add_data.append(f".env{sep}.")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=คิวอิ่ม",
        "--noconfirm",
        "--onedir",
        "--windowed",  # ซ่อน terminal window
        "desktop_app.py",
    ]

    for item in add_data:
        cmd.extend(["--add-data", item])

    # ซ่อน warning / hooks ที่จำเป็น
    hidden_imports = [
        "engineio.async_drivers.threading",
        "jinja2",
        "flask",
        "dotenv",
        "cachelib",
    ]
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])

    print(f"📦 รันคำสั่ง: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n🎉 บิลด์สำเร็จเรียบร้อยแล้ว!")
        if system == "Darwin":
            print("📁 ไฟล์แอปพลิเคชันอยู่ที่: dist/คิวอิ่ม.app")
        elif system == "Windows":
            print("📁 ไฟล์แอปพลิเคชันอยู่ที่: dist/คิวอิ่ม/คิวอิ่ม.exe")
        else:
            print("📁 ไฟล์แอปพลิเคชันอยู่ที่: dist/คิวอิ่ม/")
    else:
        print("\n❌ การบิลด์เกิดข้อผิดพลาด")
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
