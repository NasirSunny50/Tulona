import "./globals.css";

export const metadata = {
  title: "Tulona — Compare Phone Prices in Bangladesh",
  description: "Compare phone prices, warranty and stock across Bangladesh's top online shops — all in one place.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <header className="hdr">
          <div className="hdr-in">
            <a href="/" className="logo">
              <span className="mark">৳</span>
              <span>
                Tulona <span className="tag">· phone price comparison</span>
              </span>
            </a>
            <span className="spacer" />
          </div>
        </header>
        {children}
        <footer className="foot-site">
          Tulona · Compare phone prices across Bangladesh's top online shops
        </footer>
      </body>
    </html>
  );
}
