"use client";
import { useState, useEffect, useRef, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API || "http://127.0.0.1:8000";
const PAGE = 24;

const SHOP_ICON = {
  sumashtech: "/shops/sumashtech.png", rio: "/shops/rio.png",
  kry: "/shops/kry.ico", dazzle: "/shops/dazzle.svg",
};
const SHOP_NAME = {
  sumashtech: "Sumash Tech", rio: "Rio International", kry: "KRY International", dazzle: "Dazzle",
};
const PLACEHOLDER = "/placeholder.svg";
const cleanImg = (u) => (u && !/dazzle\.sgp1|api\.dazzle\.com\.bd\/storage/i.test(u) ? u : null);

const taka = (n) => (n == null ? "—" : "৳" + Number(n).toLocaleString("en-BD"));
const romLabel = (n) => (n >= 1024 ? `${n / 1024}TB` : `${n}GB`);

const EMPTY_FILTERS = { in_stock: false, price: null, ram: [], rom: [], network: "", display: [] };

function SearchIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
    </svg>
  );
}

// --- dual-range price slider with editable min/max inputs ---
// Keeps its own state while dragging (commits on release) so the page grid
// doesn't re-render on every tick -> smooth.
function PriceFilter({ min, max, applied, onApply }) {
  const [lo, setLo] = useState(applied[0]);
  const [hi, setHi] = useState(applied[1]);
  useEffect(() => { setLo(applied[0]); setHi(applied[1]); }, [applied[0], applied[1]]);

  const step = max > 100000 ? 500 : 100;
  const pct = (v) => ((v - min) / (max - min || 1)) * 100;
  const commit = () => onApply([Math.max(min, Math.min(lo, hi)), Math.min(max, Math.max(hi, lo))]);

  return (
    <>
      <div className="pslider">
        <div className="pslider-track" />
        <div className="pslider-fill" style={{ left: `${pct(lo)}%`, right: `${100 - pct(hi)}%` }} />
        <input type="range" min={min} max={max} step={step} value={lo}
          onChange={(e) => setLo(Math.min(+e.target.value, hi))} onMouseUp={commit} onTouchEnd={commit} />
        <input type="range" min={min} max={max} step={step} value={hi}
          onChange={(e) => setHi(Math.max(+e.target.value, lo))} onMouseUp={commit} onTouchEnd={commit} />
      </div>
      <div className="prange-inputs">
        <input type="number" className="pnum" value={lo} min={min} max={max}
          onChange={(e) => setLo(Math.min(+e.target.value || 0, hi))}
          onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
        <span className="prange-dash">–</span>
        <input type="number" className="pnum" value={hi} min={min} max={max}
          onChange={(e) => setHi(Math.max(+e.target.value || 0, lo))}
          onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
      </div>
    </>
  );
}

