"use client";

import { useMemo, useState } from "react";
import { Identity } from "@/lib/identity";
import {
  ArrowDownRight,
  ArrowRight,
  Check,
  Headphones,
  Heart,
  Laptop,
  Menu,
  Minus,
  PackageCheck,
  Plus,
  Search,
  ShieldCheck,
  ShoppingBag,
  Smartphone,
  Sparkles,
  Star,
  Truck,
  Watch,
  X,
  Zap,
} from "./icons";

// Voltway catalog. Paul's storefront products are kept (each with its own
// image), plus our two demo phones with distinct stock images — no image is
// reused across two tiles. The YPhone 16 Pro Max is the promo-leak demo focus:
// $1,000 list, its discounts come from the chat flow (not a storefront markdown),
// so compareAt == price and the save pill is hidden.
type Product = {
  id: string;
  brand: string;
  name: string;
  category: "Audio" | "Phones" | "Computing" | "Wearables";
  price: number;
  compareAt: number;
  rating: number;
  reviews: number;
  badge: string;
  stock: number;
  image: string;
};

const PRODUCTS: Product[] = [
  {
    id: "yphone-16-pro-max",
    brand: "YPhone",
    name: "YPhone 16 Pro Max",
    category: "Phones",
    price: 1000,
    compareAt: 1000,
    rating: 4.9,
    reviews: 3120,
    badge: "Featured",
    stock: 9,
    image: "/images/yphone-16-pro-max.jpg",
  },
  {
    id: "bigcell-9-pro",
    brand: "Bigcell",
    name: "Bigcell 9 Pro",
    category: "Phones",
    price: 899,
    compareAt: 1099,
    rating: 4.6,
    reviews: 540,
    badge: "New",
    stock: 14,
    image: "/images/bigcell-9-pro.jpg",
  },
  {
    id: "bose-qc45",
    brand: "Bose",
    name: "QuietComfort 45 Headphones",
    category: "Audio",
    price: 249,
    compareAt: 329,
    rating: 4.8,
    reviews: 1842,
    badge: "Bestseller",
    stock: 12,
    image: "/images/bose-qc45.jpg",
  },
  {
    // Featured in the refund-compliance demo: the seeded order is 2 × $349.99.
    id: "sony-wh1000xm5",
    brand: "Sony",
    name: "WH-1000XM5 Wireless Headphones",
    category: "Audio",
    price: 349.99,
    compareAt: 449.99,
    rating: 4.9,
    reviews: 2374,
    badge: "Hot deal",
    stock: 8,
    image: "/images/sony-wh1000xm5.jpg",
  },
  {
    id: "beats-studio-pro",
    brand: "Beats",
    name: "Studio Pro Wireless Headphones",
    category: "Audio",
    price: 199,
    compareAt: 349,
    rating: 4.7,
    reviews: 965,
    badge: "43% off",
    stock: 19,
    image: "/images/beats-studio-pro.jpg",
  },
  {
    id: "pixel-8a",
    brand: "Google",
    name: "Pixel 8a 128GB Unlocked",
    category: "Phones",
    price: 399,
    compareAt: 499,
    rating: 4.5,
    reviews: 721,
    badge: "Unlocked",
    stock: 11,
    image: "/images/pixel-8a.jpg",
  },
  {
    id: "macbook-air-m2",
    brand: "Apple",
    name: "MacBook Air 13-inch M2",
    category: "Computing",
    price: 849,
    compareAt: 999,
    rating: 4.9,
    reviews: 1389,
    badge: "Low price",
    stock: 7,
    image: "/images/macbook-air-m2.jpg",
  },
  {
    id: "jbl-flip-6",
    brand: "JBL",
    name: "Flip 6 Portable Speaker",
    category: "Audio",
    price: 89,
    compareAt: 129,
    rating: 4.6,
    reviews: 1108,
    badge: "Weekend deal",
    stock: 24,
    image: "/images/jbl-flip-6.jpg",
  },
  {
    id: "galaxy-watch-6",
    brand: "Samsung",
    name: "Galaxy Watch6 40mm",
    category: "Wearables",
    price: 179,
    compareAt: 299,
    rating: 4.5,
    reviews: 684,
    badge: "40% off",
    stock: 16,
    image: "/images/galaxy-watch-6.jpg",
  },
];

const categoryMeta = [
  { name: "All deals", icon: Zap },
  { name: "Audio", icon: Headphones },
  { name: "Phones", icon: Smartphone },
  { name: "Computing", icon: Laptop },
  { name: "Wearables", icon: Watch },
] as const;

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

type CartLine = { product: Product; quantity: number };

function Logo() {
  return (
    <a className="logo" href="#top" aria-label="Voltway home">
      <span className="logo-mark">
        <Zap size={18} fill="currentColor" />
      </span>
      <span>VOLTWAY</span>
    </a>
  );
}

