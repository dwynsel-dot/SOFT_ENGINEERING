#!/usr/bin/env python3
"""
Backend test suite for PayMongo online payment + refund cancel flow
Tests the FarmDirect Laguna backend API
"""

import requests
import json
import sys
from pymongo import MongoClient

# Base URL from frontend/.env
BASE_URL = "https://map-overlap-fix-1.preview.emergentagent.com/api"

# Test credentials from /app/memory/test_credentials.md
BUYER_EMAIL = "aling.nena@laguna.ph"
BUYER_PASSWORD = "buyer123"
SELLER_EMAIL = "mang.kanor@laguna.ph"
SELLER_PASSWORD = "farmer123"
ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "admin123"

# MongoDB connection
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "farmdirect_laguna"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def log_test(name):
    print(f"\n{Colors.BLUE}{'='*80}{Colors.END}")
    print(f"{Colors.BLUE}TEST: {name}{Colors.END}")
    print(f"{Colors.BLUE}{'='*80}{Colors.END}")

def log_pass(msg):
    print(f"{Colors.GREEN}✅ PASS: {msg}{Colors.END}")

def log_fail(msg):
    print(f"{Colors.RED}❌ FAIL: {msg}{Colors.END}")

def log_info(msg):
    print(f"{Colors.YELLOW}ℹ️  INFO: {msg}{Colors.END}")

def login(email, password):
    """Login and return Bearer token"""
    resp = requests.post(f"{BASE_URL}/auth/login", 
                        json={"email": email, "password": password},
                        timeout=10)
    if resp.status_code != 200:
        log_fail(f"Login failed for {email}: {resp.status_code} - {resp.text}")
        return None
    data = resp.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        log_fail(f"No token in login response for {email}")
        return None
    log_pass(f"Login successful for {email}")
    return token

def get_headers(token):
    """Return headers with Bearer token"""
    return {"Authorization": f"Bearer {token}"}

def get_products(token):
    """Fetch marketplace products"""
    resp = requests.get(f"{BASE_URL}/products", 
                       headers=get_headers(token),
                       timeout=10)
    if resp.status_code != 200:
        log_fail(f"Failed to fetch products: {resp.status_code}")
        return []
    return resp.json()

def find_low_cost_product(products):
    """Find a low-cost product (e.g., Fresh Lemongrass ₱15)"""
    # Sort by price and pick the cheapest
    sorted_products = sorted(products, key=lambda p: float(p.get("price", 999)))
    if not sorted_products:
        return None
    product = sorted_products[0]
    log_info(f"Selected product: {product.get('name')} - ₱{product.get('price')}")
    return product

def create_online_checkout(token, product):
    """Create online checkout order"""
    items = [{
        "product_id": product["id"],
        "name": product["name"],
        "price": float(product["price"]),
        "quantity": 1,
        "seller_id": product["seller_id"],
        "image_url": product.get("image_url", "")
    }]
    
    payload = {
        "items": items,
        "payment_method": "online",
        "fulfillment_type": "pickup",
        "contact_phone": "0917-000-0000",
        "pickup_location": "Test farm",
        "origin_url": "https://example.com"
    }
    
    resp = requests.post(f"{BASE_URL}/checkout",
                        headers=get_headers(token),
                        json=payload,
                        timeout=15)
    return resp

def create_gcash_checkout(token, product):
    """Create GCash checkout order"""
    items = [{
        "product_id": product["id"],
        "name": product["name"],
        "price": float(product["price"]),
        "quantity": 1,
        "seller_id": product["seller_id"],
        "image_url": product.get("image_url", "")
    }]
    
    payload = {
        "items": items,
        "payment_method": "gcash",
        "fulfillment_type": "pickup",
        "contact_phone": "0917-000-0000",
        "pickup_location": "Test farm",
        "origin_url": "https://example.com"
    }
    
    resp = requests.post(f"{BASE_URL}/checkout",
                        headers=get_headers(token),
                        json=payload,
                        timeout=15)
    return resp

