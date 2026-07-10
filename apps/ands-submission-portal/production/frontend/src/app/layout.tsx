import type { ReactNode } from "react";

export const metadata = {
  title: "ANDS Submission Portal",
  description: "Proxied to the original monolith on Railway",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
