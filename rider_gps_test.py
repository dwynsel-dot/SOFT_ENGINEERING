#!/usr/bin/env python3
"""
Rider GPS Chain Backend Test Suite
Tests rider login, GPS location updates, and end-to-end delivery flow
"""

import requests
import json
import sys
import time

# Base URL from frontend/.env
BASE_URL = "https://map-overlap-fix-1.preview.emergentagent.com/api"

# Test credentials from /app/memory/test_credentials.md
RIDER_1_EMAIL = "kuya.jun@laguna.ph"
RIDER_2_EMAIL = "kuya.marvin@laguna.ph"
RIDER_3_EMAIL = "ate.ella@laguna.ph"
RIDER_PASSWORD = "rider123"

BUYER_EMAIL = "aling.nena@laguna.ph"
BUYER_PASSWORD = "buyer123"

SELLER_EMAIL = "mang.kanor@laguna.ph"
SELLER_PASSWORD = "farmer123"

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
    """Login and return Bearer token and user data"""
    resp = requests.post(f"{BASE_URL}/auth/login", 
                        json={"email": email, "password": password},
                        timeout=10)
    if resp.status_code != 200:
        log_fail(f"Login failed for {email}: {resp.status_code} - {resp.text}")
        return None, None
    data = resp.json()
    token = data.get("token") or data.get("access_token")
    user = data.get("user")
    if not token:
        log_fail(f"No token in login response for {email}")
        return None, None
    log_pass(f"Login successful for {email}")
    return token, user

def get_headers(token):
    """Return headers with Bearer token"""
    return {"Authorization": f"Bearer {token}"}

# ============================================================================
# TEST 1: Rider Login
# ============================================================================

def test_1_rider_login():
    """Test 1: Rider login for all 3 riders"""
    log_test("Test 1: Rider login for all 3 riders")
    
    riders = [
        (RIDER_1_EMAIL, "Kuya Jun"),
        (RIDER_2_EMAIL, "Kuya Marvin"),
        (RIDER_3_EMAIL, "Ate Ella")
    ]
    
    rider_tokens = {}
    rider_users = {}
    
    for email, name in riders:
        log_info(f"Testing login for {name} ({email})...")
        token, user = login(email, RIDER_PASSWORD)
        
        if not token:
            log_fail(f"Login failed for {name}")
            return None
        
        # Verify role is "rider"
        if user.get("role") != "rider":
            log_fail(f"Role is not 'rider' for {name}: {user.get('role')}")
            return None
        log_pass(f"{name} has role='rider'")
        
        rider_tokens[email] = token
        rider_users[email] = user
    
    log_pass("All 3 riders logged in successfully with role='rider'")
    return rider_tokens, rider_users

# ============================================================================
# TEST 2: Rider Profiles
# ============================================================================