def get_order(token, order_id):
    """Fetch order details"""
    resp = requests.get(f"{BASE_URL}/orders/{order_id}",
                       headers=get_headers(token),
                       timeout=10)
    return resp

def get_paymongo_status(token, order_id):
    """Poll PayMongo payment status"""
    resp = requests.get(f"{BASE_URL}/paymongo/status/{order_id}",
                       headers=get_headers(token),
                       timeout=10)
    return resp

def cancel_order(token, order_id):
    """Cancel an order"""
    resp = requests.put(f"{BASE_URL}/orders/{order_id}/cancel",
                       headers=get_headers(token),
                       timeout=15)
    return resp

def update_order_status(token, order_id, status):
    """Update order status (seller only)"""
    resp = requests.put(f"{BASE_URL}/orders/{order_id}/status",
                       headers=get_headers(token),
                       json={"status": status},
                       timeout=10)
    return resp

def mark_order_as_paid_in_db(order_id):
    """Manually mark order as paid in MongoDB (for testing refund path)"""
    try:
        client = MongoClient(MONGO_URL)
        db = client[DB_NAME]
        result = db.orders.update_one(
            {"id": order_id},
            {"$set": {"payment_status": "paid"}}
        )
        client.close()
        return result.modified_count > 0
    except Exception as e:
        log_fail(f"Failed to mark order as paid in DB: {e}")
        return False

def get_product_stock(product_id):
    """Get current stock of a product from DB"""
    try:
        client = MongoClient(MONGO_URL)
        db = client[DB_NAME]
        product = db.products.find_one({"id": product_id})
        client.close()
        if product:
            return product.get("stock", 0)
        return None
    except Exception as e:
        log_fail(f"Failed to get product stock: {e}")
        return None

# ============================================================================
# TEST SUITE
# ============================================================================

def test_1_online_checkout_session_creation(buyer_token, product):
    """Test 1: Online checkout via PayMongo (happy path — session creation)"""
    log_test("Test 1: Online checkout via PayMongo (session creation)")
    
    resp = create_online_checkout(buyer_token, product)
    
    if resp.status_code != 200:
        log_fail(f"Checkout failed: {resp.status_code} - {resp.text}")
        return None
    
    data = resp.json()
    log_info(f"Checkout response: {json.dumps(data, indent=2)}")
    
    # Verify response contains checkout_url starting with https://checkout.paymongo.com/
    checkout_url = data.get("checkout_url", "")
    if not checkout_url.startswith("https://checkout.paymongo.com/"):
        log_fail(f"checkout_url doesn't start with https://checkout.paymongo.com/: {checkout_url}")
        return None
    log_pass(f"checkout_url is valid PayMongo URL")
    
    # Verify provider == "paymongo"
    if data.get("provider") != "paymongo":
        log_fail(f"provider is not 'paymongo': {data.get('provider')}")
        return None
    log_pass("provider == 'paymongo'")
    
    order_id = data.get("order_id")
    if not order_id:
        log_fail("No order_id in response")
        return None
    log_pass(f"Order created: {order_id}")
    
    # Fetch order and verify fields
    order_resp = get_order(buyer_token, order_id)
    if order_resp.status_code != 200:
        log_fail(f"Failed to fetch order: {order_resp.status_code}")
        return None
    
    order = order_resp.json()
    log_info(f"Order details: payment_provider={order.get('payment_provider')}, payment_status={order.get('payment_status')}, status={order.get('status')}")
    
    if order.get("payment_provider") != "paymongo":
        log_fail(f"payment_provider != 'paymongo': {order.get('payment_provider')}")
        return None
    log_pass("payment_provider == 'paymongo'")
    
    if not order.get("paymongo_session_id"):
        log_fail("paymongo_session_id not present")
        return None
    log_pass("paymongo_session_id present")
    
    if order.get("payment_status") != "pending":
        log_fail(f"payment_status != 'pending': {order.get('payment_status')}")
        return None
    log_pass("payment_status == 'pending'")
    
    if order.get("status") != "pending":
        log_fail(f"status != 'pending': {order.get('status')}")
        return None
    log_pass("status == 'pending'")
    
    log_pass("Test 1 PASSED")
    return order_id

