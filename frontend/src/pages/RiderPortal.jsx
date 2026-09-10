import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api, { peso, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import DeliveryMap from "@/components/DeliveryMap";
import { Button } from "@/components/ui/button";
import { Bike, MapPin, Phone, Package, Navigation, CheckCircle2, Truck, Store, Wallet } from "lucide-react";
import { toast } from "sonner";

const STATUS_LABEL = { pending: "Pending", confirmed: "Confirmed", packed: "Packed", rider_assigned: "Rider Assigned", out_for_delivery: "Out for Delivery", delivered: "Delivered", ready_for_pickup: "Ready for Pickup", picked_up: "Picked Up", cancelled: "Cancelled" };

export default function RiderPortal() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [orders, setOrders] = useState([]);
  const [busy, setBusy] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [earnings, setEarnings] = useState(null);
  const watchRef = useRef(null);

  const load = () => {
    api.get("/rider/orders").then((r) => setOrders(r.data));
    api.get("/rider/earnings").then((r) => setEarnings(r.data)).catch(() => {});
  };

  useEffect(() => {
    if (loading) return;
    if (!user) { navigate("/login"); return; }
    if (user.role !== "rider") { navigate("/"); return; }
    load();
    const t = setInterval(load, 8000);
    return () => { clearInterval(t); if (watchRef.current) navigator.geolocation.clearWatch(watchRef.current); };
    // eslint-disable-next-line
  }, [user, loading]);

  const startLocationSharing = (onError) => {
    if (!navigator.geolocation) { toast.error("Geolocation not supported on this device"); return false; }
    if (watchRef.current) return true; // already sharing
    watchRef.current = navigator.geolocation.watchPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        // fire-and-forget for every currently-active delivery
        const targets = orders.filter((o) => o.status === "out_for_delivery");
        targets.forEach((o) => api.put(`/orders/${o.id}/rider-location`, { lat: latitude, lng: longitude }).catch(() => {}));
      },
      (err) => { if (onError) onError(err); else toast.error("Could not get your location — please allow location access"); },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
    );
    setSharing(true);
    return true;
  };

  const stopLocationSharing = () => {
    if (watchRef.current) navigator.geolocation.clearWatch(watchRef.current);
    watchRef.current = null; setSharing(false);
  };

  const setStatus = async (id, status) => {
    setBusy(true);
    try {
      await api.put(`/orders/${id}/rider-status`, { status });
      toast.success(`Marked ${STATUS_LABEL[status]}`);
      // Auto-start GPS sharing the moment a delivery goes out
      if (status === "out_for_delivery") {
        const started = startLocationSharing(() => toast.error("Please allow location access so the buyer can track you"));
        if (started) toast.success("Sharing your live GPS with the buyer");
      }
      // If the delivery just finished, and no other active deliveries remain, stop sharing
      if (status === "delivered") {
        const stillActive = orders.some((o) => o.id !== id && o.status === "out_for_delivery");
        if (!stillActive) stopLocationSharing();
      }
      load();
    }
    catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed"); }
    finally { setBusy(false); }
  };

  const active = orders.filter((o) => o.status === "out_for_delivery");

  const toggleShare = () => {
    if (sharing) {
      stopLocationSharing();
      toast("Stopped sharing location");
      return;
    }
    if (active.length === 0) { toast.error("Start a delivery (Out for Delivery) first"); return; }
    if (startLocationSharing()) toast.success("Sharing live location with buyers");
  };

  if (loading || !user) return <div className="py-24 text-center text-muted-foreground">Loading…</div>;

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-heading font-black text-3xl tracking-tight">My Deliveries</h1>
          <p className="text-sm text-muted-foreground mt-1">Rider · {user.name}</p>
        </div>
        <Button data-testid="share-location-btn" onClick={toggleShare}
          className={`rounded-full gap-2 ${sharing ? "bg-destructive hover:bg-destructive/90" : "bg-primary hover:bg-primary/90"}`}>
          <Navigation size={16} className={sharing ? "animate-pulse" : ""} /> {sharing ? "Stop sharing" : "Share live location"}
        </Button>
      </div>

      {earnings && (
        <div className="grid grid-cols-3 gap-3 mb-6">
          <div className="bg-card border border-border rounded-2xl p-4"><Package className="text-primary" size={20} /><div className="font-heading font-black text-2xl mt-1" data-testid="rider-completed">{earnings.completed}</div><div className="text-xs text-muted-foreground uppercase tracking-wider">Completed</div></div>
          <div className="bg-card border border-border rounded-2xl p-4"><Truck className="text-accent" size={20} /><div className="font-heading font-black text-2xl mt-1" data-testid="rider-active">{earnings.active}</div><div className="text-xs text-muted-foreground uppercase tracking-wider">Active</div></div>
          <div className="bg-primary text-primary-foreground rounded-2xl p-4"><Wallet size={20} /><div className="font-heading font-black text-2xl mt-1" data-testid="rider-fees">{peso(earnings.fees_earned)}</div><div className="text-xs text-primary-foreground/80 uppercase tracking-wider">Fees earned</div></div>
        </div>
      )}

      {orders.length === 0 ? (
        <div className="text-center py-24 text-muted-foreground"><Bike className="mx-auto mb-3 opacity-50" /><p>No deliveries assigned to you yet.</p></div>
      ) : (
        <div className="space-y-4">
          {orders.map((o) => (
            <div key={o.id} data-testid={`rider-order-${o.id}`} className="bg-card border border-border rounded-2xl p-4">
              <div className="flex items-center justify-between">
                <div className="font-heading font-bold flex items-center gap-2"><Package size={16} className="text-primary" /> #{o.id.slice(0, 8)}</div>
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${o.status === "delivered" ? "bg-primary/10 text-primary" : "bg-accent/10 text-accent"}`}>{STATUS_LABEL[o.status]}</span>
              </div>

              <div className="mt-3 rounded-xl bg-secondary/50 p-3 text-sm space-y-1.5">
                <div className="flex items-start gap-2"><MapPin size={15} className="mt-0.5 text-primary shrink-0" /><span data-testid={`rider-address-${o.id}`} className="font-medium">{o.delivery_address || "No address"}</span></div>
                {o.delivery_lat != null && (
                  <a href={`https://www.google.com/maps/dir/?api=1&destination=${o.delivery_lat},${o.delivery_lng}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline"><Navigation size={12} /> Open in Google Maps ({o.delivery_lat.toFixed(4)}, {o.delivery_lng.toFixed(4)})</a>
                )}
                <div className="flex items-center gap-2"><Phone size={15} className="text-primary" /><a href={`tel:${o.contact_phone}`} className="hover:underline">{o.contact_phone}</a> · {o.buyer_name}</div>
                <div className="text-xs text-muted-foreground">{o.items.reduce((s, i) => s + i.quantity, 0)} item(s) · {peso(o.total)} · {o.payment_method === "cod" ? "Collect cash on delivery" : o.payment_method === "gcash" ? "GCash" : "Paid online"}</div>
              </div>

              {o.delivery_lat != null && o.status !== "delivered" && (
                <div className="mt-3"><DeliveryMap order={o} height={200} /></div>
              )}

              <div className="flex flex-wrap gap-2 mt-3">
                {o.status === "rider_assigned" && <Button data-testid={`start-delivery-${o.id}`} size="sm" disabled={busy} onClick={() => setStatus(o.id, "out_for_delivery")} className="rounded-full bg-accent hover:bg-accent/90 text-accent-foreground text-xs h-8 gap-1"><Truck size={13} /> Start delivery</Button>}
                {o.status === "out_for_delivery" && <Button data-testid={`mark-delivered-${o.id}`} size="sm" disabled={busy} onClick={() => setStatus(o.id, "delivered")} className="rounded-full bg-primary hover:bg-primary/90 text-xs h-8 gap-1"><CheckCircle2 size={13} /> Mark delivered</Button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
