"use client";
import { useState, useEffect, useMemo } from "react";

const API = process.env.NEXT_PUBLIC_API || "http://127.0.0.1:8000";

const SHOP_ICON = {
  sumashtech: "/shops/sumashtech.png", rio: "/shops/rio.png",
  kry: "/shops/kry.ico", dazzle: "/shops/dazzle.ico",
};
const SHOP_COLORS = { sumashtech: "#5b5bf6", rio: "#07b07a", kry: "#f3651e", dazzle: "#e0387b" };

function taka(n) { return n == null ? "—" : "৳" + Number(n).toLocaleString("en-BD"); }

// Dazzle bakes a "dazzle Care+" sticker into its images — never display those.
const PLACEHOLDER = "/placeholder.svg";
const cleanImg = (u) => (u && !/dazzle\.sgp1|api\.dazzle\.com\.bd\/storage/i.test(u) ? u : null);

// strip leaked attribute markers (sim/network, ram & storage, region…) from a colour
function cleanColor(c) {
  if (!c) return c;
  return c.replace(/\s+(ram\s*&\s*storage|sim\s*&?\s*\/?\s*network|region|version|warranty)\b.*$/i, "").trim() || c;
}

// ---- spec helpers ----
function findSpec(specs, group, nameIncludes) {
  for (const [g, rows] of Object.entries(specs || {})) {
    if (group && !g.toLowerCase().includes(group.toLowerCase())) continue;
    for (const r of Array.isArray(rows) ? rows : [])
      if ((r.name || "").toLowerCase().includes(nameIncludes.toLowerCase())) return r.value;
  }
  return null;
}
function rx(v, re) { const m = v && v.match(re); return m ? m[1] : null; }
function keySpecs(specs) {
  if (!specs) return [];
  const out = [];
  const d = rx(findSpec(specs, "Display", "Size"), /([\d.]+)\s*inch/i); if (d) out.push(["🖥️", "Display", `${d}″`]);
  const chip = findSpec(specs, "Platform", "Chipset"); if (chip) out.push(["⚙️", "Chipset", chip.split("(")[0].replace(/qualcomm|mediatek/i, "").trim().slice(0, 16)]);
  const ram = rx(findSpec(specs, "Memory", "Internal"), /(\d+)\s*GB\s*RAM/i); if (ram) out.push(["💾", "RAM", `${ram}GB`]);
  const mp = rx(findSpec(specs, "Main Camera", "") || findSpec(specs, "Camera", ""), /(\d+)\s*MP/i); if (mp) out.push(["📷", "Camera", `${mp}MP`]);
  const mah = rx(findSpec(specs, "Battery", "Type") || findSpec(specs, "Battery", "Capacity"), /([\d,]+)\s*mAh/i); if (mah) out.push(["🔋", "Battery", `${mah}mAh`]);
  return out;
}

const sKey = (o) => (o.ram_gb && o.rom_gb ? `${o.ram_gb}/${o.rom_gb}` : o.rom_gb ? `${o.rom_gb}` : "std");
const sLabel = (o) => (o.ram_gb && o.rom_gb ? `${o.ram_gb}/${o.rom_gb}GB` : o.rom_gb ? `${o.rom_gb}GB` : "Standard");
const isOfficial = (o) => /official/i.test(o.warranty || "");

