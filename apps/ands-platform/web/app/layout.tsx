import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "File an ANDS — guided drug submission to Health Canada",
  description:
    "A guided, story-driven, spatial way to file an Abbreviated New Drug " +
    "Submission to Health Canada — even if you've never done it before.",
};

export const viewport: Viewport = {
  themeColor: "#0b1220",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
