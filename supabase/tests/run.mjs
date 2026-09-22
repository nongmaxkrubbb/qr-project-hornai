/** Real PostgreSQL (WASM) in memory; never reads .env or connects to Supabase. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { PGlite } = require('@electric-sql/pglite');
const { pgcrypto } = require('@electric-sql/pglite/contrib/pgcrypto');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
async function run(legacy) {
  const db = new PGlite({ extensions: { pgcrypto } });
  const label = legacy ? 'legacy upgrade' : 'fresh install';
  try {
    await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
      CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
      CREATE SCHEMA storage;
      CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
      CREATE TABLE storage.objects(id uuid PRIMARY KEY,bucket_id text); ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
      INSERT INTO storage.buckets(id,name,public) VALUES('slips','slips',true);`);
    await db.exec(read(legacy ? 'supabase/tests/legacy_schema.sql' : 'supabase/schema.sql'));
    await db.exec(read('supabase/migrations/202609210001_production_foundation.sql'));
    await db.exec(read('supabase/migrations/202609210001_production_foundation.sql'));
    await db.exec(read('supabase/tests/production_foundation.sql'));
    const { rows } = await db.query(`SELECT public FROM storage.buckets WHERE id='slips'`);
    if (rows[0]?.public !== false) throw new Error('slips bucket must be private');
    if (legacy) {
      const { rows: old } = await db.query(`SELECT o.payment_status,o.token_hash,s.organization_id,
        (SELECT last_number FROM order_counters WHERE branch_id=o.branch_id AND the_date=o.order_date) AS number,
        (SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='orders') AS policies
        FROM orders o CROSS JOIN staff s WHERE o.order_code='Q023' AND s.username='legacy_staff'`);
      if (old[0]?.payment_status !== 'legacy_unverified' || old[0]?.token_hash !== null || old[0]?.organization_id !== 'e1000000-0000-0000-0000-000000000001' || old[0]?.number !== 23 || Number(old[0]?.policies) !== 0) {
        throw new Error('Legacy receipts, staff organization, counter or privacy migration failed: ' + JSON.stringify(old));
      }
    }
    console.log(`PASS ${label}: migration replay, transactional regressions, private storage${legacy ? ', historical receipts, staff organization and counters' : ''}`);
  } finally { await db.close(); }
}
try { await run(false); await run(true); }
catch (error) { console.error(error.message, error.detail || '', error.where || ''); process.exitCode = 1; }
