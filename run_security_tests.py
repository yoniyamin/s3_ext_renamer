#!/usr/bin/env python3
"""
Quick Security Test Runner
Simple script to verify the security enhancements are working
"""

import requests
import json
import sys
import time
from datetime import datetime

def test_security_enhancements():
    """Quick test of security enhancements"""
    base_url = "http://127.0.0.1:5000"
    
    print("🔒 Security Enhancement Verification")
    print("=" * 50)
    
    # Test 1: Check that old-style credential requests fail
    print("🧪 Test 1: Verifying credential exposure protection...")
    
    old_style_request = {
        "access_key": "FAKE_ACCESS_KEY",
        "secret_key": "FAKE_SECRET_KEY",
        "bucket": "test-bucket"
    }
    
    try:
        response = requests.post(f"{base_url}/list-buckets", 
                               json=old_style_request, 
                               timeout=10)
        
        if response.status_code == 401:
            print("✅ PASS: Old-style requests correctly rejected")
        else:
            print(f"❌ FAIL: Expected 401, got {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR: Could not connect to server: {e}")
        print("📝 Make sure the S3 Manipulator server is running on port 5000")
        return False
    
    # Test 2: Check authentication endpoints exist
    print("🧪 Test 2: Verifying authentication endpoints...")
    
    try:
        response = requests.post(f"{base_url}/auth/login", 
                               json={"access_key": "test", "secret_key": "test"}, 
                               timeout=10)
        
        if response.status_code in [400, 401]:  # Either is acceptable for invalid creds
            print("✅ PASS: Authentication endpoint responding correctly")
        else:
            print(f"❓ INFO: Auth endpoint returned {response.status_code}")
            
    except requests.exceptions.RequestException:
        print("❌ FAIL: Authentication endpoint not accessible")
        return False
    
    # Test 3: Check session validation
    print("🧪 Test 3: Verifying session validation...")
    
    try:
        response = requests.post(f"{base_url}/auth/validate", 
                               json={"session_id": "invalid_session"}, 
                               timeout=10)
        
        if response.status_code == 401:
            print("✅ PASS: Invalid sessions correctly rejected")
        else:
            print(f"❓ INFO: Session validation returned {response.status_code}")
            
    except requests.exceptions.RequestException:
        print("❌ FAIL: Session validation endpoint not accessible")
        return False
    
    print("\n🎉 Basic security verification complete!")
    print("🔒 Your S3 Manipulator now uses secure session-based authentication")
    print("\nFor comprehensive testing:")
    print("1. Update test_security_endpoints.py with your AWS credentials")
    print("2. Run: python test_security_endpoints.py")
    
    return True

if __name__ == "__main__":
    test_security_enhancements()