export default function ProductPage({ params }) {
  const { slug } = params;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selStorage, setSelStorage] = useState(null);
  const [selColor, setSelColor] = useState(null);
  const [selVersion, setSelVersion] = useState("all");

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/api/products/${slug}`);
        const d = await r.json();
        setData(d);
        const priced = (d.offers || []).filter((o) => o.price != null).sort((a, b) => a.price - b.price);
        if (priced[0]) setSelStorage(sKey(priced[0]));
        else if (d.offers?.[0]) setSelStorage(sKey(d.offers[0]));
      } catch { setData(null); }
      setLoading(false);
    })();
  }, [slug]);

  const product = data?.product;
  const offers = data?.offers || [];

  // colours: prefer rich spec.colors (with images), else derive from offers
  const colors = useMemo(() => {
    const raw = Array.isArray(product?.spec?.colors) && product.spec.colors.length
      ? product.spec.colors
      : offers.filter((o) => o.color).map((o) => ({ name: o.color, image: null }));
    const by = new Map();
    for (const c of raw) {
      const name = cleanColor(c.name);
      if (!name) continue;
      const key = name.toLowerCase();
      const img = cleanImg(c.image);
      if (!by.has(key)) by.set(key, { name, image: img });
      else if (!by.get(key).image && img) by.get(key).image = img;
    }
    return [...by.values()];
  }, [product, offers]);

  const storages = useMemo(() => {
    const m = new Map();
    for (const o of offers) if (!m.has(sKey(o))) m.set(sKey(o), { key: sKey(o), label: sLabel(o), rom: o.rom_gb || 0 });
    return [...m.values()].sort((a, b) => a.rom - b.rom);
  }, [offers]);

  const hasVersions = useMemo(() => {
    let off = false, un = false;
    for (const o of offers) { if (o.warranty) (isOfficial(o) ? (off = true) : (un = true)); }
    return off && un;
  }, [offers]);

  const matched = useMemo(() => {
    const m = {};
    for (const o of offers) {
      if (sKey(o) !== selStorage) continue;
      if (selVersion === "official" && !isOfficial(o)) continue;
      if (selVersion === "unofficial" && isOfficial(o)) continue;
      const k = o.source;
      if (o.price == null && m[k]) continue;
      if (!m[k] || (o.price != null && (m[k].price == null || o.price < m[k].price))) m[k] = o;
    }
    return Object.values(m).sort((a, b) => (a.price ?? 1e15) - (b.price ?? 1e15));
  }, [offers, selStorage, selVersion]);

  if (loading)
    return <div className="wrap"><div className="sk" style={{ height: 320, borderRadius: 22, marginBottom: 22 }} /></div>;
  if (!product)
    return <div className="wrap empty"><div className="big">🤷</div>Product not found. <a href="/" style={{ color: "var(--brand)" }}>← Back</a></div>;

  const specs = product.spec?.specs || null;
  const ks = keySpecs(specs);
  const selColorObj = colors.find((c) => c.name === selColor);
  const firstColorImg = colors.find((c) => c.image)?.image;
  const mainImg = selColorObj?.image || cleanImg(product.image_url) || firstColorImg || PLACEHOLDER;
  const prices = matched.map((o) => o.price).filter((p) => p != null);
  const low = prices.length ? Math.min(...prices) : null;
  const best = matched.find((o) => o.price === low);
  const spread = prices.length > 1 ? Math.max(...prices) - Math.min(...prices) : 0;

  return (
    <div className="wrap">
      <div className="crumb">
        <a href="/">Home</a> <span>›</span> <span>{product.brand}</span> <span>›</span>
        <span style={{ color: "var(--ink-soft)" }}>{product.model_name}</span>
      </div>

      <div className="pdp">
        {/* gallery */}
        <div className="gallery">
          <div className="gallery-main">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={mainImg} alt={product.model_name} />
          </div>
          {colors.filter((c) => c.image).length > 1 && (
            <div className="gallery-thumbs">
              {colors.filter((c) => c.image).map((c) => (
                <button key={c.name} title={c.name}
                  className={`thumb-btn ${selColor === c.name ? "on" : ""}`}
                  onClick={() => setSelColor(c.name)}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={c.image} alt={c.name} />
                </button>
              ))}
            </div>
          )}
        </div>

        {/* info + selectors */}
        <div className="pdp-info">
          <div className="brand">{product.brand}</div>
          <h1>{product.model_name}</h1>
          {ks.length > 0 && (
            <div className="kspec">
              {ks.map(([icon, label, val]) => (
                <div className="kspec-item" key={label}>
                  <span className="kspec-ic">{icon}</span><span className="kspec-v">{val}</span><span className="kspec-l">{label}</span>
                </div>
              ))}
            </div>
          )}

          <div className="price-hero">
            <div>
              <span className="ph-lab">Best price{selColor ? ` · ${selColor}` : ""} · {storages.find((s) => s.key === selStorage)?.label}</span>
              <span className="ph-val">{taka(low)}</span>
              {best && <span className="ph-shop">at {best.source_name}{spread > 0 ? ` · save up to ${taka(spread)}` : ""}</span>}
            </div>
            {best && <a className="bd-cta" href={best.url} target="_blank" rel="noreferrer">View deal ↗</a>}
          </div>

          {colors.length > 0 && (
            <div className="sel-block">
              <div className="sel-label">Color: <b>{selColor || colors[0]?.name || "—"}</b></div>
              <div className="swatches">
                {colors.map((c) => (
                  <button key={c.name} title={c.name}
                    className={`swatch ${(selColor || colors[0]?.name) === c.name ? "on" : ""}`}
                    onClick={() => setSelColor(c.name)}>
                    {c.image
                      ? // eslint-disable-next-line @next/next/no-img-element
                        <img className="swatch-img" src={c.image} alt={c.name} />
                      : <span className="swatch-dot" style={{ background: "#b7bccb" }} />}
                    <span className="swatch-lbl">{c.name}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="sel-block">
            <div className="sel-label">RAM &amp; Storage</div>
            <div className="config-pills">
              {storages.map((s) => (
                <button key={s.key} className={`config-pill ${selStorage === s.key ? "on" : ""}`}
                  onClick={() => setSelStorage(s.key)}>{s.label}</button>
              ))}
            </div>
          </div>

          {hasVersions && (
            <div className="sel-block">
              <div className="sel-label">Version / Region</div>
              <div className="config-pills">
                {["all", "official", "unofficial"].map((v) => (
                  <button key={v} className={`config-pill ${selVersion === v ? "on" : ""}`}
                    onClick={() => setSelVersion(v)}>{v[0].toUpperCase() + v.slice(1)}</button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* comparison */}
      <div className="sec-head">
        <h2>Price comparison</h2>
        <span className="count">{matched.length} {matched.length === 1 ? "shop" : "shops"}</span>
      </div>
      <div className="offers">
        {matched.length === 0 && <div className="empty" style={{ padding: 30 }}>No shop offers this configuration.</div>}
        {matched.map((o, i) => {
          const isBest = o.price != null && o.price === low && matched.length > 1;
          return (
            <div key={i} className={`offer ${isBest ? "best" : ""}`} style={{ animationDelay: `${i * 28}ms` }}>
              <div className="left">
                {SHOP_ICON[o.source]
                  ? // eslint-disable-next-line @next/next/no-img-element
                    <img className="offer-shopicon" src={SHOP_ICON[o.source]} alt={o.source_name} />
                  : <div className="avatar" style={{ background: SHOP_COLORS[o.source] || "#5b5bf6" }}>{(o.source_name || "?")[0]}</div>}
                <div style={{ minWidth: 0 }}>
                  <div className="shop">{o.source_name}</div>
                  <div className="sub">
                    {o.color && <span className="tag">{cleanColor(o.color)}</span>}
                    {o.warranty && <span className="tag warr">🛡 {o.warranty}</span>}
                    <span className="tag" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <span className={`dot ${o.in_stock == null ? "unknown" : o.in_stock ? "in" : "out"}`} />
                      {o.in_stock == null ? "Check availability" : o.in_stock ? "In stock" : "Out of stock"}
                    </span>
                  </div>
                </div>
              </div>
              <div className="right">
                <div className="amt-wrap">
                  {isBest && <span className="ribbon">Best price</span>}
                  <div className="amt">{taka(o.price)}</div>
                </div>
                <a className="visit" href={o.url} target="_blank" rel="noreferrer">Visit ↗</a>
              </div>
            </div>
          );
        })}
      </div>

      {specs && Object.keys(specs).length > 0 && (
        <>
          <div className="sec-head"><h2>Full specifications</h2></div>
          <div className="specs">
            {Object.entries(specs).map(([group, rows]) => (
              <div className="spec-group" key={group}>
                <div className="spec-group-title">{group}</div>
                <div className="spec-rows">
                  {(Array.isArray(rows) ? rows : []).map((r, j) => (
                    <div className="spec-row" key={j}><span className="spec-k">{r.name}</span><span className="spec-v">{r.value}</span></div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
