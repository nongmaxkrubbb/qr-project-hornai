import os
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
try:
    res = supabase.rpc("run_sql", {"sql_query": "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'orders_status_check';"}).execute()
    print(res.data)
except Exception as e:
    print(e)
