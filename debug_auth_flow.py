#!/usr/bin/env python3
"""
Debug Authentication Flow
Simple script to test the authentication endpoints directly
"""

import requests
import json
import sys

def test_auth_flow():
    """Test the authentication flow step by step"""
    base_url = "http://127.0.0.1:5000"
    
    print("🔍 Debug Authentication Flow")
    print("=" * 40)
    
    # Test 1: Check if server is running
    print("1️⃣ Testing server connectivity...")
    try:
        response = requests.get(f"{base_url}/", timeout=5)
        print(f"✅ Server responding: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Server not accessible: {e}")
        print("📝 Make sure to start the server with: python s3bucket_ext_rename.py")
        return False
    
    # Test 2: Test auth endpoints with invalid credentials
    print("\n2️⃣ Testing auth/login endpoint with invalid credentials...")
    test_data = {
        "access_key": "INVALID_KEY",
        "secret_key": "invalid_secret",
        "region": "us-east-1"
    }
    
    try:
        response = requests.post(f"{base_url}/auth/login", 
                               json=test_data, 
                               timeout=10)
        print(f"📡 Response status: {response.status_code}")
        print(f"📄 Response body: {response.text}")
        
        if response.status_code == 401:
            print("✅ Auth endpoint correctly rejects invalid credentials")
        else:
            print(f"⚠️ Unexpected response: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Auth endpoint error: {e}")
        return False
    
    # Test 3: Test list-buckets without session
    print("\n3️⃣ Testing list-buckets without session...")
    try:
        response = requests.post(f"{base_url}/list-buckets", 
                               json={}, 
                               timeout=10)
        print(f"📡 Response status: {response.status_code}")
        print(f"📄 Response body: {response.text}")
        
        if response.status_code == 401:
            print("✅ List-buckets correctly rejects requests without session")
        else:
            print(f"⚠️ Unexpected response: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ List-buckets endpoint error: {e}")
        return False
    
    # Test 4: Test with fake session
    print("\n4️⃣ Testing list-buckets with fake session...")
    try:
        response = requests.post(f"{base_url}/list-buckets", 
                               json={"session_id": "fake_session_123"}, 
                               timeout=10)
        print(f"📡 Response status: {response.status_code}")
        print(f"📄 Response body: {response.text}")
        
        if response.status_code == 401:
            print("✅ List-buckets correctly rejects fake sessions")
        else:
            print(f"⚠️ Unexpected response: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ List-buckets with fake session error: {e}")
        return False
    
    print("\n🎉 Basic authentication flow tests completed!")
    print("\n📝 Next steps:")
    print("1. Open the browser console (F12)")
    print("2. Use the wizard normally")
    print("3. Check console for detailed auth flow logs")
    print("4. Look for 🔐 🪣 📡 📄 emoji messages")
    
    return True

if __name__ == "__main__":
    test_auth_flow()
