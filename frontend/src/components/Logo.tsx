import { useState, type ReactNode } from "react";

/* Brand mark. Prefers the official raster logo at /orient-logo.png if present (drop the
   provided artwork there), and falls back to the bundled vector /orient-logo.svg so the
   app always renders a logo. Kept dependency-free and accessible. */

const PRIMARY = "/orient-logo.png";
const FALLBACK = "/orient-logo.svg";

export function Logo({
  size = 34,
  title = "Orient",
}: {
  size?: number;
  title?: string;
}): ReactNode {
  const [src, setSrc] = useState(PRIMARY);
  return (
    <img
      src={src}
      width={size}
      height={size}
      alt={`${title} logo`}
      className="brand-logo"
      decoding="async"
      onError={() => {
        if (src !== FALLBACK) setSrc(FALLBACK);
      }}
      style={{ width: size, height: size, objectFit: "contain", display: "block" }}
    />
  );
}