def test_2_status_polling_unpaid(buyer_token, order_id):
    """Test 2: Status polling while unpaid"""
    log_test("Test 2: Status polling while unpaid")
    
    resp = get_paymongo_status(buyer_token, order_id)
    
    if resp.status_code != 200:
        log_fail(f"Status polling failed: {resp.status_code} - {resp.text}")
        return False
    
    data = resp.json()
    log_info(f"Status response: {json.dumps(data, indent=2)}")
    
    if data.get("payment_status") != "pending":
        log_fail(f"payment_status != 'pending': {data.get('payment_status')}")
        return False
    log_pass("payment_status == 'pending' (unpaid)")
    
    log_pass("Test 2 PASSED")
    return True

def test_3_status_polling_permissions(buyer_token, seller_token, order_id, product):
    """Test 3: Status polling as unrelated user (permission check)"""
    log_test("Test 3: Status polling permissions")
    
    # Test as seller (should be allowed since seller is the same seller_id from product)
    log_info("Testing as seller (should be allowed)...")
    resp = get_paymongo_status(seller_token, order_id)
    if resp.status_code != 200:
        log_fail(f"Seller access failed: {resp.status_code} - {resp.text}")
        return False
    log_pass("Seller can access status (200)")
    
    # Create a new buyer account to test unrelated user access
    log_info("Creating new buyer account for permission test...")
    new_buyer_email = f"test.buyer.{order_id[:8]}@test.com"
    new_buyer_password = "testpass123"
    
    # Register new buyer
    register_resp = requests.post(f"{BASE_URL}/auth/register",
                                 json={
                                     "email": new_buyer_email,
                                     "password": new_buyer_password,
                                     "name": "Test Buyer",
                                     "role": "buyer"
                                 },
                                 timeout=10)
    
    if register_resp.status_code != 200:
        log_info(f"Could not create new buyer (may already exist): {register_resp.status_code}")
        # Try to login anyway
    
    new_buyer_token = login(new_buyer_email, new_buyer_password)
    if not new_buyer_token:
        log_fail("Could not login as new buyer")
        return False
    
    # Test as unrelated buyer (should be 403)
    log_info("Testing as unrelated buyer (should be 403)...")
    resp = get_paymongo_status(new_buyer_token, order_id)
    if resp.status_code != 403:
        log_fail(f"Unrelated buyer should get 403, got: {resp.status_code}")
        return False
    log_pass("Unrelated buyer correctly denied (403)")
    
    log_pass("Test 3 PASSED")
    return True