def test_2_rider_profiles(rider_tokens, rider_users):
    """Test 2: Rider profiles linked in /api/riders"""
    log_test("Test 2: Rider profiles linked in /api/riders")
    
    # Use any rider token to fetch riders
    token = list(rider_tokens.values())[0]
    
    resp = requests.get(f"{BASE_URL}/riders", 
                       headers=get_headers(token),
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to fetch riders: {resp.status_code} - {resp.text}")
        return None
    
    riders = resp.json()
    log_info(f"Found {len(riders)} rider profiles")
    
    # Verify all 3 new riders are present
    rider_emails = [RIDER_1_EMAIL, RIDER_2_EMAIL, RIDER_3_EMAIL]
    found_riders = {}
    
    for rider in riders:
        rider_user_id = rider.get("rider_user_id")
        if rider_user_id:
            # Match with our logged-in users
            for email, user in rider_users.items():
                if user["id"] == rider_user_id:
                    found_riders[email] = rider
                    log_pass(f"Found rider profile for {email}: {rider.get('name')} (rider_user_id={rider_user_id})")
    
    if len(found_riders) != 3:
        log_fail(f"Expected 3 rider profiles, found {len(found_riders)}")
        return None
    
    log_pass("All 3 rider profiles found with correct rider_user_id links")
    return found_riders

# ============================================================================
# TEST 3: End-to-End Delivery + GPS Chain
# ============================================================================

def test_3_e2e_delivery_gps_chain(rider_tokens, rider_users, found_riders):
    """Test 3: End-to-end delivery + GPS chain"""
    log_test("Test 3: End-to-end delivery + GPS chain")
    
    # Step 1: Login as buyer
    log_info("Step 1: Login as buyer...")
    buyer_token, buyer_user = login(BUYER_EMAIL, BUYER_PASSWORD)
    if not buyer_token:
        log_fail("Buyer login failed")
        return None
    
    # Step 2: Fetch products
    log_info("Step 2: Fetch products...")
    resp = requests.get(f"{BASE_URL}/products", 
                       headers=get_headers(buyer_token),
                       timeout=10)
    if resp.status_code != 200:
        log_fail(f"Failed to fetch products: {resp.status_code}")
        return None
    
    products = resp.json()
    if not products:
        log_fail("No products found")
        return None
    
    # Pick the cheapest product
    product = sorted(products, key=lambda p: float(p.get("price", 999)))[0]
    log_info(f"Selected product: {product.get('name')} - ₱{product.get('price')}")
    
    # Step 3: Create delivery order with COD
    log_info("Step 3: Create delivery order with COD...")
    items = [{
        "product_id": product["id"],
        "name": product["name"],
        "price": float(product["price"]),
        "quantity": 1,
        "seller_id": product["seller_id"],
        "image_url": product.get("image_url", "")
    }]
    
    checkout_payload = {
        "items": items,
        "payment_method": "cod",
        "fulfillment_type": "delivery",
        "delivery_address": "Brgy. Batong Malake, Los Baños, Laguna",
        "delivery_lat": 14.1699,
        "delivery_lng": 121.2415,
        "contact_phone": "0917-123-4567",
        "pickup_location": None,
        "origin_url": "https://example.com"
    }
    
    resp = requests.post(f"{BASE_URL}/checkout",
                        headers=get_headers(buyer_token),
                        json=checkout_payload,
                        timeout=15)
    
    if resp.status_code != 200:
        log_fail(f"Checkout failed: {resp.status_code} - {resp.text}")
        return None
    
    order_id = resp.json().get("order_id")
    log_pass(f"Order created: {order_id}")
    
    # Step 4: Login as seller
    log_info("Step 4: Login as seller...")
    seller_token, seller_user = login(SELLER_EMAIL, SELLER_PASSWORD)
    if not seller_token:
        log_fail("Seller login failed")
        return None
    
    # Step 5: Advance order status: confirmed → packed → rider_assigned
    log_info("Step 5: Advance order status...")
    statuses = ["confirmed", "packed"]
    
    for status in statuses:
        log_info(f"  Setting status to: {status}")
        resp = requests.put(f"{BASE_URL}/orders/{order_id}/status",
                           headers=get_headers(seller_token),
                           json={"status": status},
                           timeout=10)
        if resp.status_code != 200:
            log_fail(f"Failed to set status to {status}: {resp.status_code} - {resp.text}")
            return None
        log_pass(f"Status set to: {status}")
    
    # Step 6: Assign rider (Kuya Jun)
    log_info("Step 6: Assign rider (Kuya Jun)...")
    kuya_jun_rider = found_riders[RIDER_1_EMAIL]
    
    resp = requests.put(f"{BASE_URL}/orders/{order_id}/assign-rider",
                       headers=get_headers(seller_token),
                       json={"rider_id": kuya_jun_rider["id"]},
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to assign rider: {resp.status_code} - {resp.text}")
        return None
    
    order = resp.json()
    if order.get("status") != "rider_assigned":
        log_fail(f"Order status is not 'rider_assigned': {order.get('status')}")
        return None
    log_pass(f"Rider assigned: {kuya_jun_rider['name']}")
    
    # Step 7: Set status to out_for_delivery
    log_info("Step 7: Set status to out_for_delivery...")
    resp = requests.put(f"{BASE_URL}/orders/{order_id}/status",
                       headers=get_headers(seller_token),
                       json={"status": "out_for_delivery"},
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to set status to out_for_delivery: {resp.status_code} - {resp.text}")
        return None
    log_pass("Status set to: out_for_delivery")
    
    # Step 8: Login as Kuya Jun (rider)
    log_info("Step 8: Login as Kuya Jun (rider)...")
    jun_token = rider_tokens[RIDER_1_EMAIL]
    
    # Step 9: Get rider orders
    log_info("Step 9: Get rider orders...")
    resp = requests.get(f"{BASE_URL}/rider/orders",
                       headers=get_headers(jun_token),
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to get rider orders: {resp.status_code} - {resp.text}")
        return None
    
    rider_orders = resp.json()
    order_ids = [o["id"] for o in rider_orders]
    
    if order_id not in order_ids:
        log_fail(f"Order {order_id} not found in rider orders")
        return None
    log_pass(f"Order {order_id} found in rider orders")
    
    # Step 10: Update rider location (first update)
    log_info("Step 10: Update rider location (first update)...")
    resp = requests.put(f"{BASE_URL}/orders/{order_id}/rider-location",
                       headers=get_headers(jun_token),
                       json={"lat": 14.18, "lng": 121.20},
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to update rider location: {resp.status_code} - {resp.text}")
        return None
    log_pass("Rider location updated (first update)")
    
    # Step 11: Get order as buyer and verify rider_location
    log_info("Step 11: Get order as buyer and verify rider_location...")
    resp = requests.get(f"{BASE_URL}/orders/{order_id}",
                       headers=get_headers(buyer_token),
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to get order: {resp.status_code} - {resp.text}")
        return None
    
    order = resp.json()
    rider_location = order.get("rider_location")
    
    if not rider_location:
        log_fail("rider_location not present in order")
        return None
    
    if rider_location.get("lat") != 14.18:
        log_fail(f"rider_location.lat != 14.18: {rider_location.get('lat')}")
        return None
    
    if rider_location.get("lng") != 121.20:
        log_fail(f"rider_location.lng != 121.20: {rider_location.get('lng')}")
        return None
    
    if not rider_location.get("at"):
        log_fail("rider_location.at (timestamp) not present")
        return None
    
    log_pass(f"rider_location verified: lat={rider_location['lat']}, lng={rider_location['lng']}, at={rider_location['at']}")
    
    # Step 12: Update rider location (second update)
    log_info("Step 12: Update rider location (second update)...")
    time.sleep(1)  # Small delay to ensure timestamp changes
    
    resp = requests.put(f"{BASE_URL}/orders/{order_id}/rider-location",
                       headers=get_headers(jun_token),
                       json={"lat": 14.175, "lng": 121.235},
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to update rider location (second): {resp.status_code} - {resp.text}")
        return None
    log_pass("Rider location updated (second update)")
    
    # Step 13: Get order as buyer and verify updated rider_location
    log_info("Step 13: Get order as buyer and verify updated rider_location...")
    resp = requests.get(f"{BASE_URL}/orders/{order_id}",
                       headers=get_headers(buyer_token),
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to get order: {resp.status_code} - {resp.text}")
        return None
    
    order = resp.json()
    rider_location = order.get("rider_location")
    
    if not rider_location:
        log_fail("rider_location not present in order after second update")
        return None
    
    if rider_location.get("lat") != 14.175:
        log_fail(f"rider_location.lat != 14.175 after second update: {rider_location.get('lat')}")
        return None
    
    if rider_location.get("lng") != 121.235:
        log_fail(f"rider_location.lng != 121.235 after second update: {rider_location.get('lng')}")
        return None
    
    log_pass(f"rider_location updated correctly: lat={rider_location['lat']}, lng={rider_location['lng']}")
    
    log_pass("End-to-end delivery + GPS chain PASSED")
    return order_id, jun_token

# ============================================================================
# TEST 4: Authorization Guard
# ============================================================================

def test_4_authorization_guard(order_id, rider_tokens):
    """Test 4: Authorization guard on /rider-location"""
    log_test("Test 4: Authorization guard on /rider-location")
    
    # Try to update location as Kuya Marvin (different rider)
    log_info("Attempting to update location as Kuya Marvin (different rider)...")
    marvin_token = rider_tokens[RIDER_2_EMAIL]
    
    resp = requests.put(f"{BASE_URL}/orders/{order_id}/rider-location",
                       headers=get_headers(marvin_token),
                       json={"lat": 14.19, "lng": 121.25},
                       timeout=10)
    
    if resp.status_code != 403:
        log_fail(f"Expected 403, got: {resp.status_code}")
        log_info(f"Response: {resp.text}")
        return False
    
    log_pass("Different rider correctly denied with 403")
    
    # Verify error message
    try:
        error = resp.json()
        detail = error.get("detail", "")
        log_info(f"Error detail: {detail}")
    except:
        pass
    
    log_pass("Authorization guard PASSED")
    return True

# ============================================================================
# TEST 5: Rider Earnings
# ============================================================================

def test_5_rider_earnings(rider_tokens):
    """Test 5: Rider earnings endpoint"""
    log_test("Test 5: Rider earnings endpoint")
    
    # Get earnings for Kuya Jun
    log_info("Getting earnings for Kuya Jun...")
    jun_token = rider_tokens[RIDER_1_EMAIL]
    
    resp = requests.get(f"{BASE_URL}/rider/earnings",
                       headers=get_headers(jun_token),
                       timeout=10)
    
    if resp.status_code != 200:
        log_fail(f"Failed to get rider earnings: {resp.status_code} - {resp.text}")
        return False
    
    earnings = resp.json()
    log_info(f"Earnings response: {json.dumps(earnings, indent=2)}")
    
    # Verify expected shape
    required_fields = ["completed", "active", "fees_earned", "assigned"]
    for field in required_fields:
        if field not in earnings:
            log_fail(f"Missing field in earnings response: {field}")
            return False
        log_pass(f"Field '{field}' present: {earnings[field]}")
    
    # Verify active >= 1 (we just created an order)
    if earnings.get("active", 0) < 1:
        log_fail(f"Expected active >= 1, got: {earnings.get('active')}")
        return False
    log_pass(f"Active orders: {earnings['active']} (>= 1)")
    
    log_pass("Rider earnings PASSED")
    return True

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"\n{Colors.BLUE}{'='*80}{Colors.END}")
    print(f"{Colors.BLUE}FarmDirect Laguna - Rider GPS Chain Backend Tests{Colors.END}")
    print(f"{Colors.BLUE}{'='*80}{Colors.END}\n")
    
    results = {}
    
    # Test 1: Rider login
    test1_result = test_1_rider_login()
    results["Test 1: Rider login"] = test1_result is not None
    
    if not test1_result:
        log_fail("Test 1 failed. Cannot continue.")
        print_summary(results)
        sys.exit(1)
    
    rider_tokens, rider_users = test1_result
    
    # Test 2: Rider profiles
    test2_result = test_2_rider_profiles(rider_tokens, rider_users)
    results["Test 2: Rider profiles"] = test2_result is not None
    
    if not test2_result:
        log_fail("Test 2 failed. Cannot continue.")
        print_summary(results)
        sys.exit(1)
    
    found_riders = test2_result
    
    # Test 3: End-to-end delivery + GPS chain
    test3_result = test_3_e2e_delivery_gps_chain(rider_tokens, rider_users, found_riders)
    results["Test 3: E2E delivery + GPS chain"] = test3_result is not None
    
    if not test3_result:
        log_fail("Test 3 failed. Cannot continue.")
        print_summary(results)
        sys.exit(1)
    
    order_id, jun_token = test3_result
    
    # Test 4: Authorization guard
    results["Test 4: Authorization guard"] = test_4_authorization_guard(order_id, rider_tokens)
    
    # Test 5: Rider earnings
    results["Test 5: Rider earnings"] = test_5_rider_earnings(rider_tokens)
    
    # Print summary
    print_summary(results)
    
    # Exit with appropriate code
    if all(results.values()):
        sys.exit(0)
    else:
        sys.exit(1)

def print_summary(results):
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
    else:
        print(f"{Colors.RED}{'='*80}{Colors.END}")
        print(f"{Colors.RED}SOME TESTS FAILED ❌{Colors.END}")
        print(f"{Colors.RED}{'='*80}{Colors.END}\n")

if __name__ == "__main__":
    main()
