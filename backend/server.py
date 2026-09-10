from dotenv import load_dotenv
from pathlib import Path
import os

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, UploadFile, File, Form, Query, Header
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response as StarletteResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import logging, uuid, bcrypt, jwt, requests, io, qrcode, hmac, hashlib, math, httpx

from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "laguna-farm"

PAYMONGO_SECRET_KEY = os.environ.get("PAYMONGO_SECRET_KEY", "")
PAYMONGO_WEBHOOK_SECRET = os.environ.get("PAYMONGO_WEBHOOK_SECRET", "")

EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "FarmDirect Laguna")

async def send_email(to: str, subject: str, html: str):
    if not to or not EMAIL_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{EMAIL_BASE_URL}/api/v1/email/send",
                                  headers={"X-Email-Key": EMAIL_KEY},
                                  json={"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME})
        r.raise_for_status()
    except Exception as e:
        logger.error(f"email send failed: {e}")

def order_email_html(title: str, body: str) -> str:
    return f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f8f4;padding:24px;font-family:Arial,sans-serif">
<tr><td align="center"><table width="480" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;overflow:hidden">
<tr><td style="background:#2D5A40;padding:20px 24px;color:#fff;font-size:20px;font-weight:bold">🌱 FarmDirect Laguna</td></tr>
<tr><td style="padding:24px"><h2 style="margin:0 0 12px;color:#16281b">{title}</h2>
<p style="margin:0;color:#59685e;font-size:15px;line-height:1.6">{body}</p></td></tr>
<tr><td style="padding:16px 24px;background:#ebe8e0;color:#59685e;font-size:12px">Farm-fresh from Laguna's farmers.</td></tr>
</table></td></tr></table>"""

def create_paymongo_session(amount_centavos: int, order_id: str, origin_url: str,
                            payment_method_types: list | None = None,
                            success_url: str | None = None,
                            cancel_url: str | None = None) -> dict:
    pmt = payment_method_types or ["gcash"]
    payload = {"data": {"attributes": {
        "line_items": [{"amount": amount_centavos, "currency": "PHP", "name": "FarmDirect Laguna order", "quantity": 1}],
        "payment_method_types": pmt,
        "success_url": success_url or f"{origin_url}/gcash-pay/{order_id}",
        "cancel_url": cancel_url or f"{origin_url}/gcash-pay/{order_id}",
        "reference_number": order_id,
        "metadata": {"order_id": order_id},
        "show_line_items": True,
    }}}
    r = requests.post("https://api.paymongo.com/v1/checkout_sessions",
                      auth=(PAYMONGO_SECRET_KEY, ""),
                      headers={"Content-Type": "application/json",
                               "Idempotency-Key": hashlib.sha256(f"checkout:{order_id}:{','.join(pmt)}".encode()).hexdigest()},
                      json=payload, timeout=20)
    r.raise_for_status()
    body = r.json()["data"]
    return {"id": body["id"], "checkout_url": body["attributes"]["checkout_url"]}

def paymongo_retrieve_session(session_id: str) -> dict:
    r = requests.get(f"https://api.paymongo.com/v1/checkout_sessions/{session_id}",
                     auth=(PAYMONGO_SECRET_KEY, ""), timeout=20)
    r.raise_for_status()
    return r.json().get("data", {})

def paymongo_refund(payment_id: str, amount_centavos: int, order_id: str, reason: str = "requested_by_customer") -> dict:
    payload = {"data": {"attributes": {
        "amount": amount_centavos,
        "payment_id": payment_id,
        "reason": reason,
        "notes": f"Refund for order {order_id[:8]}",
    }}}
    r = requests.post("https://api.paymongo.com/v1/refunds",
                      auth=(PAYMONGO_SECRET_KEY, ""),
                      headers={"Content-Type": "application/json",
                               "Idempotency-Key": hashlib.sha256(f"refund:{order_id}:{payment_id}".encode()).hexdigest()},
                      json=payload, timeout=25)
    r.raise_for_status()
    return r.json().get("data", {})

def verify_paymongo_signature(raw: bytes, header: str) -> bool:
    if not header or not PAYMONGO_WEBHOOK_SECRET:
        return False
    parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
    timestamp = parts.get("t")
    supplied = parts.get("li" if PAYMONGO_SECRET_KEY.startswith("sk_live_") else "te")
    if not timestamp or not supplied:
        return False
    signed = f"{timestamp}.".encode() + raw
    expected = hmac.new(PAYMONGO_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)

# ----------------------- Shipping fee (Laguna) -----------------------
LAGUNA_CENTER = (14.17, 121.33)
MUNICIPALITIES = {
    "Calamba": (14.2117, 121.1653), "Los Baños": (14.1699, 121.2415),
    "Santa Cruz": (14.2813, 121.4162), "San Pablo": (14.0683, 121.3256),
    "Paete": (14.365, 121.484), "Nagcarlan": (14.136, 121.417), "Liliw": (14.129, 121.435),
    "Bay": (14.184, 121.283), "Cabuyao": (14.275, 121.124), "Biñan": (14.337, 121.081),
    "Santa Rosa": (14.312, 121.111), "San Pedro": (14.359, 121.048),
}

def match_coords(s):
    if not s:
        return LAGUNA_CENTER
    sl = s.lower()
    for name, c in MUNICIPALITIES.items():
        if name.lower() in sl:
            return c
    return LAGUNA_CENTER

def match_town(s):
    if not s:
        return None
    sl = s.lower()
    for name in MUNICIPALITIES:
        if name.lower() in sl:
            return name
    return None

def haversine(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))

def fee_from_distance(km):
    # Lalamove-style motorcycle rate: ₱49 base + ₱6/km (0-5km) then ₱5/km
    fee = 49 + (6 * km if km <= 5 else 30 + 5 * (km - 5))
    return float(round(fee))

LOCAL_RATE = 30.0

def shipping_fee_for(pickup_town, buyer_town, pickup, dropoff):
    if pickup_town and buyer_town and pickup_town == buyer_town:
        return LOCAL_RATE  # same municipality — cheaper local rate
    return fee_from_distance(haversine(pickup, dropoff))

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------- Object Storage -----------------------
storage_key = None

def init_storage():
    global storage_key
    if storage_key:
        return storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    storage_key = resp.json()["storage_key"]
    return storage_key

def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = requests.put(f"{STORAGE_URL}/objects/{path}",
                        headers={"X-Storage-Key": key, "Content-Type": content_type},
                        data=data, timeout=120)
    resp.raise_for_status()
    return resp.json()

def get_object(path: str):
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}",
                        headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")

# ----------------------- Auth helpers -----------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": datetime.now(timezone.utc) + timedelta(days=7), "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def serialize_user(user: dict) -> dict:
    return {"id": str(user["_id"]), "email": user["email"], "name": user.get("name"),
            "role": user.get("role"), "phone": user.get("phone"), "address": user.get("address"),
            "farm_name": user.get("farm_name"),
            "gcash_number": user.get("gcash_number"), "gcash_name": user.get("gcash_name"),
            "gcash_qr_url": user.get("gcash_qr_url")}

async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def require_seller(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("seller", "admin"):
        raise HTTPException(status_code=403, detail="Seller access required")
    return user

async def require_seller_only(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "seller":
        raise HTTPException(status_code=403, detail="Only sellers can perform this action. Admins have view-only access.")
    return user

async def require_rider(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "rider":
        raise HTTPException(status_code=403, detail="Rider access required")
    return user

# ----------------------- Models -----------------------
class RegisterInput(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "buyer"
    phone: Optional[str] = None
    address: Optional[str] = None
    farm_name: Optional[str] = None
    vehicle: Optional[str] = None

class LoginInput(BaseModel):
    email: EmailStr
    password: str

class ProductInput(BaseModel):
    name: str
    description: str = ""
    category: str = "Vegetables"
    price: float
    unit: str = "kg"
    stock: int = 0
    image_url: Optional[str] = None
    location: str = "Laguna"

class OrderItem(BaseModel):
    product_id: str
    name: str
    price: float
    quantity: int
    seller_id: str
    image_url: Optional[str] = None

class CheckoutInput(BaseModel):
    items: List[OrderItem]
    delivery_address: str = ""
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    contact_phone: str
    payment_method: str  # "online" or "cod"
    fulfillment_type: str = "delivery"  # "delivery" or "pickup"
    pickup_location: Optional[str] = None
    origin_url: str

class StatusUpdate(BaseModel):
    status: str

class RiderAssign(BaseModel):
    rider_id: str

class GcashProfile(BaseModel):
    gcash_number: str
    gcash_name: str
    gcash_qr_url: Optional[str] = None

class GcashReference(BaseModel):
    reference: str
    proof_url: Optional[str] = None

class ReviewInput(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = ""

class CustomRider(BaseModel):
    name: str
    phone: str = ""
    vehicle: str = "Motorcycle"

class ShippingQuoteInput(BaseModel):
    fulfillment_type: str = "delivery"
    product_id: Optional[str] = None
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    delivery_address: str = ""

class RiderLocation(BaseModel):
    lat: float
    lng: float

class StockUpdate(BaseModel):
    stock: int = Field(ge=0)

ORDER_STAGES = ["pending", "confirmed", "packed", "rider_assigned", "out_for_delivery", "delivered", "ready_for_pickup", "picked_up", "cancelled"]

# ----------------------- Auth routes -----------------------
@api_router.post("/auth/register")
async def register(data: RegisterInput, response: Response):
    email = data.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    role = data.role if data.role in ("buyer", "seller", "rider") else "buyer"
    doc = {"email": email, "password_hash": hash_password(data.password), "name": data.name,
           "role": role, "phone": data.phone, "address": data.address, "farm_name": data.farm_name,
           "created_at": datetime.now(timezone.utc).isoformat()}
    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    if role == "rider":
        coords = match_coords(data.address)
        await db.riders.insert_one({"id": str(uuid.uuid4()), "rider_user_id": str(result.inserted_id),
                                    "name": data.name, "phone": data.phone or "",
                                    "vehicle": data.vehicle or "Motorcycle",
                                    "zone": data.address or "Laguna", "lat": coords[0], "lng": coords[1]})
    token = create_access_token(str(result.inserted_id), email)
    response.set_cookie("access_token", token, httponly=True, secure=True, samesite="none", max_age=604800, path="/")
    return {"token": token, "user": serialize_user(doc)}

@api_router.post("/auth/login")
async def login(data: LoginInput, response: Response):
    email = data.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(str(user["_id"]), email)
    response.set_cookie("access_token", token, httponly=True, secure=True, samesite="none", max_age=604800, path="/")
    return {"token": token, "user": serialize_user(user)}

@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return serialize_user(user)

@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}

# ----------------------- File upload -----------------------
@api_router.post("/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(require_seller)):
    ext = file.filename.split(".")[-1].lower() if "." in file.filename else "bin"
    path = f"{APP_NAME}/uploads/{str(user['_id'])}/{uuid.uuid4()}.{ext}"
    data = await file.read()
    result = put_object(path, data, file.content_type or "application/octet-stream")
    doc = {"id": str(uuid.uuid4()), "storage_path": result["path"],
           "content_type": file.content_type, "is_deleted": False,
           "created_at": datetime.now(timezone.utc).isoformat()}
    await db.files.insert_one(doc)
    backend = os.environ.get("REACT_APP_BACKEND_URL", "")
    return {"image_url": f"/api/files/{result['path']}"}

@api_router.get("/files/{path:path}")
async def download(path: str):
    record = await db.files.find_one({"storage_path": path, "is_deleted": False})
    if not record:
        raise HTTPException(status_code=404, detail="File not found")
    data, content_type = get_object(path)
    return StarletteResponse(content=data, media_type=record.get("content_type", content_type))

# ----------------------- Products -----------------------
@api_router.get("/products")
async def list_products(category: Optional[str] = None, search: Optional[str] = None, seller_id: Optional[str] = None):
    q = {"is_deleted": {"$ne": True}}
    if category and category != "All":
        q["category"] = category
    if seller_id:
        q["seller_id"] = seller_id
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    products = await db.products.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return products

@api_router.get("/products/{product_id}")
async def get_product(product_id: str):
    p = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    srevs = await db.reviews.find({"seller_id": p["seller_id"]}).to_list(2000)
    p["seller_rating"] = round(sum(r["rating"] for r in srevs) / len(srevs), 1) if srevs else 0
    p["seller_review_count"] = len(srevs)
    return p

@api_router.get("/products/{product_id}/reviews")
async def list_reviews(product_id: str):
    return await db.reviews.find({"product_id": product_id}, {"_id": 0}).sort("created_at", -1).to_list(500)

@api_router.get("/products/{product_id}/can-review")
async def can_review(product_id: str, user: dict = Depends(get_current_user)):
    delivered = await db.orders.find_one({"buyer_id": str(user["_id"]), "items.product_id": product_id, "status": {"$in": ["delivered", "picked_up"]}})
    reviewed = await db.reviews.find_one({"product_id": product_id, "buyer_id": str(user["_id"])})
    return {"can_review": bool(delivered), "already_reviewed": bool(reviewed)}

@api_router.post("/products/{product_id}/reviews")
async def add_review(product_id: str, data: ReviewInput, user: dict = Depends(get_current_user)):
    product = await db.products.find_one({"id": product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    purchased = await db.orders.find_one({"buyer_id": str(user["_id"]), "items.product_id": product_id, "status": {"$in": ["delivered", "picked_up"]}})
    if not purchased:
        raise HTTPException(status_code=403, detail="You can review a product only after your order has been delivered")
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.reviews.find_one({"product_id": product_id, "buyer_id": str(user["_id"])})
    if existing:
        await db.reviews.update_one({"id": existing["id"]}, {"$set": {"rating": data.rating, "comment": data.comment, "created_at": now}})
    else:
        await db.reviews.insert_one({"id": str(uuid.uuid4()), "product_id": product_id, "seller_id": product["seller_id"],
                                     "buyer_id": str(user["_id"]), "buyer_name": user.get("name"),
                                     "rating": data.rating, "comment": data.comment, "created_at": now})
    revs = await db.reviews.find({"product_id": product_id}).to_list(1000)
    avg = round(sum(r["rating"] for r in revs) / len(revs), 1) if revs else 0
    await db.products.update_one({"id": product_id}, {"$set": {"rating_avg": avg, "rating_count": len(revs)}})
    return {"ok": True, "rating_avg": avg, "rating_count": len(revs)}

@api_router.get("/seller/earnings")
async def seller_earnings(user: dict = Depends(require_seller)):
    uid = str(user["_id"])
    orders = await db.orders.find({"seller_ids": uid}, {"_id": 0}).to_list(2000)
    breakdown = {"online": 0.0, "gcash": 0.0, "cod": 0.0}
    pending = 0.0
    rows = []
    for o in orders:
        if o.get("status") == "cancelled":
            continue
        amt = round(sum(i["price"] * i["quantity"] for i in o["items"] if i["seller_id"] == uid), 2)
        method = o.get("payment_method")
        realized = False
        if method in ("online", "gcash") and o.get("payment_status") == "paid":
            breakdown["online" if method == "online" else "gcash"] += amt
            realized = True
        elif method == "cod" and o.get("status") in ("delivered", "picked_up"):
            breakdown["cod"] += amt
            realized = True
        else:
            pending += amt
        rows.append({"order_id": o["id"], "date": o["created_at"], "method": method,
                     "status": o["status"], "payment_status": o.get("payment_status"),
                     "buyer_name": o.get("buyer_name"), "amount": amt, "realized": realized})
    total = round(sum(breakdown.values()), 2)
    breakdown = {k: round(v, 2) for k, v in breakdown.items()}
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {"breakdown": breakdown, "total": total, "pending": round(pending, 2), "orders": rows}

@api_router.post("/products")
async def create_product(data: ProductInput, user: dict = Depends(require_seller_only)):
    doc = data.model_dump()
    doc.update({"id": str(uuid.uuid4()), "seller_id": str(user["_id"]),
                "seller_name": user.get("farm_name") or user.get("name"),
                "is_deleted": False, "created_at": datetime.now(timezone.utc).isoformat()})
    await db.products.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc

@api_router.put("/products/{product_id}")
async def update_product(product_id: str, data: ProductInput, user: dict = Depends(require_seller_only)):
    p = await db.products.find_one({"id": product_id})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    if p["seller_id"] != str(user["_id"]) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not your product")
    await db.products.update_one({"id": product_id}, {"$set": data.model_dump()})
    updated = await db.products.find_one({"id": product_id}, {"_id": 0})
    return updated

@api_router.delete("/products/{product_id}")
async def delete_product(product_id: str, user: dict = Depends(require_seller_only)):
    p = await db.products.find_one({"id": product_id})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    if p["seller_id"] != str(user["_id"]) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not your product")
    await db.products.update_one({"id": product_id}, {"$set": {"is_deleted": True}})
    return {"ok": True}

@api_router.patch("/products/{product_id}/stock")
async def update_stock(product_id: str, data: StockUpdate, user: dict = Depends(require_seller_only)):
    p = await db.products.find_one({"id": product_id})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    if p["seller_id"] != str(user["_id"]) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not your product")
    await db.products.update_one({"id": product_id}, {"$set": {"stock": data.stock}})
    return await db.products.find_one({"id": product_id}, {"_id": 0})

# ----------------------- Riders -----------------------
@api_router.get("/riders")
async def list_riders():
    return await db.riders.find({}, {"_id": 0}).to_list(100)

# ----------------------- Orders -----------------------
def order_total(items):
    return round(sum(i["price"] * i["quantity"] for i in items), 2)

async def restore_stock(order):
    if order.get("stock_restored"):
        return
    for i in order.get("items", []):
        await db.products.update_one({"id": i["product_id"]}, {"$inc": {"stock": i["quantity"]}})
    await db.orders.update_one({"id": order["id"]}, {"$set": {"stock_restored": True}})

@api_router.post("/checkout")
async def checkout(data: CheckoutInput, request: Request, user: dict = Depends(get_current_user)):
    if not data.items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    items = [i.model_dump() for i in data.items]
    subtotal = order_total(items)
    shipping_fee = 0.0
    if data.fulfillment_type == "delivery":
        first = await db.products.find_one({"id": items[0]["product_id"]})
        seller_loc = first.get("location") if first else None
        pickup = match_coords(seller_loc)
        if data.delivery_lat is not None and data.delivery_lng is not None:
            dropoff = (data.delivery_lat, data.delivery_lng)
        else:
            dropoff = match_coords(data.delivery_address)
        shipping_fee = shipping_fee_for(match_town(seller_loc), match_town(data.delivery_address), pickup, dropoff)
    total = round(subtotal + shipping_fee, 2)
    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    order = {"id": order_id, "buyer_id": str(user["_id"]), "buyer_name": user.get("name"),
             "items": items, "subtotal": subtotal, "shipping_fee": shipping_fee, "total": total, "delivery_address": data.delivery_address,
             "delivery_lat": data.delivery_lat, "delivery_lng": data.delivery_lng,
             "fulfillment_type": data.fulfillment_type, "pickup_location": data.pickup_location,
             "contact_phone": data.contact_phone, "payment_method": data.payment_method,
             "payment_status": "pending", "status": "pending", "rider": None,
             "seller_ids": list({i["seller_id"] for i in items}),
             "created_at": now, "updated_at": now, "history": [{"status": "pending", "at": now}]}

    # decrement stock
    for i in items:
        await db.products.update_one({"id": i["product_id"]}, {"$inc": {"stock": -i["quantity"]}})

    if data.payment_method == "cod":
        order["payment_status"] = "cod_pending"
        await db.orders.insert_one(dict(order))
        return {"order_id": order_id, "payment_method": "cod"}

    if data.payment_method == "gcash":
        if PAYMONGO_SECRET_KEY:
            centavos = int(round(total * 100))
            try:
                session = create_paymongo_session(centavos, order_id, data.origin_url)
            except Exception as e:
                for i in items:
                    await db.products.update_one({"id": i["product_id"]}, {"$inc": {"stock": i["quantity"]}})
                logger.error(f"paymongo error: {e}")
                raise HTTPException(status_code=400, detail="Could not start GCash payment. Please try again.")
            order["payment_status"] = "gcash_pending"
            order["gcash_mode"] = "auto"
            order["payment_provider"] = "paymongo"
            order["paymongo_session_id"] = session["id"]
            await db.orders.insert_one(dict(order))
            return {"order_id": order_id, "gcash_mode": "auto", "checkout_url": session["checkout_url"]}
        # manual direct-to-seller GCash fallback
        seller_id = items[0]["seller_id"]
        seller = await db.users.find_one({"_id": ObjectId(seller_id)})
        if not seller or not seller.get("gcash_number"):
            for i in items:  # rollback stock
                await db.products.update_one({"id": i["product_id"]}, {"$inc": {"stock": i["quantity"]}})
            raise HTTPException(status_code=400, detail="This seller hasn't set up GCash yet. Please pick another payment method.")
        order["payment_status"] = "gcash_pending"
        order["gcash_mode"] = "manual"
        order["gcash_info"] = {"number": seller.get("gcash_number"), "name": seller.get("gcash_name"), "qr_url": seller.get("gcash_qr_url")}
        await db.orders.insert_one(dict(order))
        return {"order_id": order_id, "payment_method": "gcash", "gcash_mode": "manual"}

    # online payment — prefer PayMongo (card + gcash + paymaya); fallback to Stripe
    if PAYMONGO_SECRET_KEY:
        centavos = int(round(total * 100))
        success_url = f"{data.origin_url}/payment/success?order_id={order_id}&provider=paymongo"
        cancel_url = f"{data.origin_url}/payment/cancel?order_id={order_id}&provider=paymongo"
        try:
            session = create_paymongo_session(
                centavos, order_id, data.origin_url,
                payment_method_types=["card", "gcash", "paymaya"],
                success_url=success_url, cancel_url=cancel_url,
            )
        except Exception as e:
            for i in items:
                await db.products.update_one({"id": i["product_id"]}, {"$inc": {"stock": i["quantity"]}})
            logger.error(f"paymongo online error: {e}")
            raise HTTPException(status_code=400, detail="Could not start online payment. Please try again.")
        order["payment_provider"] = "paymongo"
        order["paymongo_session_id"] = session["id"]
        await db.orders.insert_one(dict(order))
        return {"order_id": order_id, "payment_method": "online", "provider": "paymongo",
                "checkout_url": session["checkout_url"]}

    host_url = str(request.base_url)
    webhook_url = f"{host_url}api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=os.environ["STRIPE_API_KEY"], webhook_url=webhook_url)
    success_url = f"{data.origin_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{data.origin_url}/payment/cancel"
    req = CheckoutSessionRequest(amount=float(total), currency="php",
                                 success_url=success_url, cancel_url=cancel_url,
                                 metadata={"order_id": order_id, "user_id": str(user["_id"])})
    session = await stripe_checkout.create_checkout_session(req)
    order["session_id"] = session.session_id
    order["payment_provider"] = "stripe"
    await db.orders.insert_one(dict(order))
    await db.payment_transactions.insert_one({
        "session_id": session.session_id, "order_id": order_id, "user_id": str(user["_id"]),
        "amount": float(total), "currency": "php", "status": "initiated",
        "payment_status": "pending", "created_at": now, "updated_at": now})
    return {"order_id": order_id, "checkout_url": session.url, "session_id": session.session_id, "provider": "stripe"}

@api_router.get("/payments/status/{session_id}")
async def payment_status(session_id: str, request: Request):
    record = await db.payment_transactions.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if record.get("payment_status") != "paid":
        host_url = str(request.base_url)
        stripe_checkout = StripeCheckout(api_key=os.environ["STRIPE_API_KEY"], webhook_url=f"{host_url}api/webhook/stripe")
        try:
            status = await stripe_checkout.get_checkout_status(session_id)
            if status.payment_status == "paid":
                now = datetime.now(timezone.utc).isoformat()
                await db.payment_transactions.update_one(
                    {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now}})
                await db.orders.update_one(
                    {"id": record["order_id"], "payment_status": {"$ne": "paid"}},
                    {"$set": {"payment_status": "paid", "updated_at": now}})
                record = await db.payment_transactions.find_one({"session_id": session_id})
            elif status.status == "expired":
                order = await db.orders.find_one({"id": record["order_id"]})
                if order:
                    await restore_stock(order)
        except Exception as e:
            logger.error(f"stripe status err: {e}")
    return {"session_id": session_id, "status": record["status"], "payment_status": record["payment_status"], "order_id": record.get("order_id")}

@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("Stripe-Signature")
    host_url = str(request.base_url)
    stripe_checkout = StripeCheckout(api_key=os.environ["STRIPE_API_KEY"], webhook_url=f"{host_url}api/webhook/stripe")
    try:
        wh = await stripe_checkout.handle_webhook(body, sig)
    except Exception as e:
        logger.error(f"webhook err: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook")
    if wh.payment_status == "paid":
        now = datetime.now(timezone.utc).isoformat()
        await db.payment_transactions.update_one(
            {"session_id": wh.session_id, "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now}})
        rec = await db.payment_transactions.find_one({"session_id": wh.session_id})
        if rec:
            await db.orders.update_one(
                {"id": rec["order_id"], "payment_status": {"$ne": "paid"}},
                {"$set": {"payment_status": "paid", "updated_at": now}})
    elif wh.payment_status in ("expired", "failed", "unpaid"):
        rec = await db.payment_transactions.find_one({"session_id": wh.session_id})
        if rec:
            order = await db.orders.find_one({"id": rec["order_id"]})
            if order and order.get("payment_status") != "paid":
                await restore_stock(order)
    return {"status": "ok"}

@api_router.post("/webhook/paymongo")
async def paymongo_webhook(request: Request):
    raw = await request.body()
    if not verify_paymongo_signature(raw, request.headers.get("Paymongo-Signature")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    event = await request.json()
    attrs = event.get("data", {}).get("attributes", {})
    etype = attrs.get("type")
    resource = attrs.get("data", {})
    if etype == "checkout_session.payment.paid":
        a = resource.get("attributes", {})
        oid = a.get("reference_number") or a.get("metadata", {}).get("order_id")
        pay_id = None
        for p in (a.get("payments") or []):
            if (p.get("attributes") or {}).get("status") == "paid":
                pay_id = p.get("id"); break
        if oid:
            now = datetime.now(timezone.utc).isoformat()
            update = {"payment_status": "paid", "updated_at": now}
            if pay_id:
                update["paymongo_payment_id"] = pay_id
            await db.orders.update_one({"id": oid, "payment_status": {"$ne": "paid"}},
                {"$set": update})
    return {"received": True}

@api_router.get("/paymongo/status/{order_id}")
async def paymongo_status(order_id: str, user: dict = Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    if str(user["_id"]) != o.get("buyer_id") and user.get("role") not in ("admin", "seller"):
        raise HTTPException(status_code=403, detail="Not allowed")
    if o.get("payment_status") == "paid":
        return {"order_id": order_id, "payment_status": "paid",
                "paymongo_payment_id": o.get("paymongo_payment_id")}
    sid = o.get("paymongo_session_id")
    if not sid or not PAYMONGO_SECRET_KEY:
        return {"order_id": order_id, "payment_status": o.get("payment_status", "pending")}
    try:
        sess = paymongo_retrieve_session(sid)
    except Exception as e:
        logger.error(f"paymongo retrieve err: {e}")
        return {"order_id": order_id, "payment_status": o.get("payment_status", "pending")}
    attrs = sess.get("attributes", {})
    payments = attrs.get("payments") or []
    paid_payment = next((p for p in payments if (p.get("attributes") or {}).get("status") == "paid"), None)
    if paid_payment:
        now = datetime.now(timezone.utc).isoformat()
        await db.orders.update_one(
            {"id": order_id, "payment_status": {"$ne": "paid"}},
            {"$set": {"payment_status": "paid",
                      "paymongo_payment_id": paid_payment.get("id"),
                      "updated_at": now}})
        return {"order_id": order_id, "payment_status": "paid",
                "paymongo_payment_id": paid_payment.get("id")}
    return {"order_id": order_id, "payment_status": o.get("payment_status", "pending")}

@api_router.get("/orders")
async def my_orders(user: dict = Depends(get_current_user)):
    uid = str(user["_id"])
    if user.get("role") == "admin":
        orders = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    elif user.get("role") == "seller":
        orders = await db.orders.find({"seller_ids": uid}, {"_id": 0}).sort("created_at", -1).to_list(500)
    else:
        orders = await db.orders.find({"buyer_id": uid}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return orders

@api_router.get("/orders/{order_id}")
async def get_order(order_id: str, user: dict = Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    uid = str(user["_id"])
    if user.get("role") == "buyer" and o["buyer_id"] != uid:
        raise HTTPException(status_code=403, detail="Not your order")
    return o

@api_router.put("/orders/{order_id}/status")
async def update_status(order_id: str, data: StatusUpdate, user: dict = Depends(require_seller_only)):
    if data.status not in ORDER_STAGES:
        raise HTTPException(status_code=400, detail="Invalid status")
    o = await db.orders.find_one({"id": order_id})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id},
        {"$set": {"status": data.status, "updated_at": now},
         "$push": {"history": {"status": data.status, "at": now}}})
    return await db.orders.find_one({"id": order_id}, {"_id": 0})

@api_router.put("/orders/{order_id}/assign-rider")
async def assign_rider(order_id: str, data: RiderAssign, user: dict = Depends(require_seller_only)):
    rider = await db.riders.find_one({"id": data.rider_id}, {"_id": 0})
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id},
        {"$set": {"rider": rider, "status": "rider_assigned", "updated_at": now},
         "$push": {"history": {"status": "rider_assigned", "at": now}}})
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if rider.get("rider_user_id"):
        ruser = await db.users.find_one({"_id": ObjectId(rider["rider_user_id"])})
        if ruser and ruser.get("email"):
            addr = order.get("delivery_address") or "the buyer's address"
            await send_email(ruser["email"], f"New delivery assigned — order #{order_id[:8]}",
                order_email_html("You've got a new delivery! 🛵",
                    f"Hi {rider.get('name')}, you've been assigned to deliver order "
                    f"<b>#{order_id[:8]}</b> to <b>{addr}</b>. Open your Rider portal to view "
                    f"the route, buyer contact, and start the delivery. "
                    f"Delivery fee: <b>₱{order.get('shipping_fee', 0):.2f}</b> (100% yours)."))
    return order

@api_router.put("/orders/{order_id}/assign-custom-rider")
async def assign_custom_rider(order_id: str, data: CustomRider, user: dict = Depends(require_seller)):
    o = await db.orders.find_one({"id": order_id})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    now = datetime.now(timezone.utc).isoformat()
    rider = {"id": str(uuid.uuid4()), "name": data.name, "phone": data.phone,
             "vehicle": data.vehicle, "zone": "—", "custom": True}
    await db.orders.update_one({"id": order_id},
        {"$set": {"rider": rider, "status": "rider_assigned", "updated_at": now},
         "$push": {"history": {"status": "rider_assigned", "at": now, "note": f"Rider {data.name} ({data.vehicle}) assigned"}}})
    return await db.orders.find_one({"id": order_id}, {"_id": 0})

@api_router.post("/shipping-quote")
async def shipping_quote(data: ShippingQuoteInput):
    if data.fulfillment_type == "pickup":
        return {"shipping_fee": 0.0, "distance_km": 0, "local_rate": False}
    pickup = LAGUNA_CENTER
    seller_town = None
    if data.product_id:
        p = await db.products.find_one({"id": data.product_id})
        if p:
            pickup = match_coords(p.get("location"))
            seller_town = match_town(p.get("location"))
    if data.delivery_lat is not None and data.delivery_lng is not None:
        dropoff = (data.delivery_lat, data.delivery_lng)
    else:
        dropoff = match_coords(data.delivery_address)
    buyer_town = match_town(data.delivery_address)
    dist = haversine(pickup, dropoff)
    local = bool(seller_town and buyer_town and seller_town == buyer_town)
    fee = LOCAL_RATE if local else fee_from_distance(dist)
    return {"shipping_fee": fee, "distance_km": round(dist, 1), "local_rate": local}

@api_router.get("/rider/orders")
async def rider_orders(user: dict = Depends(require_rider)):
    uid = str(user["_id"])
    return await db.orders.find({"rider.rider_user_id": uid}, {"_id": 0}).sort("created_at", -1).to_list(500)

@api_router.put("/orders/{order_id}/rider-status")
async def rider_update_status(order_id: str, data: StatusUpdate, user: dict = Depends(require_rider)):
    if data.status not in ("out_for_delivery", "delivered"):
        raise HTTPException(status_code=400, detail="Riders can only mark Out for Delivery or Delivered")
    o = await db.orders.find_one({"id": order_id})
    if not o or (o.get("rider") or {}).get("rider_user_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your delivery")
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id},
        {"$set": {"status": data.status, "updated_at": now},
         "$push": {"history": {"status": data.status, "at": now}}})
    buyer = await db.users.find_one({"_id": ObjectId(o["buyer_id"])})
    rider_name = (o.get("rider") or {}).get("name", "Your rider")
    if buyer and buyer.get("email"):
        if data.status == "out_for_delivery":
            await send_email(buyer["email"], f"Your FarmDirect order #{order_id[:8]} is on the way!",
                order_email_html("Your order is on the way! 🛵",
                    f"{rider_name} has started your delivery to <b>{o.get('delivery_address')}</b>. "
                    f"Track the rider live in your Orders page."))
        elif data.status == "delivered":
            await send_email(buyer["email"], f"Your FarmDirect order #{order_id[:8]} was delivered",
                order_email_html("Delivered! ✅",
                    f"Your order was delivered to <b>{o.get('delivery_address')}</b>. Enjoy your farm-fresh goods, "
                    f"and don't forget to leave a review!"))
    return await db.orders.find_one({"id": order_id}, {"_id": 0})

@api_router.put("/orders/{order_id}/rider-location")
async def rider_update_location(order_id: str, data: RiderLocation, user: dict = Depends(require_rider)):
    o = await db.orders.find_one({"id": order_id})
    if not o or (o.get("rider") or {}).get("rider_user_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your delivery")
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id},
        {"$set": {"rider_location": {"lat": data.lat, "lng": data.lng, "at": now}}})
    if o.get("status") == "out_for_delivery" and not o.get("arriving_notified"):
        dropoff = (o["delivery_lat"], o["delivery_lng"]) if o.get("delivery_lat") is not None else match_coords(o.get("delivery_address"))
        if haversine((data.lat, data.lng), dropoff) < 1.5:
            await db.orders.update_one({"id": order_id}, {"$set": {"arriving_notified": True}})
            buyer = await db.users.find_one({"_id": ObjectId(o["buyer_id"])})
            if buyer and buyer.get("email"):
                await send_email(buyer["email"], f"Your FarmDirect order #{order_id[:8]} is arriving!",
                    order_email_html("Almost there! 📍",
                        "Your rider is less than 1.5 km away. Please get ready to receive your order."))
    return {"ok": True}

@api_router.get("/rider/earnings")
async def rider_earnings(user: dict = Depends(require_rider)):
    uid = str(user["_id"])
    orders = await db.orders.find({"rider.rider_user_id": uid}, {"_id": 0}).to_list(1000)
    delivered = [o for o in orders if o.get("status") == "delivered"]
    fees = round(sum((o.get("shipping_fee") or 0) for o in delivered), 2)
    active = len([o for o in orders if o.get("status") in ("rider_assigned", "out_for_delivery")])
    return {"completed": len(delivered), "active": active, "fees_earned": fees, "assigned": len(orders)}

async def _issue_refund_for_order(o: dict) -> dict:
    """Attempts to refund a paid order via its original gateway.
    Returns dict with keys: ok, refund_id (or None), message, provider."""
    method = o.get("payment_method")
    if o.get("payment_status") != "paid" or method not in ("online", "gcash"):
        return {"ok": False, "message": "Order is not eligible for refund", "provider": None}
    provider = o.get("payment_provider") or ("paymongo" if o.get("paymongo_session_id") else "stripe")

    # If we don't yet have the paymongo_payment_id, retrieve it from the session
    pay_id = o.get("paymongo_payment_id")
    if provider == "paymongo" and not pay_id and o.get("paymongo_session_id") and PAYMONGO_SECRET_KEY:
        try:
            sess = paymongo_retrieve_session(o["paymongo_session_id"])
            for p in (sess.get("attributes", {}).get("payments") or []):
                if (p.get("attributes") or {}).get("status") == "paid":
                    pay_id = p.get("id"); break
            if pay_id:
                await db.orders.update_one({"id": o["id"]}, {"$set": {"paymongo_payment_id": pay_id}})
        except Exception as e:
            logger.error(f"paymongo retrieve for refund failed: {e}")

    if provider == "paymongo":
        if not PAYMONGO_SECRET_KEY:
            return {"ok": False, "message": "PayMongo not configured on server", "provider": provider}
        if not pay_id:
            return {"ok": False, "message": "No PayMongo payment id on this order — cannot refund", "provider": provider}
        centavos = int(round(float(o.get("total") or 0) * 100))
        try:
            refund = paymongo_refund(pay_id, centavos, o["id"])
            return {"ok": True, "refund_id": refund.get("id"),
                    "message": "Refund submitted via PayMongo",
                    "provider": provider}
        except requests.HTTPError as e:
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                pass
            logger.error(f"paymongo refund http err: {e} body={body}")
            return {"ok": False, "message": f"PayMongo refund failed: {body or str(e)}", "provider": provider}
        except Exception as e:
            logger.error(f"paymongo refund err: {e}")
            return {"ok": False, "message": f"Refund failed: {e}", "provider": provider}

    # Stripe refund path (legacy)
    return {"ok": False, "message": "Stripe refunds not implemented in this build", "provider": provider}


@api_router.put("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, user: dict = Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    uid = str(user["_id"])
    is_owner = o["buyer_id"] == uid
    is_seller = user.get("role") == "seller" and uid in o.get("seller_ids", [])
    if not (is_owner or is_seller):
        raise HTTPException(status_code=403, detail="Not allowed to cancel this order")
    if o.get("status") in ("delivered", "picked_up", "cancelled"):
        raise HTTPException(status_code=400, detail="This order can no longer be cancelled")
    if o.get("status") in ("out_for_delivery",):
        raise HTTPException(status_code=400, detail="Cannot cancel while the rider is out for delivery")

    now = datetime.now(timezone.utc).isoformat()
    refund_info = None
    # If paid via online/gcash → attempt refund
    if o.get("payment_status") == "paid" and o.get("payment_method") in ("online", "gcash"):
        refund_info = await _issue_refund_for_order(o)
        if not refund_info.get("ok"):
            # Use 409 (Conflict) instead of 502 — Cloudflare intercepts 5xx and replaces the body.
            raise HTTPException(status_code=409, detail=refund_info.get("message") or "Refund failed")

    await restore_stock(o)
    update = {"status": "cancelled", "updated_at": now}
    history_entry = {"status": "cancelled", "at": now}
    if refund_info and refund_info.get("ok"):
        update["payment_status"] = "refunded"
        update["refund_id"] = refund_info.get("refund_id")
        update["refund_provider"] = refund_info.get("provider")
        history_entry["note"] = f"Refund issued via {refund_info.get('provider')}"
    await db.orders.update_one({"id": order_id},
        {"$set": update, "$push": {"history": history_entry}})
    return await db.orders.find_one({"id": order_id}, {"_id": 0})

@api_router.put("/seller/gcash")
async def update_gcash(data: GcashProfile, user: dict = Depends(require_seller_only)):
    await db.users.update_one({"_id": user["_id"]},
        {"$set": {"gcash_number": data.gcash_number, "gcash_name": data.gcash_name, "gcash_qr_url": data.gcash_qr_url}})
    u = await db.users.find_one({"_id": user["_id"]})
    return serialize_user(u)

@api_router.put("/orders/{order_id}/gcash-reference")
async def submit_gcash_ref(order_id: str, data: GcashReference, user: dict = Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    if o["buyer_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your order")
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id},
        {"$set": {"gcash_reference": data.reference, "gcash_proof_url": data.proof_url,
                  "payment_status": "gcash_submitted", "updated_at": now}})
    return await db.orders.find_one({"id": order_id}, {"_id": 0})

@api_router.put("/orders/{order_id}/verify-payment")
async def verify_payment(order_id: str, user: dict = Depends(require_seller_only)):
    o = await db.orders.find_one({"id": order_id})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id},
        {"$set": {"payment_status": "paid", "updated_at": now}})
    return await db.orders.find_one({"id": order_id}, {"_id": 0})

@api_router.get("/gcash-qr/{order_id}")
async def gcash_qr(order_id: str):
    o = await db.orders.find_one({"id": order_id})
    if not o or not o.get("gcash_info"):
        raise HTTPException(status_code=404, detail="No GCash info for this order")
    info = o["gcash_info"]
    payload = f"GCash Payment\nPay to: {info.get('name')}\nNumber: {info.get('number')}\nAmount: PHP {o['total']:.2f}\nRef: {order_id[:8]}"
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StarletteResponse(content=buf.getvalue(), media_type="image/png")

@api_router.get("/seller/stats")
async def seller_stats(user: dict = Depends(require_seller)):
    uid = str(user["_id"])
    products = await db.products.count_documents({"seller_id": uid, "is_deleted": {"$ne": True}})
    orders = await db.orders.find({"seller_ids": uid}, {"_id": 0}).to_list(1000)
    revenue = 0.0
    for o in orders:
        if o.get("payment_status") in ("paid", "cod_pending") and o.get("status") != "cancelled":
            revenue += sum(i["price"] * i["quantity"] for i in o["items"] if i["seller_id"] == uid)
    return {"products": products, "orders": len(orders), "revenue": round(revenue, 2)}

@api_router.get("/")
async def root():
    return {"message": "Laguna FarmDirect API"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_pw = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({"email": admin_email, "password_hash": hash_password(admin_pw),
                                   "name": "Laguna Admin", "role": "admin",
                                   "created_at": datetime.now(timezone.utc).isoformat()})
    legacy_rider_emails = ["kuya.jun@laguna.ph", "kuya.marvin@laguna.ph", "ate.ella@laguna.ph"]
    legacy_rider_users = await db.users.find(
        {"email": {"$in": legacy_rider_emails}}, {"_id": 1}
    ).to_list(len(legacy_rider_emails))
    if legacy_rider_users:
        legacy_user_ids = [str(user["_id"]) for user in legacy_rider_users]
        await db.riders.delete_many({"rider_user_id": {"$in": legacy_user_ids}})
        await db.users.delete_many({"_id": {"$in": [user["_id"] for user in legacy_rider_users]}})
    await db.riders.delete_many({"rider_user_id": {"$exists": False}, "name": {"$in": [
        "Jun Dela Cruz", "Marvin Reyes", "Ella Santos", "Boy Aquino"
    ]}})
    try:
        init_storage()
    except Exception as e:
        logger.error(f"storage init failed: {e}")

@app.on_event("shutdown")
async def shutdown():
    client.close()