function CheckRow({ checked, onClick, label }) {
  return (
    <button className={`fcheck ${checked ? "on" : ""}`} onClick={onClick}>
      <span className="fbox">{checked && "✓"}</span><span>{label}</span>
    </button>
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

  const [facets, setFacets] = useState(null);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [drawer, setDrawer] = useState(false);

  const buildQS = useCallback((query, br, sortBy, f, offset) => {
    const p = new URLSearchParams({ q: query, brand: br, sort: sortBy, limit: PAGE, offset });
    if (f.in_stock) p.set("in_stock", "1");
    if (f.price) { p.set("price_min", f.price[0]); p.set("price_max", f.price[1]); }
    if (f.ram.length) p.set("ram", f.ram.join(","));
    if (f.rom.length) p.set("rom", f.rom.join(","));
    if (f.network) p.set("network", f.network);
    if (f.display.length) p.set("display", f.display.join(","));
    return p.toString();
  }, []);

  const search = useCallback(async (query, br, sortBy, f) => {
    setLoading(true); setActiveQ(query); setShowSug(false);
    try {
      const r = await fetch(`${API}/api/search?${buildQS(query, br, sortBy, f, 0)}`);
      const d = await r.json();
      setResults(d.results || []); setTotal(d.total || 0);
    } catch { setResults([]); setTotal(0); }
    setLoading(false);
  }, [buildQS]);

  useEffect(() => {
    fetch(`${API}/api/brands`).then((r) => r.json()).then((d) => setBrands(d.brands || [])).catch(() => {});
    fetch(`${API}/api/facets`).then((r) => r.json()).then((d) => {
      setFacets(d);
      const init = { ...EMPTY_FILTERS, price: [d.price.min, d.price.max] };
      setFilters(init);
      search("", "", "relevant", init);
    }).catch(() => search("", "", "relevant", EMPTY_FILTERS));
  }, [search]);

  // autocomplete
  useEffect(() => {
    if (q.trim().length < 2) { setSuggest([]); return; }
    const t = setTimeout(async () => {
      try { const d = await (await fetch(`${API}/api/suggest?q=${encodeURIComponent(q)}`)).json(); setSuggest(d.suggestions || []); }
      catch { setSuggest([]); }
    }, 180);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const h = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setShowSug(false); };
    document.addEventListener("mousedown", h); return () => document.removeEventListener("mousedown", h);
  }, []);

  async function loadMore() {
    setMore(true);
    try {
      const d = await (await fetch(`${API}/api/search?${buildQS(activeQ, brand, sort, filters, results.length)}`)).json();
      setResults((p) => [...p, ...(d.results || [])]);
    } catch {}
    setMore(false);
  }

  // apply filter change immediately
  function setF(next) { const nf = { ...filters, ...next }; setFilters(nf); search(activeQ, brand, sort, nf); }
  function toggleArr(key, val) { const a = filters[key]; setF({ [key]: a.includes(val) ? a.filter((x) => x !== val) : [...a, val] }); }
  function pickBrand(slug) { setBrand(slug); search(activeQ, slug, sort, filters); }
  function onSort(e) { setSort(e.target.value); search(activeQ, brand, e.target.value, filters); }

  const activeCount =
    (filters.in_stock ? 1 : 0) + filters.ram.length + filters.rom.length +
    filters.display.length + (filters.network ? 1 : 0) +
    (facets && filters.price && (filters.price[0] > facets.price.min || filters.price[1] < facets.price.max) ? 1 : 0);

  function resetFilters() {
    const nf = { ...EMPTY_FILTERS, price: facets ? [facets.price.min, facets.price.max] : null };
    setFilters(nf); search(activeQ, brand, sort, nf);
  }

  const sidebar = (
    <aside className="filters">
      <div className="filters-head">
        <h3>Filters</h3>
        {activeCount > 0 && <button className="freset" onClick={resetFilters}>Clear ({activeCount})</button>}
      </div>

      <div className="fgroup">
        <div className="flabel">Availability</div>
        <CheckRow checked={filters.in_stock} onClick={() => setF({ in_stock: !filters.in_stock })} label="In stock only" />
      </div>

      {facets && filters.price && (
        <div className="fgroup">
          <div className="flabel">Price range</div>
          <PriceFilter min={facets.price.min} max={facets.price.max} applied={filters.price}
            onApply={(v) => setF({ price: v })} />
        </div>
      )}

      <div className="fgroup">
        <div className="flabel">Network</div>
        {["5G", "4G"].map((n) => (
          <CheckRow key={n} checked={filters.network === n.toLowerCase()}
            onClick={() => setF({ network: filters.network === n.toLowerCase() ? "" : n.toLowerCase() })} label={n} />
        ))}
      </div>

      {facets?.display?.length > 0 && (
        <div className="fgroup">
          <div className="flabel">Display type</div>
          {facets.display.map((d) => (
            <CheckRow key={d} checked={filters.display.includes(d.toLowerCase())}
              onClick={() => toggleArr("display", d.toLowerCase())} label={d} />
          ))}
        </div>
      )}

      {facets && (
        <div className="fgroup">
          <div className="flabel">RAM</div>
          <div className="fpills">
            {facets.ram.filter((r) => r >= 3).map((r) => (
              <button key={r} className={`fpill ${filters.ram.includes(r) ? "on" : ""}`} onClick={() => toggleArr("ram", r)}>{r}GB</button>
            ))}
          </div>
        </div>
      )}

      {facets && (
        <div className="fgroup">
          <div className="flabel">Internal storage</div>
          <div className="fpills">
            {facets.rom.filter((r) => r >= 32).map((r) => (
              <button key={r} className={`fpill ${filters.rom.includes(r) ? "on" : ""}`} onClick={() => toggleArr("rom", r)}>{romLabel(r)}</button>
            ))}
          </div>
        </div>
      )}
    </aside>
  );

  return (
    <>
      <section className="hero">
        <h1>Compare phone prices<br /><span className="grad">across Bangladesh</span></h1>
        <p>See prices, warranty and stock from multiple online shops — side by side, in one click.</p>
        <div className="searchwrap" ref={boxRef}>
          <form className="searchbar" onSubmit={(e) => { e.preventDefault(); search(q, brand, sort, filters); }}>
            <SearchIcon />
            <input value={q} onChange={(e) => { setQ(e.target.value); setShowSug(true); }} onFocus={() => setShowSug(true)}
              placeholder="Search for a phone… e.g. Galaxy S25 Ultra, iPhone 17" />
            <button className="btn" type="submit">Search</button>
          </form>
          {showSug && suggest.length > 0 && (
            <div className="suggest">
              {suggest.map((s) => (
                <a key={s.slug} href={`/product/${s.slug}`} className="suggest-item">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={cleanImg(s.image_url) || PLACEHOLDER} alt="" />
                  <span className="s-name">{s.model_name}</span><span className="s-brand">{s.brand}</span>
                </a>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="wrap">
        <div className="brandbar">
          <button className={`brand-chip ${brand === "" ? "on" : ""}`} onClick={() => pickBrand("")}>All brands</button>
          {brands.map((b) => (
            <button key={b.slug} className={`brand-chip ${brand === b.slug ? "on" : ""}`} onClick={() => pickBrand(b.slug)}>
              {b.name} <span className="bc-n">{b.n}</span>
            </button>
          ))}
        </div>

        <div className="results-layout">
          <div className="sidebar-desktop">{sidebar}</div>

          <div className="results-main">
            <div className="sec-head">
              <h2>{activeQ ? `Results for “${activeQ}”` : brand ? `${brands.find((b) => b.slug === brand)?.name || ""} phones` : "All phones"}</h2>
              <div className="sec-tools">
                <button className="filters-btn" onClick={() => setDrawer(true)}>⚙ Filters{activeCount > 0 ? ` (${activeCount})` : ""}</button>
                {!loading && <span className="count">{total.toLocaleString("en-US")} phones</span>}
                <select className="sortsel" value={sort} onChange={onSort}>
                  <option value="relevant">Sort: Relevant</option>
                  <option value="low">Price: Low to High</option>
                  <option value="high">Price: High to Low</option>
                  <option value="shops">Most shops</option>
                </select>
              </div>
            </div>

            {loading ? (
              <div className="grid">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="sk sk-card" />)}</div>
            ) : results.length === 0 ? (
              <div className="empty"><div className="big">🔍</div><div>No phones match these filters. Try clearing some.</div></div>
            ) : (
              <>
                <div className="grid">
                  {results.map((p, i) => (
                    <a key={p.slug} href={`/product/${p.slug}`} className="card" style={{ animationDelay: `${Math.min((i % PAGE) * 20, 240)}ms` }}>
                      <div className="thumb">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={cleanImg(p.image_url) || PLACEHOLDER} alt={p.model_name} loading="lazy" />
                      </div>
                      <div className="brand">{p.brand}</div>
                      <div className="name">{p.model_name}</div>
                      <div className="foot">
                        <div>
                          {p.min_price == null ? <span className="price na">Price unavailable</span> : (
                            <span className="price">{p.min_price !== p.max_price && <span className="from">from</span>}{taka(p.min_price)}</span>
                          )}
                        </div>
                        <div className="shopicons" title={(p.sources || []).map((s) => SHOP_NAME[s] || s).join(", ")}>
                          {(p.sources || []).map((s) => SHOP_ICON[s] ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img key={s} src={SHOP_ICON[s]} alt={SHOP_NAME[s] || s} className="shopicon" />
                          ) : null)}
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
        </div>
      </div>

      {/* mobile drawer */}
      {drawer && (
        <div className="drawer-overlay" onClick={() => setDrawer(false)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-top"><span>Filters</span><button onClick={() => setDrawer(false)}>✕</button></div>
            {sidebar}
            <button className="drawer-apply" onClick={() => setDrawer(false)}>Show {total.toLocaleString("en-US")} phones</button>
          </div>
        </div>
      )}
    </>
  );
}
