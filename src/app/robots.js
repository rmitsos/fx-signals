// Nothing here is ever meant to be indexed. This is not a site that becomes
// public later — it shows open positions, so refuse every crawler outright
// and advertise no sitemap.
export default function robots() {
  return {
    rules: { userAgent: "*", disallow: "/" },
  };
}
