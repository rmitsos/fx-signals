import { NextResponse } from "next/server";

// Access gate.
//
// A private GitHub repo does NOT make a Vercel deployment private — the
// project gets a public *.vercel.app URL that anyone who learns it can read.
// Since this site shows your open positions, that is the one thing it must
// not do. So: nothing is served without a shared secret.
//
// In Next 16 this file is `proxy.js`, not `middleware.js` — the middleware
// convention is deprecated and renamed.
//
// This is a shared secret in a URL, not an authentication system. It keeps
// the page out of the hands of anyone who stumbles across the hostname. If
// this ever holds broker credentials, replace it with real auth.

const COOKIE = "fx_access";
const YEAR = 60 * 60 * 24 * 365;

export function proxy(request) {
  const { pathname, searchParams } = request.nextUrl;

  // The cron endpoint authenticates itself with CRON_SECRET and is called by
  // Vercel's scheduler, which carries no cookie.
  if (pathname.startsWith("/api/")) return NextResponse.next();

  const token = process.env.FX_ACCESS_TOKEN;

  // Fail closed. An unset secret must not mean "open to everyone" — that is
  // the failure mode this gate exists to prevent, and it would be silent.
  if (!token) {
    return new NextResponse(
      "FX_ACCESS_TOKEN is not set. Set it in the project's environment variables, " +
        "then open the site with ?k=<token> once.",
      { status: 503, headers: { "content-type": "text/plain" } }
    );
  }

  if (request.cookies.get(COOKIE)?.value === token) {
    return NextResponse.next();
  }

  // ?k=<token> once, then it lives in an httpOnly cookie so the secret stops
  // appearing in the address bar, browser history and any referrer header.
  if (searchParams.get("k") === token) {
    const clean = new URL(request.nextUrl);
    clean.searchParams.delete("k");
    const res = NextResponse.redirect(clean);
    res.cookies.set(COOKIE, token, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      maxAge: YEAR,
      path: "/",
    });
    return res;
  }

  // 404 rather than 401: no reason to confirm to a stranger that anything is
  // here at all.
  return new NextResponse("Not found", {
    status: 404,
    headers: { "content-type": "text/plain" },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