def test_4_cancel_unpaid_order(buyer_token, product):
    """Test 4: Cancel unpaid online order (stock restore, no refund)"""
    log_test("Test 4: Cancel unpaid online order")
    
    # Get initial stock
    initial_stock = get_product_stock(product["id"])
    if initial_stock is None:
        log_fail("Could not get initial stock")
        return False
    log_info(f"Initial stock: {initial_stock}")
    
    # Create a new order
    resp = create_online_checkout(buyer_token, product)
    if resp.status_code != 200:
        log_fail(f"Checkout failed: {resp.status_code}")
        return False
    
    order_id = resp.json().get("order_id")
    log_info(f"Created order: {order_id}")
    
    # Check stock after order (should be decreased)
    stock_after_order = get_product_stock(product["id"])
    if stock_after_order is None:
        log_fail("Could not get stock after order")
        return False
    log_info(f"Stock after order: {stock_after_order}")
    
    if stock_after_order != initial_stock - 1:
        log_fail(f"Stock not decreased correctly: expected {initial_stock - 1}, got {stock_after_order}")
        return False
    log_pass("Stock decreased by 1 after order")
    
    # Cancel the order
    cancel_resp = cancel_order(buyer_token, order_id)
    if cancel_resp.status_code != 200:
        log_fail(f"Cancel failed: {cancel_resp.status_code} - {cancel_resp.text}")
        return False
    
    cancelled_order = cancel_resp.json()
    if cancelled_order.get("status") != "cancelled":
        log_fail(f"Order status != 'cancelled': {cancelled_order.get('status')}")
        return False
    log_pass("Order status == 'cancelled'")
    
    # Check stock after cancel (should be restored)
    stock_after_cancel = get_product_stock(product["id"])
    if stock_after_cancel is None:
        log_fail("Could not get stock after cancel")
        return False
    log_info(f"Stock after cancel: {stock_after_cancel}")
    
    if stock_after_cancel != initial_stock:
        log_fail(f"Stock not restored: expected {initial_stock}, got {stock_after_cancel}")
        return False
    log_pass("Stock restored after cancel")
    
    # Try to cancel again (should be idempotent-ish: 400 because already cancelled)
    cancel_resp2 = cancel_order(buyer_token, order_id)
    if cancel_resp2.status_code != 400:
        log_fail(f"Second cancel should return 400, got: {cancel_resp2.status_code}")
        return False
    log_pass("Second cancel correctly returns 400")
    
    log_pass("Test 4 PASSED")
    return True

def test_5_cancel_out_for_delivery_block(buyer_token, seller_token, product):
    """Test 5: Cancel with out_for_delivery block"""
    log_test("Test 5: Cancel with out_for_delivery block")
    
    # Create a new order
    resp = create_online_checkout(buyer_token, product)
    if resp.status_code != 200:
        log_fail(f"Checkout failed: {resp.status_code}")
        return False
    
    order_id = resp.json().get("order_id")
    log_info(f"Created order: {order_id}")
    
    # Advance order status as seller: confirmed → packed → rider_assigned → out_for_delivery
    statuses = ["confirmed", "packed", "rider_assigned", "out_for_delivery"]
    
    for status in statuses:
        log_info(f"Updating order to status: {status}")
        status_resp = update_order_status(seller_token, order_id, status)
        if status_resp.status_code != 200:
            log_fail(f"Failed to update status to {status}: {status_resp.status_code} - {status_resp.text}")
            return False
        log_pass(f"Order status updated to: {status}")
    
    # Try to cancel as buyer (should return 400)
    log_info("Attempting to cancel order with status 'out_for_delivery'...")
    cancel_resp = cancel_order(buyer_token, order_id)
    
    if cancel_resp.status_code != 400:
        log_fail(f"Cancel should return 400, got: {cancel_resp.status_code}")
        return False
    
    # Check error message mentions "out for delivery"
    error_detail = cancel_resp.json().get("detail", "")
    if "out for delivery" not in error_detail.lower():
        log_fail(f"Error message doesn't mention 'out for delivery': {error_detail}")
        return False
    log_pass(f"Cancel correctly blocked with message: {error_detail}")
    
    log_pass("Test 5 PASSED")
    return True

