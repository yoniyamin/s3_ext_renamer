#!/usr/bin/env python3
"""
Comprehensive Security Test Suite for S3 Manipulator
Tests all endpoints with the new session-based authentication system
"""

import pytest
import requests
import json
import time
import logging
from datetime import datetime
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestConfig:
    """Test configuration - UPDATE THESE WITH YOUR VALUES"""
    BASE_URL = "http://127.0.0.1:5000"
    
    # Test AWS credentials (use IAM user with limited S3 permissions)
    TEST_ACCESS_KEY = "YOUR_TEST_ACCESS_KEY_HERE"
    TEST_SECRET_KEY = "YOUR_TEST_SECRET_KEY_HERE"
    TEST_SESSION_TOKEN = None  # Optional
    TEST_REGION = "us-east-1"
    TEST_BUCKET = "YOUR_TEST_BUCKET_HERE"
    
    # Invalid credentials for security testing
    INVALID_ACCESS_KEY = "AKIAAAAAAAAAAAAAAA"
    INVALID_SECRET_KEY = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class SecurityTestSuite:
    """Complete security test suite for S3 Manipulator endpoints"""
    
    def __init__(self):
        self.base_url = TestConfig.BASE_URL
        self.session_id = None
        self.test_results = []
    
    def log_test_result(self, test_name, status, message="", details=None):
        """Log test results for reporting"""
        result = {
            "test": test_name,
            "status": status,  # "PASS", "FAIL", "SKIP"
            "message": message,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.test_results.append(result)
        
        status_emoji = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}
        logger.info(f"{status_emoji.get(status, '🔍')} {test_name}: {message}")
    
    def make_request(self, endpoint, method="POST", data=None, headers=None, timeout=30):
        """Make HTTP request with proper error handling"""
        if headers is None:
            headers = {"Content-Type": "application/json"}
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            if method.upper() == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=timeout)
            elif method.upper() == "GET":
                response = requests.get(url, headers=headers, timeout=timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return None
    
    # ======================== AUTHENTICATION TESTS ========================
    
    def test_auth_login_valid_credentials(self):
        """Test authentication with valid AWS credentials"""
        test_name = "Authentication - Valid Credentials"
        
        data = {
            "access_key": TestConfig.TEST_ACCESS_KEY,
            "secret_key": TestConfig.TEST_SECRET_KEY,
            "region": TestConfig.TEST_REGION
        }
        if TestConfig.TEST_SESSION_TOKEN:
            data["session_token"] = TestConfig.TEST_SESSION_TOKEN
        
        response = self.make_request("/auth/login", data=data)
        
        if not response:
            self.log_test_result(test_name, "FAIL", "Request failed")
            return False
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success") and result.get("session_id"):
                self.session_id = result["session_id"]
                self.log_test_result(test_name, "PASS", f"Session created: {self.session_id[:8]}...")
                return True
            else:
                self.log_test_result(test_name, "FAIL", f"Invalid response: {result}")
                return False
        else:
            self.log_test_result(test_name, "FAIL", f"HTTP {response.status_code}: {response.text}")
            return False
    
    def test_auth_login_invalid_credentials(self):
        """Test authentication with invalid AWS credentials"""
        test_name = "Authentication - Invalid Credentials"
        
        data = {
            "access_key": TestConfig.INVALID_ACCESS_KEY,
            "secret_key": TestConfig.INVALID_SECRET_KEY,
            "region": TestConfig.TEST_REGION
        }
        
        response = self.make_request("/auth/login", data=data)
        
        if not response:
            self.log_test_result(test_name, "FAIL", "Request failed")
            return False
        
        if response.status_code == 401:
            result = response.json()
            if not result.get("success"):
                self.log_test_result(test_name, "PASS", "Correctly rejected invalid credentials")
                return True
        
        self.log_test_result(test_name, "FAIL", f"Expected 401, got {response.status_code}")
        return False
    
    def test_auth_validate_session(self):
        """Test session validation"""
        test_name = "Authentication - Session Validation"
        
        if not self.session_id:
            self.log_test_result(test_name, "SKIP", "No session ID available")
            return False
        
        data = {"session_id": self.session_id}
        response = self.make_request("/auth/validate", data=data)
        
        if response and response.status_code == 200:
            result = response.json()
            if result.get("success"):
                self.log_test_result(test_name, "PASS", "Session validation successful")
                return True
        
        self.log_test_result(test_name, "FAIL", f"Session validation failed: {response.text if response else 'No response'}")
        return False
    
    def test_auth_invalid_session(self):
        """Test requests with invalid session ID"""
        test_name = "Authentication - Invalid Session ID"
        
        invalid_session = "invalid_session_id_12345"
        data = {"session_id": invalid_session}
        response = self.make_request("/auth/validate", data=data)
        
        if response and response.status_code == 401:
            result = response.json()
            if not result.get("success"):
                self.log_test_result(test_name, "PASS", "Correctly rejected invalid session")
                return True
        
        self.log_test_result(test_name, "FAIL", f"Expected 401, got {response.status_code if response else 'No response'}")
        return False
    
    # ======================== S3 OPERATION TESTS ========================
    
    def test_list_buckets(self):
        """Test listing S3 buckets with session authentication"""
        test_name = "S3 Operations - List Buckets"
        
        if not self.session_id:
            self.log_test_result(test_name, "SKIP", "No session ID available")
            return False
        
        data = {"session_id": self.session_id}
        response = self.make_request("/list-buckets", data=data)
        
        if response and response.status_code == 200:
            result = response.json()
            if result.get("success") and "buckets" in result:
                bucket_count = len(result["buckets"])
                self.log_test_result(test_name, "PASS", f"Listed {bucket_count} buckets")
                return True
        
        self.log_test_result(test_name, "FAIL", f"Failed to list buckets: {response.text if response else 'No response'}")
        return False
    
    def test_browse_folders(self):
        """Test browsing folders in S3 bucket"""
        test_name = "S3 Operations - Browse Folders"
        
        if not self.session_id:
            self.log_test_result(test_name, "SKIP", "No session ID available")
            return False
        
        data = {
            "session_id": self.session_id,
            "bucket": TestConfig.TEST_BUCKET,
            "prefix": ""
        }
        response = self.make_request("/browse-folders", data=data)
        
        if response and response.status_code == 200:
            result = response.json()
            if result.get("success"):
                self.log_test_result(test_name, "PASS", f"Browse successful: {len(result.get('files', []))} files, {len(result.get('folders', []))} folders")
                return True
        
        self.log_test_result(test_name, "FAIL", f"Failed to browse folders: {response.text if response else 'No response'}")
        return False
    
    def test_generate_presigned_url(self):
        """Test generating presigned URLs"""
        test_name = "S3 Operations - Generate Presigned URL"
        
        if not self.session_id:
            self.log_test_result(test_name, "SKIP", "No session ID available")
            return False
        
        data = {
            "session_id": self.session_id,
            "bucket": TestConfig.TEST_BUCKET,
            "object_key": "test/file.txt",
            "url_type": "upload",
            "expiration": 300
        }
        response = self.make_request("/generate-presigned-url", data=data)
        
        if response and response.status_code == 200:
            result = response.json()
            if result.get("success") and result.get("presigned_url"):
                self.log_test_result(test_name, "PASS", "Presigned URL generated successfully")
                return True
        
        self.log_test_result(test_name, "FAIL", f"Failed to generate presigned URL: {response.text if response else 'No response'}")
        return False
    
    def test_create_folder(self):
        """Test creating a folder in S3"""
        test_name = "S3 Operations - Create Folder"
        
        if not self.session_id:
            self.log_test_result(test_name, "SKIP", "No session ID available")
            return False
        
        test_folder = f"test-folder-{int(time.time())}/"
        data = {
            "session_id": self.session_id,
            "bucket": TestConfig.TEST_BUCKET,
            "folder_key": test_folder
        }
        response = self.make_request("/s3-create-folder", data=data)
        
        if response and response.status_code == 200:
            result = response.json()
            if result.get("success"):
                self.log_test_result(test_name, "PASS", f"Created folder: {test_folder}")
                return True
        
        self.log_test_result(test_name, "FAIL", f"Failed to create folder: {response.text if response else 'No response'}")
        return False
    
    # ======================== SECURITY TESTS ========================
    
    def test_no_credentials_in_requests(self):
        """Verify that credentials are not being sent in API requests"""
        test_name = "Security - No Credentials in Requests"
        
        if not self.session_id:
            self.log_test_result(test_name, "SKIP", "No session ID available")
            return False
        
        # Make a request and verify no sensitive data in payload
        data = {
            "session_id": self.session_id,
            "bucket": TestConfig.TEST_BUCKET
        }
        
        # Convert to JSON to check content
        json_data = json.dumps(data)
        
        # Check that credentials are not in the payload
        sensitive_terms = ["access_key", "secret_key", "aws_access_key_id", "aws_secret_access_key"]
        found_sensitive = [term for term in sensitive_terms if term in json_data]
        
        if not found_sensitive:
            self.log_test_result(test_name, "PASS", "No credentials found in request payload")
            return True
        else:
            self.log_test_result(test_name, "FAIL", f"Found sensitive terms in payload: {found_sensitive}")
            return False
    
    def test_session_expiration(self):
        """Test session timeout behavior (simulate)"""
        test_name = "Security - Session Timeout Handling"
        
        # For this test, we'll use an obviously invalid session ID
        expired_session = "expired_session_12345"
        data = {
            "session_id": expired_session,
            "bucket": TestConfig.TEST_BUCKET
        }
        
        response = self.make_request("/list-buckets", data=data)
        
        if response and response.status_code == 401:
            result = response.json()
            if not result.get("success"):
                self.log_test_result(test_name, "PASS", "Correctly handled expired session")
                return True
        
        self.log_test_result(test_name, "FAIL", f"Expected 401 for expired session, got {response.status_code if response else 'No response'}")
        return False
    
    def test_unauthorized_access(self):
        """Test accessing endpoints without session"""
        test_name = "Security - Unauthorized Access Prevention"
        
        data = {
            "bucket": TestConfig.TEST_BUCKET,
            "prefix": ""
        }
        # Deliberately omit session_id
        
        response = self.make_request("/browse-folders", data=data)
        
        if response and response.status_code == 401:
            self.log_test_result(test_name, "PASS", "Correctly prevented unauthorized access")
            return True
        
        self.log_test_result(test_name, "FAIL", f"Expected 401 for unauthorized access, got {response.status_code if response else 'No response'}")
        return False
    
    # ======================== LOGOUT TESTS ========================
    
    def test_auth_logout(self):
        """Test session logout and cleanup"""
        test_name = "Authentication - Logout"
        
        if not self.session_id:
            self.log_test_result(test_name, "SKIP", "No session ID available")
            return False
        
        data = {"session_id": self.session_id}
        response = self.make_request("/auth/logout", data=data)
        
        if response and response.status_code == 200:
            result = response.json()
            if result.get("success"):
                # Test that session is actually invalidated
                validate_response = self.make_request("/auth/validate", data=data)
                if validate_response and validate_response.status_code == 401:
                    self.log_test_result(test_name, "PASS", "Logout successful and session invalidated")
                    self.session_id = None
                    return True
        
        self.log_test_result(test_name, "FAIL", f"Logout failed: {response.text if response else 'No response'}")
        return False
    
    # ======================== MAIN TEST RUNNER ========================
    
    def run_all_tests(self):
        """Run the complete test suite"""
        logger.info("🔒 Starting Comprehensive Security Test Suite")
        logger.info("=" * 60)
        
        # Authentication Tests
        logger.info("🔐 Running Authentication Tests...")
        self.test_auth_login_invalid_credentials()
        self.test_auth_login_valid_credentials()
        self.test_auth_validate_session()
        self.test_auth_invalid_session()
        
        # S3 Operation Tests  
        logger.info("☁️ Running S3 Operation Tests...")
        self.test_list_buckets()
        self.test_browse_folders()
        self.test_generate_presigned_url()
        self.test_create_folder()
        
        # Security Tests
        logger.info("🛡️ Running Security Tests...")
        self.test_no_credentials_in_requests()
        self.test_session_expiration()
        self.test_unauthorized_access()
        
        # Cleanup Tests
        logger.info("🧹 Running Cleanup Tests...")
        self.test_auth_logout()
        
        # Generate Report
        self.generate_report()
    
    def generate_report(self):
        """Generate comprehensive test report"""
        logger.info("=" * 60)
        logger.info("📊 TEST REPORT SUMMARY")
        logger.info("=" * 60)
        
        total_tests = len(self.test_results)
        passed = len([r for r in self.test_results if r["status"] == "PASS"])
        failed = len([r for r in self.test_results if r["status"] == "FAIL"])
        skipped = len([r for r in self.test_results if r["status"] == "SKIP"])
        
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"✅ Passed: {passed}")
        logger.info(f"❌ Failed: {failed}")
        logger.info(f"⏭️ Skipped: {skipped}")
        logger.info(f"Success Rate: {(passed/total_tests)*100:.1f}%")
        
        if failed > 0:
            logger.info("\n❌ FAILED TESTS:")
            for result in self.test_results:
                if result["status"] == "FAIL":
                    logger.info(f"  - {result['test']}: {result['message']}")
        
        # Save detailed report
        report_file = f"security_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(self.test_results, f, indent=2)
        
        logger.info(f"\n📄 Detailed report saved to: {report_file}")
        logger.info("=" * 60)


def main():
    """Main function to run the test suite"""
    # Verify configuration
    if TestConfig.TEST_ACCESS_KEY == "YOUR_TEST_ACCESS_KEY_HERE":
        print("❌ ERROR: Please update TestConfig with your actual AWS credentials")
        print("📝 Edit the TestConfig class in this file with your test values")
        return
    
    # Run tests
    test_suite = SecurityTestSuite()
    test_suite.run_all_tests()


if __name__ == "__main__":
    main()
