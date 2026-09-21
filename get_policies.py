import os
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

res = supabase.rpc("run_sql", {"sql_query": "SELECT * FROM pg_policies WHERE tablename = 'orders';"}).execute()
print(res.data)
