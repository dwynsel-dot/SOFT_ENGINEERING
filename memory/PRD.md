# FarmDirect Laguna — PRD

## Original Problem Statement
Build a Shopee-style marketplace for farmers (sellers) and buyers within Laguna province, Philippines. Enable online payment, seller & buyer login, order tracking + delivery procedures. Sellers post their farm goods; buyers buy farm goods.

## Architecture
- **Backend**: FastAPI + MongoDB (motor). All routes under `/api`. JWT (Bearer + httpOnly cookie) auth with bcrypt.
- **Frontend**: React (CRA) + Tailwind + shadcn/ui + framer-motion. AuthContext + CartContext (localStorage cart).
- **Payments**: Stripe via emergentintegrations (managed shared sandbox `sk_test_emergent`), dynamic PHP amounts + Cash on Delivery. (Note: Stripe claimable sandbox not available for PH; using shared test sandbox.)
- **Storage**: Emergent object storage for seller product image uploads.

## User Personas
- **Buyer**: browses market, adds to cart, checks out (online/COD), tracks orders.
- **Seller (Farmer)**: posts goods with photos, manages incoming orders, advances delivery status, assigns riders.
- **Admin/Owner** (wynseldailo5@gmail.com): sees all orders.

## Admin/Owner (2026-06 — view-only)
- Admin = oversight only. Lands on /orders (all orders across marketplace, read-only). Cannot manage/act on orders or products. Backend enforces via require_seller_only on all write endpoints; frontend hides Sell link, seller dashboard, and action buttons for admin.

## Core Requirements (static)
- Email/password auth, roles buyer/seller/admin.
- Product CRUD with image upload.
- Cart + checkout with online payment (Stripe) and COD.
- Order tracking stages: pending → confirmed → packed → rider_assigned → out_for_delivery → delivered (+cancelled).
- Rider assignment with rider details.

## Implemented (2026-06)
- JWT auth (register/login/me/logout), role guarding. [done]
- Marketplace with category filter + search; product detail. [done]
- Seller dashboard: post/upload/delete products, stats, incoming orders, advance status, assign rider. [done]
- Cart, checkout (online + COD), Stripe session + polling + webhook, payment result page. [done]
- Buyer orders page with visual OrderTracker stepper + rider info. [done]
- Seeded riders, admin, demo seller/buyer + 8 products. [done]
- Stock decrement on order; stock restore on cancelled/expired online payment. [done]
- Tested: 24/24 backend pytest pass, all frontend flows pass. [done]

## Implemented (2026-06, iteration 2)
- Order cancellation (buyer + seller) for unpaid orders via PUT /api/orders/{id}/cancel with automatic stock restore (idempotent). [done]
- Live delivery map (Leaflet/OpenStreetMap) in buyer order tracking: drop-off pin + rider marker + animated route when out_for_delivery; pickup-location map for pickup orders. [done]
- Pickup fulfillment option at checkout (delivery vs pickup) — pickup skips address/rider. [done]
- Seller-driven confirmation: all orders now start 'pending'; seller confirms & advances (delivery: confirmed→packed→rider_assigned→out_for_delivery→delivered; pickup: confirmed→ready_for_pickup→picked_up). [done]
- Map picker at checkout to drop a delivery pin (lat/lng). [done]
- Tested: 18/18 backend pytest pass, all frontend flows pass.

## Backlog / Remaining
- P2: Multi-seller cart split into per-seller sub-orders; tighten CORS for prod; split server.py into routers.
- P2: Refunds for paid orders (currently only unpaid orders cancellable).
- P2: Real-time rider GPS (map currently animates a simulated route).

## Next Tasks
- Split server.py into routers/ (now ~885 lines — overdue).
- Refund flow for paid online/GCash orders.

## Implemented (2026-06, iteration 7 — ETA, Rider earnings, Email alerts)
- Delivery ETA: buyer sees "~N min · K km away" on out-for-delivery orders, computed from rider live location to drop-off (lib/laguna etaFrom, 22km/h). [done]
- Rider earnings: /rider portal cards for Completed, Active, Fees earned (GET /api/rider/earnings, null-safe). [done]
- Email alerts (Resend managed): buyer emailed on out_for_delivery ("on the way"), arriving (<1.5km, once), and delivered. send_email/order_email_html; EMERGENT_EMAIL_KEY in .env. [done]
- Hardened Orders live-poll (deps [open], self-clears on terminal status). Tested iteration_9: 4/4 frontend flows, backend chain verified, emails send with no errors.