def test_6_refund_path_negative(buyer_token, product):
    """Test 6: Refund path negative check (paid order without paymongo_payment_id)"""
    log_test("Test 6: Refund path negative check")
    
    # Create a new order
    resp = create_online_checkout(buyer_token, product)
    if resp.status_code != 200:
        log_fail(f"Checkout failed: {resp.status_code}")
        return False
    
    order_id = resp.json().get("order_id")
    log_info(f"Created order: {order_id}")
    
    # Manually mark order as paid in DB WITHOUT paymongo_payment_id
    log_info("Manually marking order as paid in DB (without paymongo_payment_id)...")
    if not mark_order_as_paid_in_db(order_id):
        log_fail("Failed to mark order as paid")
        return False
    log_pass("Order marked as paid in DB")
    
    # Try to cancel (should attempt refund and fail with 409 Conflict)
    log_info("Attempting to cancel paid order (should fail with 409 Conflict)...")
    cancel_resp = cancel_order(buyer_token, order_id)
    
    if cancel_resp.status_code != 409:
        log_fail(f"Cancel should return 409, got: {cancel_resp.status_code}")
        log_info(f"Response body: {cancel_resp.text}")
        return False
    log_pass("Cancel correctly returns 409 (Conflict)")
    
    # Check error message is JSON (not Cloudflare HTML)
    try:
        error_data = cancel_resp.json()
        error_detail = error_data.get("detail", "")
    except Exception as e:
        log_fail(f"Response is not valid JSON (Cloudflare HTML?): {e}")
        log_info(f"Response body: {cancel_resp.text[:500]}")
        return False
    log_pass("Response is valid JSON (not Cloudflare HTML)")
    
    log_info(f"Error detail: {error_detail}")
    
    # Verify error message mentions PayMongo payment id
    expected_msg = "No PayMongo payment id on this order — cannot refund"
    if expected_msg not in error_detail:
        log_fail(f"Error message doesn't match expected. Expected: '{expected_msg}', Got: '{error_detail}'")
        return False
    log_pass(f"Error message correct: {error_detail}")
    
    # Verify order state remains unchanged (status='pending', payment_status='paid')
    log_info("Verifying order state remains unchanged...")
    order_resp = get_order(buyer_token, order_id)
    if order_resp.status_code != 200:
        log_fail(f"Failed to fetch order: {order_resp.status_code}")
        return False
    
    order = order_resp.json()
    if order.get("status") != "pending":
        log_fail(f"Order status changed (should remain 'pending'): {order.get('status')}")
        return False
    log_pass("Order status remains 'pending'")
    
    if order.get("payment_status") != "paid":
        log_fail(f"Payment status changed (should remain 'paid'): {order.get('payment_status')}")
        return False
    log_pass("Payment status remains 'paid'")
    
    log_pass("Test 6 PASSED")
    return True

def test_7_login_regression(buyer_token, seller_token):
    """Test 7: Login regression (CORS still fine)"""
    log_test("Test 7: Login regression (CORS)")
    
    # Test buyer login
    buyer_token_new = login(BUYER_EMAIL, BUYER_PASSWORD)
    if not buyer_token_new:
        log_fail("Buyer login failed")
        return False
    log_pass("Buyer login successful")
    
    # Test seller login
    seller_token_new = login(SELLER_EMAIL, SELLER_PASSWORD)
    if not seller_token_new:
        log_fail("Seller login failed")
        return False
    log_pass("Seller login successful")
    
    # Test admin login
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log_fail("Admin login failed")
        return False
    log_pass("Admin login successful")
    
    log_pass("Test 7 PASSED")
    return True

