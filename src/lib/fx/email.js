// Email on signal changes, via Resend's REST API.
//
// Plain fetch rather than the Resend SDK, to keep this dependency-free like
// the rest of the app. A broken notification must never stop the signals
// themselves from being computed and stored -- that database row is the
// actual record -- so failures here are returned as a value, not thrown.

const RESEND_URL = "https://api.resend.com/emails";

/**
 * @param changes  array of changed rows from runSignalUpdate — each needs
 *                 code, assetClass, target, previousTarget, reason.
 * @param asof     the date these changes were decided.
 */
export async function sendChangeEmail({ changes, asof }) {
  const apiKey = process.env.RESEND_API_KEY;
  const to = process.env.ALERT_EMAIL_TO;
  const from = process.env.ALERT_EMAIL_FROM || "signals@resend.dev";

  if (!apiKey || !to) {
    return { sent: false, reason: "RESEND_API_KEY or ALERT_EMAIL_TO not set" };
  }
  if (!changes || changes.length === 0) {
    return { sent: false, reason: "no changes" };
  }

  const lines = changes.map((c) => {
    const dir = c.target > c.previousTarget ? "LONG" : c.target < c.previousTarget ? "SHORT" : "FLAT";
    return `${c.code} (${c.assetClass}) -> ${dir} ${Math.abs(c.target).toFixed(2)}\n  ${c.reason}`;
  });

  const subject = `Signal change (${changes.length}) — ${asof}`;
  const text = [
    `Changes as of ${asof}:`,
    "",
    ...lines,
    "",
    "This is a paper record, not advice. No order was placed by anything here.",
  ].join("\n");

  const res = await fetch(RESEND_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ from, to, subject, text }),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return { sent: false, reason: `Resend ${res.status}: ${body.slice(0, 200)}` };
  }
  return { sent: true };
}