function ProductCard({
  product,
  onAdd,
}: {
  product: Product;
  onAdd: (p: Product) => void;
}) {
  const discount =
    product.compareAt > product.price
      ? Math.round((1 - product.price / product.compareAt) * 100)
      : 0;

  return (
    <article className="product-card">
      <div className="product-image-wrap">
        <span className="deal-badge">{product.badge}</span>
        <button
          type="button"
          className="icon-button save-button"
          aria-label={`Save ${product.name}`}
        >
          <Heart size={19} />
        </button>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          className="product-image"
          src={product.image}
          alt={`${product.brand} ${product.name}`}
          loading="lazy"
        />
        <button type="button" className="quick-add" onClick={() => onAdd(product)}>
          <Plus size={18} /> Quick add
        </button>
      </div>
      <div className="product-info">
        <p className="product-brand">{product.brand}</p>
        <h3>{product.name}</h3>
        <div className="rating" aria-label={`${product.rating} out of 5 stars`}>
          <Star size={14} fill="currentColor" /> <strong>{product.rating}</strong>
          <span>({product.reviews.toLocaleString()})</span>
        </div>
        <div className="price-row">
          <span className="price">{money.format(product.price)}</span>
          {discount > 0 && (
            <>
              <span className="compare-price">{money.format(product.compareAt)}</span>
              <span className="save-pill">-{discount}%</span>
            </>
          )}
        </div>
        <p className="stock-note">
          <span /> Only {product.stock} left at this price
        </p>
      </div>
    </article>
  );
}

