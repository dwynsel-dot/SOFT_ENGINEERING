import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api, { peso, formatApiErrorDetail } from "@/lib/api";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import MapPicker from "@/components/MapPicker";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { MUNICIPALITIES, matchCoords, haversineKm } from "@/lib/laguna";
import { CreditCard, Banknote, MapPin, Truck, Store, Wallet } from "lucide-react";
import { toast } from "sonner";

const LAGUNA_TOWNS = Object.keys(MUNICIPALITIES);

export default function Checkout() {
  const { items, total, clear } = useCart();
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [fulfillment, setFulfillment] = useState("delivery");
  const [method, setMethod] = useState("online");
  const [municipality, setMunicipality] = useState("");
  const [detail, setDetail] = useState(user?.address || "");
  const [phone, setPhone] = useState(user?.phone || "");
  const [pin, setPin] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const placed = useRef(false);
  const [shippingFee, setShippingFee] = useState(0);
  const [localRate, setLocalRate] = useState(false);

  const pickupLocation = items[0]?.location || "Laguna";
  const address = [detail.trim(), municipality, municipality ? "Laguna" : ""].filter(Boolean).join(", ");

  useEffect(() => { if (loading || placed.current) return; if (!user) navigate("/login"); else if (items.length === 0) navigate("/market"); }, [user, loading, items, navigate]);

  useEffect(() => {
    if (fulfillment === "pickup" || items.length === 0) { setShippingFee(0); setLocalRate(false); return; }
    const t = setTimeout(() => {
      api.post("/shipping-quote", { fulfillment_type: "delivery", product_id: items[0].product_id,
        delivery_lat: pin?.lat, delivery_lng: pin?.lng, delivery_address: address })
        .then((r) => { setShippingFee(r.data.shipping_fee); setLocalRate(!!r.data.local_rate); }).catch(() => {});
    }, 500);
    return () => clearTimeout(t);
  }, [fulfillment, pin, address, items]);

  const grandTotal = fulfillment === "pickup" ? total : total + shippingFee;

  const submit = async () => {
    if (!phone.trim()) { toast.error("Please provide a contact phone."); return; }
    if (fulfillment === "delivery" && !municipality) { toast.error("Please select your Laguna municipality."); return; }
    if (fulfillment === "delivery" && !detail.trim()) { toast.error("Please add your house no. / barangay."); return; }
    setSubmitting(true);
    try {
      const payload = {
        items: items.map(({ product_id, name, price, quantity, seller_id, image_url }) => ({ product_id, name, price, quantity, seller_id, image_url })),
        delivery_address: fulfillment === "delivery" ? address : "",
        delivery_lat: pin?.lat, delivery_lng: pin?.lng,
        fulfillment_type: fulfillment,
        pickup_location: fulfillment === "pickup" ? pickupLocation : null,
        contact_phone: phone, payment_method: method,
        origin_url: window.location.origin,
      };
      const { data } = await api.post("/checkout", payload);
      placed.current = true;
      if (method === "cod") {
        clear();
        toast.success(fulfillment === "pickup" ? "Order placed! Pay when you pick up." : "Order placed! Pay on delivery.");
        navigate("/orders");
      } else if (method === "gcash") {
        clear();
        if (data.gcash_mode === "auto") {
          window.location.href = data.checkout_url;
        } else {
          toast.success("Order placed! Complete your GCash payment.");
          navigate(`/gcash-pay/${data.order_id}`);
        }
      } else {
        localStorage.setItem("pending_order", data.order_id);
        window.location.href = data.checkout_url;
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Checkout failed");
    } finally { setSubmitting(false); }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
      <h1 className="font-heading font-black text-3xl tracking-tight mb-6">Checkout</h1>
      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* Fulfillment */}
          <div className="bg-card border border-border rounded-2xl p-6">
            <h2 className="font-heading font-bold text-lg">How do you want it?</h2>
            <div className="grid sm:grid-cols-2 gap-3 mt-4">
              {[{ v: "delivery", i: Truck, t: "Deliver to me", d: "A rider brings it to your address" },
                { v: "pickup", i: Store, t: "Pick up at farm", d: "Best when you're near the farm" }].map((f) => (
                <button key={f.v} data-testid={`fulfill-${f.v}`} onClick={() => setFulfillment(f.v)}
                  className={`text-left p-4 rounded-2xl border-2 transition-colors ${fulfillment === f.v ? "border-primary bg-secondary" : "border-border hover:border-primary/40"}`}>
                  <f.i size={22} className={fulfillment === f.v ? "text-primary" : "text-muted-foreground"} />
                  <div className="font-semibold mt-2">{f.t}</div>
                  <div className="text-xs text-muted-foreground">{f.d}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Location details */}
          <div className="bg-card border border-border rounded-2xl p-6">
            <h2 className="font-heading font-bold text-lg flex items-center gap-2"><MapPin size={18} className="text-primary" /> {fulfillment === "pickup" ? "Pickup details" : "Delivery details"}</h2>
            <div className="mt-4 space-y-4">
              {fulfillment === "delivery" ? (
                <>
                  <div>
                    <Label>Municipality (Laguna)</Label>
                    <Select value={municipality} onValueChange={setMunicipality}>
                      <SelectTrigger data-testid="municipality-select" className="mt-1.5"><SelectValue placeholder="Select your town" /></SelectTrigger>
                      <SelectContent>{LAGUNA_TOWNS.map((t) => <SelectItem key={t} value={t} data-testid={`municipality-${t}`}>{t}</SelectItem>)}</SelectContent>
                    </Select>
                    {localRate && <p className="text-xs text-primary font-medium mt-1.5" data-testid="local-rate-note">✓ Same town as the seller — you get the cheaper local rate!</p>}
                  </div>
                  <div><Label>House no. / Barangay / Street</Label><Textarea data-testid="address-field" value={detail} onChange={(e) => setDetail(e.target.value)} className="mt-1.5" placeholder="e.g. 12 Mabini St., Brgy. San Jose" /></div>
                  <div>
                    <Label>Pin your location on the map (optional)</Label>
                    <p className="text-xs text-muted-foreground mb-1.5">Tap the map or use “Use my location” for a more accurate drop-off.</p>
                    <MapPicker value={pin} onChange={(v) => { setPin(v); if (v.address) setDetail(v.address); }} />
                    {pin && <p className="text-xs text-muted-foreground mt-1.5" data-testid="pin-coords">Pinned: {pin.lat}, {pin.lng}</p>}
                  </div>
                </>
              ) : (
                <div className="rounded-xl bg-secondary/50 p-4 text-sm">
                  <div className="flex items-center gap-2 font-medium"><Store size={16} className="text-primary" /> Pick up from</div>
                  <p className="text-muted-foreground mt-1">{pickupLocation}</p>
                  <p className="text-xs text-muted-foreground mt-2">The seller will notify you once your order is ready for pickup.</p>
                </div>
              )}
              <div><Label>Contact phone</Label><Input data-testid="phone-field" value={phone} onChange={(e) => setPhone(e.target.value)} className="mt-1.5" placeholder="0917-xxx-xxxx" /></div>
            </div>
          </div>

          {/* Payment */}
          <div className="bg-card border border-border rounded-2xl p-6">
            <h2 className="font-heading font-bold text-lg">Payment method</h2>
            <div className="grid sm:grid-cols-3 gap-3 mt-4">
              {[{ v: "online", i: CreditCard, t: "Pay online", d: "Card, GCash or Maya via secure PayMongo" },
                { v: "gcash", i: Wallet, t: "GCash", d: "Scan QR or send to the seller's GCash" },
                { v: "cod", i: Banknote, t: fulfillment === "pickup" ? "Pay on pickup" : "Cash on delivery", d: fulfillment === "pickup" ? "Pay the seller on pickup" : "Pay the rider on arrival" }].map((m) => (
                <button key={m.v} data-testid={`pay-${m.v}`} onClick={() => setMethod(m.v)}
                  className={`text-left p-4 rounded-2xl border-2 transition-colors ${method === m.v ? "border-primary bg-secondary" : "border-border hover:border-primary/40"}`}>
                  <m.i size={22} className={method === m.v ? "text-primary" : "text-muted-foreground"} />
                  <div className="font-semibold mt-2">{m.t}</div>
                  <div className="text-xs text-muted-foreground">{m.d}</div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="bg-card border border-border rounded-2xl p-6 h-fit">
          <h2 className="font-heading font-bold text-lg">Order</h2>
          <div className="mt-4 space-y-2 max-h-52 overflow-y-auto">
            {items.map((i) => (
              <div key={i.product_id} className="flex justify-between text-sm">
                <span className="text-muted-foreground truncate pr-2">{i.name} ×{i.quantity}</span>
                <span className="font-medium whitespace-nowrap">{peso(i.price * i.quantity)}</span>
              </div>
            ))}
          </div>
          <div className="border-t border-border my-4" />
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Subtotal</span><span className="font-medium">{peso(total)}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Shipping fee</span><span className="font-medium" data-testid="checkout-shipping">{fulfillment === "pickup" ? "Free (pickup)" : peso(shippingFee)}</span></div>
          </div>
          <div className="border-t border-border my-3" />
          <div className="flex justify-between font-heading font-bold text-lg"><span>Total</span><span className="text-primary" data-testid="checkout-total">{peso(grandTotal)}</span></div>
          <Button data-testid="place-order-btn" onClick={submit} disabled={submitting} className="w-full mt-5 rounded-full bg-accent hover:bg-accent/90 text-accent-foreground h-12">
            {submitting ? "Processing…" : method === "cod" ? "Place order" : "Pay now"}
          </Button>
        </div>
      </div>
    </div>
  );
}
