import os
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
try:
    res = supabase.table("orders").select("*").limit(1).execute()
    print("RLS test bypassed successfully using service_role.")
except Exception as e:
    print(e)
