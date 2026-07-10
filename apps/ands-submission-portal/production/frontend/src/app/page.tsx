import Link from "next/link";

/** Vercel proxies all routes to the Railway monolith (see vercel.json). */
export default function HomePage() {
  return (
    <div className="card" style={{ margin: "2rem auto", maxWidth: 640 }}>
      <h1>ANDS Submission Portal</h1>
      <p>
        This Vercel project proxies to the original application on Railway —
        the full workspace with guided submission, validation, transmission, and
        lifecycle screens from <code>server.py</code>.
      </p>
      <p>
        <Link href="/">Open the full portal</Link> ·{" "}
        <Link href="/submit">Guided submission</Link> ·{" "}
        <Link href="/dashboard">Dashboard</Link>
      </p>
      <p className="muted">
        Direct API host:{" "}
        <a href="https://ands-submission-portal-production.up.railway.app">
          ands-submission-portal-production.up.railway.app
        </a>
      </p>
    </div>
  );
}
