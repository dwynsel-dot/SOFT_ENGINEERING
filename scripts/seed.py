import requests

API = "http://localhost:8001/api"

def reg(email, pw, name, role, extra={}):
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": pw, "name": name, "role": role, **extra})
    if r.status_code == 400:
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw})
    return r.json()["token"]

seller_tok = reg("mang.kanor@laguna.ph", "farmer123", "Mang Kanor", "seller",
                 {"farm_name": "Kanor's Organic Farm", "phone": "0917-100-2003", "address": "Brgy. Bagong Kalsada, Calamba, Laguna"})
reg("aling.nena@laguna.ph", "buyer123", "Aling Nena", "buyer",
    {"phone": "0917-200-3004", "address": "Brgy. Batong Malake, Los Baños, Laguna"})

H = {"Authorization": f"Bearer {seller_tok}"}
IMG = {
  "veg": "https://images.pexels.com/photos/10697692/pexels-photo-10697692.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
  "carrot": "https://images.unsplash.com/photo-1687199129802-3e4cc27baac0?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDJ8MHwxfHNlYXJjaHwxfHxmcmVzaCUyMHZlZ2V0YWJsZXMlMjBtYXJrZXQlMjBzdGFsbHxlbnwwfHx8fDE3ODU1NTQzMDd8MA&ixlib=rb-4.1.0&q=85",
  "market": "https://images.unsplash.com/photo-1779893457658-ef97d16743d8?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDJ8MHwxfHNlYXJjaHw0fHxmcmVzaCUyMHZlZ2V0YWJsZXMlMjBtYXJrZXQlMjBzdGFsbHxlbnwwfHx8fDE3ODU1NTQzMDd8MA&ixlib=rb-4.1.0&q=85",
}
PRODUCTS = [
    {"name": "Fresh Roma Tomatoes", "category": "Vegetables", "price": 65, "unit": "kg", "stock": 40, "location": "Calamba, Laguna", "image_url": IMG["veg"], "description": "Vine-ripened Roma tomatoes, harvested this morning."},
    {"name": "Native Carrots", "category": "Root Crops", "price": 90, "unit": "kg", "stock": 30, "location": "Calamba, Laguna", "image_url": IMG["carrot"], "description": "Sweet, crunchy carrots grown organically."},
    {"name": "Organic Kangkong", "category": "Vegetables", "price": 25, "unit": "bundle", "stock": 60, "location": "Los Baños, Laguna", "image_url": IMG["market"], "description": "Water spinach, freshly cut bundles."},
    {"name": "Laguna Lanzones", "category": "Fruits", "price": 120, "unit": "kg", "stock": 25, "location": "Paete, Laguna", "image_url": IMG["veg"], "description": "Sweet Paete lanzones in season."},
    {"name": "Dinorado Rice", "category": "Rice & Grains", "price": 55, "unit": "kg", "stock": 100, "location": "Santa Cruz, Laguna", "image_url": IMG["market"], "description": "Premium local Dinorado rice, freshly milled."},
    {"name": "Free-Range Eggs", "category": "Dairy & Eggs", "price": 8, "unit": "piece", "stock": 200, "location": "San Pablo, Laguna", "image_url": IMG["carrot"], "description": "Farm-fresh free-range chicken eggs."},
    {"name": "Fresh Lemongrass (Tanglad)", "category": "Herbs", "price": 15, "unit": "bundle", "stock": 50, "location": "Nagcarlan, Laguna", "image_url": IMG["market"], "description": "Aromatic lemongrass for cooking and tea."},
    {"name": "Sweet Camote", "category": "Root Crops", "price": 45, "unit": "kg", "stock": 70, "location": "Liliw, Laguna", "image_url": IMG["veg"], "description": "Sweet potatoes, perfect for kamote-cue."},
]
for p in PRODUCTS:
    r = requests.post(f"{API}/products", json=p, headers=H)
    print(p["name"], r.status_code)
print("done")