function CartDrawer({
  cart,
  setCart,
  open,
  onClose,
}: {
  cart: Record<string, CartLine>;
  setCart: React.Dispatch<React.SetStateAction<Record<string, CartLine>>>;
  open: boolean;
  onClose: () => void;
}) {
  const items = Object.values(cart);
  const subtotal = items.reduce(
    (sum, item) => sum + item.product.price * item.quantity,
    0,
  );

  const changeQuantity = (id: string, amount: number) => {
    setCart((current) => {
      const next = { ...current };
      const quantity = next[id].quantity + amount;
      if (quantity <= 0) delete next[id];
      else next[id] = { ...next[id], quantity };
      return next;
    });
  };

  return (
    <>
      <button
        type="button"
        className={`drawer-scrim ${open ? "is-open" : ""}`}
        onClick={onClose}
        aria-label="Close cart"
        tabIndex={open ? 0 : -1}
      />
      <aside className={`cart-drawer ${open ? "is-open" : ""}`} aria-hidden={!open}>
        <div className="drawer-header">
          <div>
            <p className="eyebrow">Your haul</p>
            <h2>
              {items.length
                ? `${items.length} great find${items.length > 1 ? "s" : ""}`
                : "Cart is empty"}
            </h2>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label="Close cart"
          >
            <X size={22} />
          </button>
        </div>
        <div className="cart-items">
          {items.length === 0 ? (
            <div className="empty-cart">
              <ShoppingBag size={38} />
              <p>Your next favorite gadget is waiting.</p>
              <button type="button" className="button button-dark" onClick={onClose}>
                Keep browsing
              </button>
            </div>
          ) : (
            items.map(({ product, quantity }) => (
              <div className="cart-item" key={product.id}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={product.image} alt="" />
                <div className="cart-item-copy">
                  <p>{product.brand}</p>
                  <h3>{product.name}</h3>
                  <strong>{money.format(product.price)}</strong>
                  <div className="quantity">
                    <button
                      type="button"
                      onClick={() => changeQuantity(product.id, -1)}
                      aria-label="Decrease quantity"
                    >
                      <Minus size={14} />
                    </button>
                    <span>{quantity}</span>
                    <button
                      type="button"
                      onClick={() => changeQuantity(product.id, 1)}
                      aria-label="Increase quantity"
                    >
                      <Plus size={14} />
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
        {items.length > 0 && (
          <div className="drawer-footer">
            <div>
              <span>Subtotal</span>
              <strong>{money.format(subtotal)}</strong>
            </div>
            <p>Shipping and taxes calculated at checkout.</p>
            <button type="button" className="button button-lime">
              Checkout <ArrowRight size={18} />
            </button>
          </div>
        )}
      </aside>
    </>
  );
}

export function Storefront({ me }: { me: Identity }) {
  const [activeCategory, setActiveCategory] = useState<string>("All deals");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("featured");
  const [cart, setCart] = useState<Record<string, CartLine>>({});
  const [cartOpen, setCartOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [subscribed, setSubscribed] = useState(false);

  const visibleProducts = useMemo(() => {
    const query = search.trim().toLowerCase();
    let next = PRODUCTS.filter((product) => {
      const inCategory =
        activeCategory === "All deals" || product.category === activeCategory;
      const inSearch =
        !query ||
        `${product.brand} ${product.name} ${product.category}`
          .toLowerCase()
          .includes(query);
      return inCategory && inSearch;
    });
    if (sort === "low") next = [...next].sort((a, b) => a.price - b.price);
    if (sort === "high") next = [...next].sort((a, b) => b.price - a.price);
    if (sort === "discount")
      next = [...next].sort(
        (a, b) => b.compareAt - b.price - (a.compareAt - a.price),
      );
    return next;
  }, [activeCategory, search, sort]);

  const cartCount = Object.values(cart).reduce(
    (sum, item) => sum + item.quantity,
    0,
  );

  const addToCart = (product: Product) => {
    setCart((current) => ({
      ...current,
      [product.id]: {
        product,
        quantity: (current[product.id]?.quantity || 0) + 1,
      },
    }));
    setCartOpen(true);
  };

  const chooseCategory = (category: string) => {
    setActiveCategory(category);
    setMenuOpen(false);
    document.getElementById("deals")?.scrollIntoView({ behavior: "smooth" });
  };

  const submitNewsletter = (event: React.FormEvent) => {
    event.preventDefault();
    if (email.trim()) setSubscribed(true);
  };

  return (
    <div id="top" className="vw">
      <div className="announcement">
        <Sparkles size={14} /> Fresh markdowns just landed <span /> Free 2-day
        delivery over $75
      </div>
      <header className="site-header">
        <div className="nav-shell">
          <button
            type="button"
            className="mobile-menu icon-button"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label="Toggle menu"
          >
            <Menu size={22} />
          </button>
          <Logo />
          <nav className={menuOpen ? "is-open" : ""}>
            <button type="button" onClick={() => chooseCategory("All deals")}>
              Deals
            </button>
            <button type="button" onClick={() => chooseCategory("Audio")}>
              Audio
            </button>
            <button type="button" onClick={() => chooseCategory("Phones")}>
              Phones
            </button>
            <button type="button" onClick={() => chooseCategory("Computing")}>
              Computing
            </button>
            <button type="button" onClick={() => chooseCategory("Wearables")}>
              Wearables
            </button>
            <label className="mobile-nav-search">
              <Search size={17} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search YPhone, Bose, Sony…"
                aria-label="Search products"
              />
            </label>
          </nav>
          <div className="header-tools">
            <label className="header-search">
              <Search size={18} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search deals"
                aria-label="Search products"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  aria-label="Clear search"
                >
                  <X size={15} />
                </button>
              )}
            </label>
            <span className="header-greeting">Hi, {me.name.split(" ")[0]}</span>
            <button
              type="button"
              className="cart-button"
              onClick={() => setCartOpen(true)}
              aria-label={`Open cart with ${cartCount} items`}
            >
              <ShoppingBag size={20} />
              <span className="cart-label">Cart</span>
              {cartCount > 0 && <b>{cartCount}</b>}
            </button>
          </div>
        </div>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-backdrop" />
          <div className="hero-content">
            <p className="eyebrow eyebrow-light">
              <span>Fresh deal drop</span> Small prices. Big energy.
            </p>
            <h1 id="hero-title">
              Tech you want.
              <br />
              <em>Prices you&rsquo;ll love.</em>
            </h1>
            <p className="hero-subtitle">
              Big-brand electronics, open-box steals, and everyday
              essentials&mdash;without the everyday markup.
            </p>
            <div className="hero-actions">
              <button
                type="button"
                className="button button-lime"
                onClick={() => chooseCategory("All deals")}
              >
                Shop today&rsquo;s drops <ArrowDownRight size={19} />
              </button>
              <button
                type="button"
                className="text-link text-link-light"
                onClick={() => chooseCategory("Audio")}
              >
                Explore audio <ArrowRight size={18} />
              </button>
            </div>
            <div className="hero-proof">
              <span>
                <ShieldCheck size={17} /> 1-year warranty
              </span>
              <span>
                <PackageCheck size={17} /> 30-day returns
              </span>
            </div>
          </div>
          <div className="hero-ticker">
            <span>UP TO 45% OFF</span>
            <span>NEW DEALS WEEKLY</span>
            <span>NO MEMBERSHIP NEEDED</span>
          </div>
        </section>

        <section className="perks" aria-label="Shopping perks">
          <div>
            <Truck />
            <span>
              <strong>Fast &amp; free</strong> Over $75
            </span>
          </div>
          <div>
            <ShieldCheck />
            <span>
              <strong>Buy confidently</strong> 1-year coverage
            </span>
          </div>
          <div>
            <PackageCheck />
            <span>
              <strong>Easy returns</strong> Send it back in 30
            </span>
          </div>
          <div>
            <Zap />
            <span>
              <strong>Fresh drops</strong> New deals every week
            </span>
          </div>
        </section>

        <section className="deals-section" id="deals">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Worth plugging into</p>
              <h2>Today&rsquo;s top deals</h2>
            </div>
            <p>Limited stock, real savings. When they&rsquo;re gone, they&rsquo;re gone.</p>
          </div>

          <div className="shop-controls">
            <div className="category-tabs" role="tablist" aria-label="Product categories">
              {categoryMeta.map(({ name, icon: Icon }) => (
                <button
                  key={name}
                  type="button"
                  className={activeCategory === name ? "active" : ""}
                  onClick={() => setActiveCategory(name)}
                  role="tab"
                  aria-selected={activeCategory === name}
                >
                  <Icon size={17} /> {name}
                </button>
              ))}
            </div>
            <label className="sort-control">
              Sort
              <select value={sort} onChange={(event) => setSort(event.target.value)}>
                <option value="featured">Featured</option>
                <option value="low">Price: low to high</option>
                <option value="high">Price: high to low</option>
                <option value="discount">Biggest savings</option>
              </select>
            </label>
          </div>

          {visibleProducts.length ? (
            <div className="product-grid">
              {visibleProducts.map((product) => (
                <ProductCard product={product} onAdd={addToCart} key={product.id} />
              ))}
            </div>
          ) : (
            <div className="no-results">
              <Search size={30} />
              <h3>No deals found</h3>
              <p>Try a different category or search phrase.</p>
              <button
                type="button"
                className="text-link"
                onClick={() => {
                  setSearch("");
                  setActiveCategory("All deals");
                }}
              >
                Clear filters <ArrowRight size={17} />
              </button>
            </div>
          )}
        </section>

        <section className="manifesto">
          <div className="manifesto-number">01&mdash;04</div>
          <div>
            <p className="eyebrow eyebrow-light">Why Voltway</p>
            <h2>
              Less markup.
              <br />
              More <em>power</em> to you.
            </h2>
          </div>
          <div className="manifesto-copy">
            <p>
              We hunt down overstock, open-box gems, and end-of-season tech so
              you don&rsquo;t have to. Every item is tested. Every price is
              checked. Every deal is the real thing.
            </p>
            <a className="text-link text-link-light" href="#story">
              How we keep prices low <ArrowRight size={18} />
            </a>
          </div>
          <Zap className="manifesto-zap" strokeWidth={1} />
        </section>

        <section className="newsletter" id="story">
          <div>
            <p className="eyebrow">Get the good stuff first</p>
            <h2>
              Deals move fast.
              <br />
              <em>You should too.</em>
            </h2>
          </div>
          {subscribed ? (
            <div className="success-message">
              <span>
                <Check size={22} />
              </span>
              <div>
                <strong>You&rsquo;re on the list.</strong>
                <p>Watch your inbox for the next Voltway drop.</p>
              </div>
            </div>
          ) : (
            <form onSubmit={submitNewsletter}>
              <label htmlFor="email">Drop alerts, price cuts, and zero spam.</label>
              <div>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  required
                />
                <button type="submit" className="button button-dark">
                  Join the list <ArrowRight size={18} />
                </button>
              </div>
              <p>By signing up, you agree to receive Voltway emails. Unsubscribe anytime.</p>
            </form>
          )}
        </section>
      </main>

      <footer>
        <div className="footer-main">
          <div>
            <Logo />
            <p>Tech for people who know a good deal when they see one.</p>
          </div>
          <div>
            <h3>Shop</h3>
            <a href="#deals">Today&rsquo;s deals</a>
            <a href="#deals">Audio</a>
            <a href="#deals">Computing</a>
            <a href="#deals">Phones</a>
          </div>
          <div>
            <h3>Help</h3>
            <a href="#shipping">Shipping</a>
            <a href="#returns">Returns</a>
            <a href="#warranty">Warranty</a>
            <a href="mailto:hello@voltway.example">Contact</a>
          </div>
          <div className="footer-note">
            <p>Questions? We&rsquo;re real people.</p>
            <a href="mailto:hello@voltway.example">hello@voltway.example</a>
          </div>
        </div>
        <div className="footer-bottom">
          <span>&copy; 2026 Voltway, Inc.</span>
          <span>Privacy &middot; Terms &middot; Accessibility</span>
          <span className="api-status">
            <i className="online" /> Need help? Tap the chat bubble.
          </span>
        </div>
      </footer>

      <CartDrawer cart={cart} setCart={setCart} open={cartOpen} onClose={() => setCartOpen(false)} />
    </div>
  );
}
