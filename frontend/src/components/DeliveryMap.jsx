import { useEffect, useRef, useState } from "react";
import { LAGUNA_CENTER, matchCoords } from "@/lib/laguna";

function pin(color, label) {
  return window.L.divIcon({
    className: "",
    html: `<div style="position:relative"><span style="display:grid;place-items:center;width:30px;height:30px;border-radius:50% 50% 50% 0;background:${color};transform:rotate(-45deg);box-shadow:0 2px 6px rgba(0,0,0,.35)"><span style="transform:rotate(45deg);color:#fff;font-size:13px;font-weight:700">${label}</span></span></div>`,
    iconSize: [30, 30], iconAnchor: [15, 30],
  });
}

function pulsingRiderIcon() {
  return window.L.divIcon({
    className: "",
    html: `<div style="position:relative;width:30px;height:30px">
      <span style="position:absolute;inset:0;border-radius:9999px;background:rgba(45,90,64,.25);animation:frdPulse 1.6s ease-out infinite"></span>
      <span style="position:absolute;inset:6px;border-radius:9999px;background:#2D5A40;box-shadow:0 0 0 2px #fff, 0 2px 6px rgba(0,0,0,.35)"></span>
    </div>
    <style>@keyframes frdPulse{0%{transform:scale(.7);opacity:.9}80%{transform:scale(1.9);opacity:0}100%{opacity:0}}</style>`,
    iconSize: [30, 30], iconAnchor: [15, 15],
  });
}

function formatAgo(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export default function DeliveryMap({ order, height = 260 }) {
  const ref = useRef();
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!window.L || !ref.current) return;
    const isPickup = order.fulfillment_type === "pickup";
    const dropoff = order.delivery_lat != null
      ? { lat: order.delivery_lat, lng: order.delivery_lng }
      : matchCoords(order.delivery_address);
    const pickupCoord = matchCoords(order.pickup_location || order.items?.[0]?.location);

    const focus = isPickup ? pickupCoord : dropoff;
    const map = window.L.map(ref.current, { scrollWheelZoom: false, zoomControl: true }).setView([focus.lat, focus.lng], 12);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap", maxZoom: 19,
    }).addTo(map);

    if (isPickup) {
      window.L.marker([pickupCoord.lat, pickupCoord.lng], { icon: pin("#2D5A40", "P") })
        .addTo(map).bindPopup(`Pickup point<br>${order.pickup_location || "Farm location"}`);
      map.setView([pickupCoord.lat, pickupCoord.lng], 13);
    } else {
      window.L.marker([dropoff.lat, dropoff.lng], { icon: pin("#E07A5F", "H") }).addTo(map).bindPopup("Delivery address");
      const origin = order.rider?.lat != null ? { lat: order.rider.lat, lng: order.rider.lng } : LAGUNA_CENTER;
      const live = order.rider_location;
      if (order.rider) {
        // Dashed hint from rider's home base to drop-off
        const line = window.L.polyline([[origin.lat, origin.lng], [dropoff.lat, dropoff.lng]], { color: "#2D5A40", weight: 3, dashArray: "6 8", opacity: 0.5 }).addTo(map);
        map.fitBounds(line.getBounds().pad(0.3));

        if (live) {
          // REAL live GPS from rider's device — pulsing marker, tight zoom
          window.L.marker([live.lat, live.lng], { icon: pulsingRiderIcon() })
            .addTo(map)
            .bindPopup(`<b>${order.rider.name}</b><br>${order.rider.vehicle || ""}<br><span style="color:#2D5A40;font-weight:600">● Live GPS</span>`);
          // Draw live→dropoff line more solid
          window.L.polyline([[live.lat, live.lng], [dropoff.lat, dropoff.lng]], { color: "#2D5A40", weight: 3, opacity: 0.85 }).addTo(map);
          map.fitBounds(window.L.latLngBounds([[live.lat, live.lng], [dropoff.lat, dropoff.lng]]).pad(0.4));
        } else if (order.status === "delivered") {
          window.L.marker([dropoff.lat, dropoff.lng], { icon: pin("#2D5A40", "R") }).addTo(map)
            .bindPopup(`${order.rider.name} · delivered`);
        } else {
          // No live GPS yet — static marker at rider's home base (NO simulated animation)
          window.L.marker([origin.lat, origin.lng], { icon: pin("#7a8a80", "R") })
            .addTo(map)
            .bindPopup(`<b>${order.rider.name}</b><br>${order.rider.vehicle || ""}<br><span style="color:#8a5a3a">Waiting for live GPS…</span>`);
        }
      }
    }
    const invalidateTimer = setTimeout(() => { try { map.invalidateSize(); } catch (_e) { /* map already removed */ } }, 250);
    return () => { clearTimeout(invalidateTimer); map.remove(); };
  }, [order.id, order.status, order.rider?.id, order.rider_location?.at, order.rider_location?.lat, order.rider_location?.lng]);

  // Tick every 15s so the "updated Xs ago" label refreshes
  useEffect(() => {
    if (!order.rider_location?.at) return;
    const t = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(t);
  }, [order.rider_location?.at]);

  const live = order.rider_location;
  const isDelivery = order.fulfillment_type !== "pickup";
  const stale = live && (now - new Date(live.at).getTime()) > 60000;

  return (
    <div className="relative">
      <div ref={ref} data-testid="delivery-map" style={{ height }} className="rounded-xl overflow-hidden border border-border" />
      {isDelivery && order.rider && order.status === "out_for_delivery" && (
        <div
          data-testid="gps-status-badge"
          className={`absolute top-3 left-3 z-[500] inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold shadow ${live ? (stale ? "bg-amber-100 text-amber-800" : "bg-primary text-primary-foreground") : "bg-secondary text-secondary-foreground border border-border"}`}
        >
          <span className={`h-2 w-2 rounded-full ${live ? (stale ? "bg-amber-500" : "bg-white animate-pulse") : "bg-muted-foreground"}`}></span>
          {live ? (stale ? `Live GPS · updated ${formatAgo(live.at)}` : `Live GPS · ${formatAgo(live.at)}`) : "Waiting for rider's live GPS…"}
        </div>
      )}
    </div>
  );
}
