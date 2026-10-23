import { useMemo, type ReactNode } from "react";

import { encodeQr, qrToSvg } from "../lib/qrcode";

/* Renders a scannable QR code for any text/URL as an inline SVG (crisp at any size, prints
   well). The QR is generated entirely client-side from the given value — no network call,
   no external service, so the candidate apply link never leaves the browser. */
export function QrCode({
  value,
  size = 160,
  title = "QR code",
}: {
  value: string;
  size?: number;
  title?: string;
}): ReactNode {
  const svg = useMemo(() => {
    try {
      return qrToSvg(encodeQr(value));
    } catch {
      return null;
    }
  }, [value]);

  if (!svg) {
    return (
      <div className="qr-box qr-box--error" style={{ width: size, height: size }} role="img" aria-label="QR unavailable">
        <span className="subtle">QR unavailable</span>
      </div>
    );
  }

  const dataUri = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  return (
    <img
      className="qr-box"
      src={dataUri}
      width={size}
      height={size}
      alt={`${title} — scan to open the link`}
      style={{ width: size, height: size }}
    />
  );
}

/** The SVG data URI for a value, handy for a download link. Returns null if encoding fails. */
export function qrDataUri(value: string): string | null {
  try {
    return `data:image/svg+xml;utf8,${encodeURIComponent(qrToSvg(encodeQr(value)))}`;
  } catch {
    return null;
  }
}
