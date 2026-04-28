import "./globals.css";
import Script from "next/script";
import { Providers } from "@/components/providers";

export const metadata = {
  title: "On-chain RCA Workbench",
  description: "Internal RCA workbench"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <Script id="wallet-extension-error-filter" strategy="beforeInteractive">
          {`
            (function () {
              function isWalletEthereumRedefinition(message, source) {
                return String(message || "").includes("Cannot redefine property: ethereum") &&
                  String(source || "").includes("chrome-extension://");
              }

              window.addEventListener("error", function (event) {
                var source = [event.filename, event.error && event.error.stack].filter(Boolean).join("\\n");
                var message = event.message || (event.error && event.error.message);
                if (isWalletEthereumRedefinition(message, source)) {
                  event.preventDefault();
                  event.stopImmediatePropagation();
                  return true;
                }
              }, true);

              window.addEventListener("unhandledrejection", function (event) {
                var reason = event.reason || {};
                var message = reason.message || String(reason);
                var source = reason.stack || "";
                if (isWalletEthereumRedefinition(message, source)) {
                  event.preventDefault();
                  event.stopImmediatePropagation();
                  return true;
                }
              }, true);
            })();
          `}
        </Script>
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