## Implemented (2026-06, iteration 10 — Municipalities, same-town rate, stock edit, rate-from-orders, rider email)
- Fixed a P0 startup blocker: server.py had a corrupted duplicated tail block (crash on boot) — removed. [done]
- PayMongo TEST key active: swapped sk_live_ → sk_test_RH3PZ8... in backend/.env so GCash auto-verify runs in sandbox (no real charges). [done]
- Checkout Laguna municipality DROPDOWN (12 towns) + house/barangay detail + optional map pin; composed address; municipality required. [done]
- Same-town shipping discount: flat LOCAL_RATE ₱30 when seller town == buyer town, else distance-based. Wired into BOTH /api/shipping-quote (returns local_rate) AND /api/checkout via shipping_fee_for() — preview & persisted fee now match (verified: Calamba same-town order persists ₱30). [done]
- Shipping fee credited 100% to the assigned rider (GET /api/rider/earnings sums delivered orders' shipping_fee). [done]
- Seller stock edit: PATCH /api/products/{id}/stock (seller-owned, StockUpdate ge=0) + 'Edit stock' button/dialog in Seller Dashboard My Products tab. [done]
- Buyers rate/review delivered products directly from Orders page (per-item 'Rate this product' → StarRating + comment dialog → POST /products/{id}/reviews). [done]
- Rider email on assignment: PUT /api/orders/{id}/assign-rider looks up the rider's user email (via rider_user_id) and sends a Resend email with order #, address, and delivery fee. Custom/temp riders (no account) skip email. [done]
- Tested iteration_10: same-town persisted fee ₱30 (curl), stock PATCH (curl), reviews POST OK, assign-rider 200 + no 500 from email, rider earnings shape OK. Frontend compiles clean.

## Implemented (2026-07, iteration 13 — PayMongo online payment + Refund flow)
- Online payment now routes through **PayMongo Hosted Checkout** (card + GCash + Maya) using the user's `sk_test_RH3PZ8j53Cye2Fz58Dmnbkf7` key on `/v1/checkout_sessions`. Stripe is preserved as fallback if PayMongo key is unset. Order stores `payment_provider="paymongo"` + `paymongo_session_id`. [done]
- Added `GET /api/paymongo/status/{order_id}` polling endpoint used by `PaymentResult` after redirect back from PayMongo. Extracts `paymongo_payment_id` from the session's paid `payments[]` and stores it. [done]
- `PUT /api/orders/{id}/cancel` now allows paid online/GCash orders and issues a PayMongo refund via `POST /v1/refunds` (auto-retrieves `paymongo_payment_id` from the session if not yet stored). On success sets `payment_status="refunded"`, `refund_id`, `refund_provider`. Blocks cancel when `status="out_for_delivery"`. Refund failures return **HTTP 409** (not 502) because Cloudflare intercepts every 5xx and replaces the body with a generic HTML error page. Same 502→400 downgrade applied to checkout gateway failures. [done]
- Orders page: cancel is now a confirmation Dialog with paid-vs-unpaid copy ("refund back to your original method · 3–7 business days" vs "restore the seller's stock"). Refunded orders show a persistent inline note. [done]
- Verified: backend 8/8 tests pass; frontend 3/3 scenarios pass (online redirect to checkout.paymongo.com, paid-order refund dialog + toast, unpaid COD cancel dialog + stock restore).

## Implemented (2026-07, iteration 12 — Login CORS fix)
- Fixed "Something went wrong. Please try again." toast on login. Root cause: ingress rewrites the `Origin` header for the preview domain, so FastAPI's CORS middleware (with `allow_credentials=True`) echoed back the rewritten origin, failing the browser's preflight check. Fix: set `allow_credentials=False` in the CORS config in `/app/backend/server.py`. Preflight now returns `Access-Control-Allow-Origin: *`. Auth uses localStorage Bearer tokens (no cookies), so no functional loss. All 3 login flows (buyer/seller/admin) verified. [done]

## Implemented (2026-07, iteration 11 — Map z-index overlap fix)
- Fixed Leaflet map overlapping shadcn Radix portals: `.leaflet-container` now isolates its stacking context and inner panes/controls are capped below z-50. Municipality Select dropdown (Checkout) and Rate product Dialog (Orders) now render cleanly above the map. Verified via UI test on /checkout. [done]

## Pending on user input
- PayMongo webhook secret (PAYMONGO_WEBHOOK_SECRET) still empty — auto-verify checkout works but signed webhook confirmation is inactive until user registers the webhook {backend}/api/webhook/paymongo and pastes its secret.

## Implemented (2026-06, iteration 6 — Rider role, live tracking, accurate address, QR warning)
- Accurate checkout address: MapPicker reverse-geocodes pin/location (Nominatim) and auto-fills the delivery address; "Use my location" via browser geolocation. [done]
- Rider role: riders register/login (role selector), auto-added to riders list so sellers can assign them; /rider portal lists assigned deliveries with accurate address, map, Google Maps directions, buyer contact, and Start delivery / Mark delivered actions (PUT /api/orders/{id}/rider-status). [done]
- Real-time tracking: rider "Share live location" (geolocation watch) posts to PUT /api/orders/{id}/rider-location; buyer order map shows the live rider marker and polls every 5s. [done]
- GCash QR-missing: prominent amber warning on /gcash-pay when the seller has no uploaded QR (auto-generated code is not an official GCash QR). [done]
- Rider endpoints are rider-owned (buyer/seller get 403). Tested iteration_8: 6/6 frontend flows + backend rider chain verified.

## Implemented (2026-06, iteration 5 — Shipping fee, Temporary riders, Delivery-gated reviews)
- Reviews now require the buyer's order to be delivered/picked_up (GET /api/products/{id}/can-review gates the UI form). [done]
- Shipping fee on delivery orders: distance-based (Lalamove-style ₱49 base + ₱6/km ≤5km then ₱5/km) via haversine between seller town and drop-off; pickup = free. POST /api/shipping-quote for live checkout estimate; orders store subtotal/shipping_fee/total. [done]
- Sellers can assign a TEMPORARY custom rider (name/phone/vehicle) per delivery order (PUT /api/orders/{id}/assign-custom-rider) — not saved to riders list, shown on the order + delivery history with a "(temp)" marker. [done]
- Tested iteration_7: 100% backend (7/7) + 100% frontend flows.

## Implemented (2026-06, iteration 4 — PayMongo auto-verify, Reviews, Earnings)
- PayMongo GCash auto-verify (Hosted Checkout V2 + signed webhook /api/webhook/paymongo) wired but DORMANT until PAYMONGO_SECRET_KEY + PAYMONGO_WEBHOOK_SECRET set. When empty, GCash uses the manual seller-QR flow. gcash_mode="auto"|"manual" on orders; GcashPayment page polls status in auto mode. Central collection (owner account). [done, awaiting keys]
- Ratings & Reviews: buyers review purchased products (POST /api/products/{id}/reviews, 1-5 + comment, one per buyer/product), product rating_avg/count denormalized, seller_rating on product detail, star ratings on cards + detail + seller products, reviews list + form. [done]
- Seller Earnings tab: income breakdown Card/Online + GCash + Cash, total, pending, per-order table (GET /api/seller/earnings). [done]
- Tested iteration_6: 100% frontend flows, backend 25/26 (1 pre-existing Stripe <₱25 min-amount edge case).
- KNOWN: to enable auto-verify, add PayMongo test keys to backend/.env and register webhook URL {backend}/api/webhook/paymongo for event checkout_session.payment.paid.

## Implemented (2026-06, iteration 3 — GCash)
- GCash manual payment: sellers save GCash name/number + optional uploaded GCash QR (PUT /api/seller/gcash). [done]
- Buyer GCash checkout: 3rd payment option → dedicated /gcash-pay/:orderId page showing seller QR (uploaded or server-generated PNG via GET /api/gcash-qr/{id}), number/name with copy, and reference submission (PUT /api/orders/{id}/gcash-reference → gcash_submitted). [done]
- Seller confirms receipt (PUT /api/orders/{id}/verify-payment → paid); reference shown on seller order card. [done]
- Fixed checkout post-submit navigation race (placed useRef guard) affecting COD + GCash. [done]
- Tested: full GCash lifecycle passes end-to-end via UI (iteration_5, 100%).
- NOTE: This is a direct peer-to-peer GCash transfer flow (no gateway). True automated account-linking/charging would require a licensed provider (PayMongo/Xendit) + the seller's merchant KYC and API keys.
