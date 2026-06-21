"use client";
import { useState, useEffect, useRef, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API || "http://127.0.0.1:8000";
const PAGE = 24;

const SHOP_ICON = {
  sumashtech: "/shops/sumashtech.png",
  rio: "/shops/rio.png",
  kry: "/shops/kry.ico",
  dazzle: "/shops/dazzle.ico",
};
const SHOP_NAME = {
  sumashtech: "Sumash Tech", rio: "Rio International", kry: "KRY International", dazzle: "Dazzle",
};

// Dazzle bakes a "dazzle Care+" sticker into its images — never display those.
const PLACEHOLDER = "/placeholder.svg";
const cleanImg = (u) => (u && !/dazzle\.sgp1|api\.dazzle\.com\.bd\/storage/i.test(u) ? u : null);

function taka(n) {
  return n == null ? "—" : "৳" + Number(n).toLocaleString("en-BD");
}

function SearchIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

export default function Home() {
  const [q, setQ] = useState("");
  const [activeQ, setActiveQ] = useState("");
  const [brand, setBrand] = useState("");
  const [sort, setSort] = useState("relevant");
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);

  const [brands, setBrands] = useState([]);
  const [suggest, setSuggest] = useState([]);
  const [showSug, setShowSug] = useState(false);
  const boxRef = useRef(null);

  // ---- data fetching ----
  const fetchPage = useCallback(async (query, br, sortBy, offset) => {
    const r = await fetch(
      `${API}/api/search?q=${encodeURIComponent(query)}&brand=${br}&sort=${sortBy}&limit=${PAGE}&offset=${offset}`
    );
    return r.json();
  }, []);

  const search = useCallback(async (query, br, sortBy) => {
    setLoading(true);
    setActiveQ(query);
    setShowSug(false);
    try {
      const d = await fetchPage(query, br, sortBy, 0);
      setResults(d.results || []);
      setTotal(d.total || 0);
    } catch {
      setResults([]); setTotal(0);
    }
    setLoading(false);
  }, [fetchPage]);

  useEffect(() => {
    search("", "", "relevant");
    fetch(`${API}/api/brands`).then((r) => r.json()).then((d) => setBrands(d.brands || [])).catch(() => {});
  }, [search]);

  // ---- autocomplete (debounced) ----
  useEffect(() => {
    if (q.trim().length < 2) { setSuggest([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/api/suggest?q=${encodeURIComponent(q)}`);
        const d = await r.json();
        setSuggest(d.suggestions || []);
      } catch { setSuggest([]); }
    }, 180);
    return () => clearTimeout(t);
  }, [q]);

  // close suggestions on outside click
  useEffect(() => {
    function onClick(e) { if (boxRef.current && !boxRef.current.contains(e.target)) setShowSug(false); }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  async function loadMore() {
    setMore(true);
    try {
      const d = await fetchPage(activeQ, brand, sort, results.length);
      setResults((prev) => [...prev, ...(d.results || [])]);
    } catch {}
    setMore(false);
  }

  function pickBrand(slug) { setBrand(slug); search(activeQ, slug, sort); }
  function onSort(e) { const s = e.target.value; setSort(s); search(activeQ, brand, s); }

  return (
    <>
      <section className="hero">
        <h1>Compare phone prices<br /><span className="grad">across Bangladesh</span></h1>
        <p>See prices, warranty and stock from multiple online shops — side by side, in one click.</p>

        <div className="searchwrap" ref={boxRef}>
          <form className="searchbar" onSubmit={(e) => { e.preventDefault(); search(q, brand, sort); }}>
            <SearchIcon />
            <input
              value={q}
              onChange={(e) => { setQ(e.target.value); setShowSug(true); }}
              onFocus={() => setShowSug(true)}
              placeholder="Search for a phone… e.g. Galaxy S25 Ultra, iPhone 17"
            />
            <button className="btn" type="submit">Search</button>
          </form>

          {showSug && suggest.length > 0 && (
            <div className="suggest">
              {suggest.map((s) => (
                <a key={s.slug} href={`/product/${s.slug}`} className="suggest-item">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={cleanImg(s.image_url) || PLACEHOLDER} alt="" />
                  <span className="s-name">{s.model_name}</span>
                  <span className="s-brand">{s.brand}</span>
                </a>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="wrap">
        {/* brand filter */}
        <div className="brandbar">
          <button className={`brand-chip ${brand === "" ? "on" : ""}`} onClick={() => pickBrand("")}>
            All brands
          </button>
          {brands.map((b) => (
            <button key={b.slug} className={`brand-chip ${brand === b.slug ? "on" : ""}`} onClick={() => pickBrand(b.slug)}>
              {b.name} <span className="bc-n">{b.n}</span>
            </button>
          ))}
        </div>

        <div className="sec-head">
          <h2>
            {activeQ ? `Results for “${activeQ}”` : brand ? `${brands.find((b) => b.slug === brand)?.name || ""} phones` : "All phones"}
          </h2>
          {!loading && (
            <div className="sec-tools">
              <span className="count">{total.toLocaleString("en-US")} phones</span>
              <select className="sortsel" value={sort} onChange={onSort}>
                <option value="relevant">Sort: Relevant</option>
                <option value="low">Price: Low to High</option>
                <option value="high">Price: High to Low</option>
                <option value="shops">Most shops</option>
              </select>
            </div>
          )}
        </div>

        {loading ? (
          <div className="grid">{Array.from({ length: 8 }).map((_, i) => <div key={i} className="sk sk-card" />)}</div>
        ) : results.length === 0 ? (
          <div className="empty"><div className="big">🔍</div><div>No phones found. Try a different search or brand.</div></div>
        ) : (
          <>
            <div className="grid">
              {results.map((p, i) => (
                <a key={p.slug} href={`/product/${p.slug}`} className="card" style={{ animationDelay: `${Math.min((i % PAGE) * 22, 280)}ms` }}>
                  <div className="thumb">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={cleanImg(p.image_url) || PLACEHOLDER} alt={p.model_name} loading="lazy" />
                  </div>
                  <div className="brand">{p.brand}</div>
                  <div className="name">{p.model_name}</div>
                  <div className="foot">
                    <div>
                      {p.min_price == null ? (
                        <span className="price na">Price unavailable</span>
                      ) : (
                        <span className="price">
                          {p.min_price !== p.max_price && <span className="from">from</span>}
                          {taka(p.min_price)}
                        </span>
                      )}
                    </div>
                    <div className="shopicons" title={(p.sources || []).map((s) => SHOP_NAME[s] || s).join(", ")}>
                      {(p.sources || []).map((s) =>
                        SHOP_ICON[s] ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img key={s} src={SHOP_ICON[s]} alt={SHOP_NAME[s] || s} className="shopicon" />
                        ) : null
                      )}
                    </div>
                  </div>
                </a>
              ))}
            </div>

            {results.length < total && (
              <div className="loadmore-wrap">
                <button className="loadmore" onClick={loadMore} disabled={more}>
                  {more ? "Loading…" : `Load more (${(total - results.length).toLocaleString("en-US")} more)`}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
