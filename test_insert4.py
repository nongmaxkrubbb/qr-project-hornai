import os
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

branch_id = "00000000-0000-0000-0000-000000000011"
order_data = {
    "order_code": "Q123",
    "branch_id": branch_id,
    "student_name": "Test",
    "room_no": None,
    "note": None,
    "status": "pending_payment",
    "payment_method": "promptpay",
    "payment_status": "pending",
    "total_price": 50
}
try:
    res_order = supabase.table("orders").insert(order_data).execute()
    print("Success:", res_order.data)
except Exception as e:
    print("Error:", e)
