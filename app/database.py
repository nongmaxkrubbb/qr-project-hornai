import os
from supabase import create_client, Client
from flask import current_app

_supabase: Client = None

def get_supabase() -> Client:
    """คืนค่า Supabase Python Client (ผูกกับ Service Role Key) สำหรับใช้งานฝั่ง Server"""
    global _supabase
    if _supabase is None:
        url = current_app.config.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
        key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _supabase = create_client(url, key)
    return _supabase

def init_app(app):
    # ไม่ต้องทำอะไรพิเศษเพราะ Supabase Python Client stateless
    # (ใช้ API เรียกไปที่ Supabase)
    pass