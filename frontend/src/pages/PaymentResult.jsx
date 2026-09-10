import { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import { useCart } from "@/context/CartContext";
import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";

export default function PaymentResult({ cancel }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { clear } = useCart();
  const [state, setState] = useState(cancel ? "cancelled" : "checking");
  const sessionId = params.get("session_id");
  const orderId = params.get("order_id");
  const provider = params.get("provider");

  const poll = useCallback(async (attempt) => {
    if (attempt > 8) { setState("timeout"); return; }
    try {
      if (provider === "paymongo" && orderId) {
        const { data } = await api.get(`/paymongo/status/${orderId}`);
        if (data.payment_status === "paid") { clear(); localStorage.removeItem("pending_order"); setState("success"); return; }
      } else if (sessionId) {
        const { data } = await api.get(`/payments/status/${sessionId}`);
        if (data.payment_status === "paid") { clear(); localStorage.removeItem("pending_order"); setState("success"); return; }
        if (data.status === "expired") { setState("failed"); return; }
      }
    } catch { /* retry */ }
    setTimeout(() => poll(attempt + 1), 2000);
  }, [sessionId, orderId, provider, clear]);

  useEffect(() => {
    if (cancel) return;
    if (!sessionId && !orderId) { setState("failed"); return; }
    poll(0);
  }, [cancel, sessionId, orderId, poll]);

  const views = {
    checking: { icon: <Loader2 className="animate-spin text-primary" size={56} />, title: "Confirming payment…", desc: "Please wait while we verify your transaction." },
    success: { icon: <CheckCircle2 className="text-primary" size={56} />, title: "Payment successful!", desc: "Your order is confirmed and being prepared. Track it in your orders." },
    cancelled: { icon: <XCircle className="text-accent" size={56} />, title: "Payment cancelled", desc: "Your order was not completed. Your cart is still saved." },
    failed: { icon: <XCircle className="text-destructive" size={56} />, title: "Payment failed", desc: "Something went wrong with your payment." },
    timeout: { icon: <Loader2 className="text-muted-foreground" size={56} />, title: "Still processing", desc: "Payment is taking a while. Check your orders shortly." },
  };
  const v = views[state];

  return (
    <div className="max-w-md mx-auto px-4 py-24 text-center" data-testid="payment-result">
      <div className="mx-auto w-fit">{v.icon}</div>
      <h1 className="font-heading font-black text-2xl mt-5" data-testid="payment-status-title">{v.title}</h1>
      <p className="text-muted-foreground mt-2">{v.desc}</p>
      <div className="flex gap-3 justify-center mt-8">
        <Button data-testid="view-orders-btn" onClick={() => navigate("/orders")} className="rounded-full bg-primary hover:bg-primary/90">View orders</Button>
        <Button variant="outline" onClick={() => navigate("/market")} className="rounded-full">Keep shopping</Button>
      </div>
    </div>
  );
}
