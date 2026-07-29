import { neon } from "@neondatabase/serverless";

// Neon's Vercel integration sets DATABASE_URL; older Vercel Postgres setups
// used POSTGRES_URL. Support both. If neither is set (a local run without a
// database attached), `sql` is null and callers degrade to an empty result
// rather than crashing — which is what you want on a page whose whole job is
// to show you what is stored.
const connectionString = process.env.DATABASE_URL || process.env.POSTGRES_URL;

export const sql = connectionString ? neon(connectionString) : null;
