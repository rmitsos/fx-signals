import { NextResponse } from "next/server";
import { runSignalUpdate } from "@/lib/fx/signals";
import { sendChangeEmail } from "@/lib/fx/email";

export const maxDuration = 60;

// Triggered by Vercel Cron (see vercel.json), daily after the New York close.
// When CRON_SECRET is set only Vercel's scheduler can call this; without it
// the endpoint is open, which is fine while you are setting things up and
// want to trigger the first run by hand.
//
// proxy.js deliberately does not gate /api/* — Vercel's scheduler carries no
// cookie, so the cron would never fire. This route guards itself instead.
//
// It computes and stores signals, and emails only when at least one
// instrument's position actually changed -- a few times a year across 22
// instruments, not a daily digest. It places no orders and holds no broker
// credentials — there is nothing here that can move money.
export async function GET(request) {
  const secret = process.env.CRON_SECRET;
  if (secret) {
    const auth = request.headers.get("authorization");
    if (auth !== `Bearer ${secret}`) {
      return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
    }
  }

  const result = await runSignalUpdate();

  let email = { sent: false, reason: "no changes" };
  if (result.changes.length > 0 && result.portfolio) {
    try {
      email = await sendChangeEmail({ changes: result.changes, asof: result.portfolio.asof });
    } catch (err) {
      email = { sent: false, reason: err?.message || String(err) };
    }
  }

  return NextResponse.json(
    { ...result, changes: result.changes.length, email },
    { status: result.ok ? 200 : 500 }
  );
}
