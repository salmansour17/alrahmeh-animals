// The gift shop: the sixteen products from the rescue's previous website, with
// their prices. There is no cart or checkout here; "Order" opens the contact
// form with the product filled in, and staff confirm size, availability and
// payment by email. Changing the catalogue means editing PRODUCTS and
// rebuilding, which is a known gap until the shop has a backend of its own.
import { Link } from "react-router-dom";
import { BowlIcon, HeartIcon, HomeIcon, PawIcon } from "../art.jsx";

const CATEGORY_ICONS = {
  Hoodies: <PawIcon size={64} />,
  "T-shirts": <PawIcon size={64} />,
  Mugs: <BowlIcon size={64} />,
  "Dog beds": <HomeIcon size={64} />,
  "Gifts & activities": <HeartIcon size={64} />,
};

// Prices are written exactly as the rescue lists them, in JOD.
export const PRODUCTS = [
  { slug: "comfy-dog-bed", name: "A Washable Comfy Dog Bed", category: "Dog beds", price: "30 – 60 JOD" },
  { slug: "edgy-dog-bed", name: "An Edgy Washable Dog Bed", category: "Dog beds", price: "60 – 90 JOD" },
  { slug: "adopt-canaan-tshirt", name: "Adopt Canaan T-shirt", category: "T-shirts", price: "15 JOD" },
  { slug: "catch-tshirt", name: "Catch T-shirt", category: "T-shirts", price: "17 JOD" },
  { slug: "pawfect-love-tshirt", name: "Pawfect Love Customised T-shirt", category: "T-shirts", price: "20 JOD" },
  { slug: "rafa-mercy-tshirt", name: "Ra'fa Mercy T-shirt", category: "T-shirts", price: "8 JOD" },
  { slug: "canaan-paw-hoodie", name: "Canaan Paw Hoodie", category: "Hoodies", price: "25 JOD" },
  { slug: "cats-love-hoodie", name: "Cats Love Hoodie", category: "Hoodies", price: "25 JOD" },
  { slug: "love-canaan-grey-hoodie", name: "Love Canaan Grey Hoodie", category: "Hoodies", price: "25 JOD" },
  { slug: "love-canaan-hoodie", name: "Love Canaan Hoodie", category: "Hoodies", price: "25 JOD" },
  { slug: "rafa-mercy-eid-mug", name: "Ra'fa Mercy Eid Mug", category: "Mugs", price: "5 JOD" },
  { slug: "cat-coffee-mug", name: "The Cat Coffee Mug", category: "Mugs", price: "15 JOD" },
  { slug: "dog-coffee-mug", name: "The Dog Coffee Mug", category: "Mugs", price: "15 JOD" },
  { slug: "cause-candles", name: "N600 Cause Candles", category: "Gifts & activities", price: "20 JOD" },
  { slug: "dog-craft-for-kids", name: "Dog Craft for Kids", category: "Gifts & activities", price: "15 JOD" },
  { slug: "bundog-story", name: "The Dog Story \"Bundog\"", category: "Gifts & activities", price: "5 JOD" },
];

const CATEGORIES = [...new Set(PRODUCTS.map((p) => p.category))];

export function Shop() {
  return (
    <>
      <section className="hero">
        <div className="hero-text">
          <p className="eyebrow">
            <HeartIcon size={18} /> Shop and support us
          </p>
          <h1>Our gift shop</h1>
          <p className="lead">
            Hoodies, T-shirts, mugs, cosy dog beds and gifts for little ones. Everything you buy
            helps the animals in our care.
          </p>
        </div>
      </section>

      {CATEGORIES.map((category) => (
        <section key={category} aria-labelledby={`cat-${category}`}>
          <h2 id={`cat-${category}`} className="section-title">
            {category}
          </h2>
          <ul className="cards products">
            {PRODUCTS.filter((p) => p.category === category).map((product) => (
              <li key={product.slug} className="product">
                <div className="photo product-art" aria-hidden="true">
                  {CATEGORY_ICONS[product.category]}
                </div>
                <div className="card-body">
                  <h3>{product.name}</h3>
                  <p className="price">{product.price}</p>
                  <Link className="button button-soft" to={`/contact?topic=shop_order&product=${product.slug}`}>
                    Order
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}

      <p className="muted small center">
        Orders are confirmed by email: we'll check size and availability and tell you how to pay
        and collect.
      </p>
    </>
  );
}