def test_8_gcash_checkout(buyer_token, product):
    """Test 8: GCash (auto) checkout still works"""
    log_test("Test 8: GCash (auto) checkout")
    
    resp = create_gcash_checkout(buyer_token, product)
    
    if resp.status_code != 200:
        log_fail(f"GCash checkout failed: {resp.status_code} - {resp.text}")
        return False
    
    data = resp.json()
    log_info(f"GCash checkout response: {json.dumps(data, indent=2)}")
    
    # Verify gcash_mode == "auto"
    if data.get("gcash_mode") != "auto":
        log_fail(f"gcash_mode != 'auto': {data.get('gcash_mode')}")
        return False
    log_pass("gcash_mode == 'auto'")
    
    # Verify checkout_url from PayMongo
    checkout_url = data.get("checkout_url", "")
    if not checkout_url.startswith("https://checkout.paymongo.com/"):
        log_fail(f"checkout_url doesn't start with https://checkout.paymongo.com/: {checkout_url}")
        return False
    log_pass("checkout_url is valid PayMongo URL")
    
    order_id = data.get("order_id")
    if not order_id:
        log_fail("No order_id in response")
        return False
    
    # Fetch order and verify payment_provider
    order_resp = get_order(buyer_token, order_id)
    if order_resp.status_code != 200:
        log_fail(f"Failed to fetch order: {order_resp.status_code}")
        return False
    
    order = order_resp.json()
    if order.get("payment_provider") != "paymongo":
        log_fail(f"payment_provider != 'paymongo': {order.get('payment_provider')}")
        return False
    log_pass("payment_provider == 'paymongo'")
    
    log_pass("Test 8 PASSED")
    return True

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"\n{Colors.BLUE}{'='*80}{Colors.END}")
    print(f"{Colors.BLUE}FarmDirect Laguna - PayMongo Payment + Refund Backend Tests{Colors.END}")
    print(f"{Colors.BLUE}{'='*80}{Colors.END}\n")
    
    # Login
    log_info("Logging in as buyer...")
    buyer_token = login(BUYER_EMAIL, BUYER_PASSWORD)
    if not buyer_token:
        log_fail("Buyer login failed. Exiting.")
        sys.exit(1)
    
    log_info("Logging in as seller...")
    seller_token = login(SELLER_EMAIL, SELLER_PASSWORD)
    if not seller_token:
        log_fail("Seller login failed. Exiting.")
        sys.exit(1)
    
    # Fetch products
    log_info("Fetching marketplace products...")
    products = get_products(buyer_token)
    if not products:
        log_fail("No products found. Exiting.")
        sys.exit(1)
    
    product = find_low_cost_product(products)
    if not product:
        log_fail("Could not find a suitable product. Exiting.")
        sys.exit(1)
    
    # Run tests
    results = {}
    
    # Test 1: Online checkout session creation
    order_id_test1 = test_1_online_checkout_session_creation(buyer_token, product)
    results["Test 1"] = order_id_test1 is not None
    
    # Test 2: Status polling while unpaid
    if order_id_test1:
        results["Test 2"] = test_2_status_polling_unpaid(buyer_token, order_id_test1)
    else:
        results["Test 2"] = False
        log_fail("Test 2 skipped (Test 1 failed)")
    
    # Test 3: Status polling permissions
    if order_id_test1:
        results["Test 3"] = test_3_status_polling_permissions(buyer_token, seller_token, order_id_test1, product)
    else:
        results["Test 3"] = False
        log_fail("Test 3 skipped (Test 1 failed)")
    
    # Test 4: Cancel unpaid order
    results["Test 4"] = test_4_cancel_unpaid_order(buyer_token, product)
    
    # Test 5: Cancel with out_for_delivery block
    results["Test 5"] = test_5_cancel_out_for_delivery_block(buyer_token, seller_token, product)
    
    # Test 6: Refund path negative check
    results["Test 6"] = test_6_refund_path_negative(buyer_token, product)
    
    # Test 7: Login regression
    results["Test 7"] = test_7_login_regression(buyer_token, seller_token)
    
    # Test 8: GCash checkout
    results["Test 8"] = test_8_gcash_checkout(buyer_token, product)
    
    # Summary
    print(f"\n{Colors.BLUE}{'='*80}{Colors.END}")
    print(f"{Colors.BLUE}TEST SUMMARY{Colors.END}")
    print(f"{Colors.BLUE}{'='*80}{Colors.END}\n")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = f"{Colors.GREEN}✅ PASS{Colors.END}" if result else f"{Colors.RED}❌ FAIL{Colors.END}"
        print(f"{test_name}: {status}")
    
    print(f"\n{Colors.BLUE}Total: {passed}/{total} tests passed{Colors.END}\n")
    
    if passed == total:
        print(f"{Colors.GREEN}{'='*80}{Colors.END}")
        print(f"{Colors.GREEN}ALL TESTS PASSED ✅{Colors.END}")
        print(f"{Colors.GREEN}{'='*80}{Colors.END}\n")
        sys.exit(0)
    else:
        print(f"{Colors.RED}{'='*80}{Colors.END}")
        print(f"{Colors.RED}SOME TESTS FAILED ❌{Colors.END}")
        print(f"{Colors.RED}{'='*80}{Colors.END}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
