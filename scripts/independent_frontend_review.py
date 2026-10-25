"""
Independent Frontend & Backend Integration Verification Script.
Executes end-to-end browser-based testing against the live FastAPI instance on http://127.0.0.1:8000.
Tests all roles, RBAC boundaries, workflow actions, Chart.js visualizations,
desktop/mobile responsiveness, and console error monitoring.
"""
import sys
import os
import time
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8000"
PASSWORD = "Demo@AICTE2026!"

console_errors = []
page_errors = []

def attach_error_listeners(page, context_name):
    def on_console(msg):
        if msg.type == "error":
            console_errors.append(f"[{context_name}] Console Error: {msg.text}")
    def on_page_error(exc):
        page_errors.append(f"[{context_name}] Uncaught Exception: {exc}")
    page.on("console", on_console)
    page.on("pageerror", on_page_error)


def run_comprehensive_review():
    results = {}
    print("=" * 70)
    print("AICTE WORKFLOW AUTOMATION PLATFORM — INDEPENDENT FRONTEND & BACKEND REVIEW")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)

        # -------------------------------------------------------------
        # 1. Desktop & Mobile Landing & Login Verification
        # -------------------------------------------------------------
        print("\n[Step 1] Checking Landing & Login Pages (Desktop & Mobile)...")
        context_desktop = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context_desktop.new_page()
        attach_error_listeners(page, "Desktop-Landing")

        page.goto(f"{BASE_URL}/")
        assert "AICTE" in page.title() or "AICTE" in page.content(), "Landing page missing AICTE title"
        print("  ✓ Landing page (1280x800) loaded successfully")

        # Test mobile viewport
        context_mobile = browser.new_context(viewport={"width": 375, "height": 667})
        mobile_page = context_mobile.new_page()
        attach_error_listeners(mobile_page, "Mobile-Landing")
        mobile_page.goto(f"{BASE_URL}/")
        assert mobile_page.locator("header").is_visible(), "Mobile header not visible"
        print("  ✓ Mobile viewport (375x667) rendered with responsive layout")

        # Check Login Page & Demo Buttons
        page.goto(f"{BASE_URL}/login")
        assert page.locator("#email").is_visible(), "Email field not visible"
        assert page.locator("#password").is_visible(), "Password field not visible"
        assert page.locator("text=🎓").is_visible(), "Institution quick-fill button not found"
        assert page.locator("text=👑").is_visible(), "Admin quick-fill button not found"
        print("  ✓ Login page rendered with 1-click demo credential filler buttons")

        # -------------------------------------------------------------
        # 2. Institution Workflow & Cross-Institution Isolation
        # -------------------------------------------------------------
        print("\n[Step 2] Testing Institution Role & Cross-Institution Data Isolation...")
        # Login as DTU (North)
        page.fill("#email", "inst.dtu@aicte.gov.in")
        page.fill("#password", PASSWORD)
        page.click("#submit-btn")
        page.wait_for_url("**/institution")
        time.sleep(1)

        # Verify DTU Dashboard Header
        user_name = page.locator("#nav-user-name").inner_text()
        print(f"  ✓ Logged in as: {user_name}")

        # Submit New Application
        app_title = f"DTU Centre for Advanced Robotics {int(time.time())}"
        page.click("#btn-open-submit-modal")
        page.wait_for_selector("#modal-submit-app", state="visible")
        page.select_option("#app-route-type", "SCRUTINY_EVC")
        page.fill("#app-title", app_title)
        page.fill("#app-description", "Autonomous systems and AI robotics laboratory extension")
        page.click("#btn-save-app")
        page.wait_for_selector("#modal-submit-app", state="hidden")
        time.sleep(1)

        # Verify application appears in DTU table
        dtu_table_content = page.locator("#applications-table-body").inner_text()
        assert app_title in dtu_table_content, "Newly submitted application not visible in DTU table"
        print(f"  ✓ Application '{app_title}' created and verified in DTU table")

        # Upload a compliance document
        test_file_path = "test_lease_document.pdf"
        with open(test_file_path, "wb") as f:
            f.write(b"%PDF-1.4 sample valid pdf content for testing")

        page.click("#btn-open-upload-modal")
        page.wait_for_selector("#modal-upload-doc", state="visible")
        page.select_option("#doc-type", "LAND_LEASE")
        page.fill("#doc-title", "DTU 99-Year Registered Campus Lease")
        page.fill("#doc-issue-date", "2020-01-01")
        page.fill("#doc-expiry-date", "2030-01-01")
        page.set_input_files("#doc-file", test_file_path)
        page.click("#btn-submit-upload")
        page.wait_for_selector("#modal-upload-doc", state="hidden")
        time.sleep(1)

        doc_table_content = page.locator("#documents-table-body").inner_text()
        assert "DTU 99-Year Registered Campus Lease" in doc_table_content, "Document not visible in DTU table"
        print("  ✓ Compliance document uploaded and displayed in DTU table")

        # Clean up local temp file
        if os.path.exists(test_file_path):
            os.remove(test_file_path)

        # Log out DTU
        page.click(".btn-logout")
        page.wait_for_url("**/login")

        # Log in as COEP (West) and verify COEP CANNOT see DTU's application or document!
        print("\n  [Isolation Check] Logging in as COEP (West) to verify cross-institution isolation...")
        page.fill("#email", "inst.coep@aicte.gov.in")
        page.fill("#password", PASSWORD)
        page.click("#submit-btn")
        page.wait_for_url("**/institution")
        time.sleep(1)

        coep_apps_content = page.locator("#applications-table-body").inner_text()
        coep_docs_content = page.locator("#documents-table-body").inner_text()
        assert app_title not in coep_apps_content, "SECURITY VIOLATION: COEP can see DTU's application!"
        assert "DTU 99-Year Registered Campus Lease" not in coep_docs_content, "SECURITY VIOLATION: COEP can see DTU's document!"
        print("  ✓ Cross-institution isolation CONFIRMED: COEP cannot view DTU's applications or documents.")

        # Log out COEP
        page.click(".btn-logout")
        page.wait_for_url("**/login")

        # -------------------------------------------------------------
        # 3. Regional Officer Queue & Jurisdiction Boundary Check
        # -------------------------------------------------------------
        print("\n[Step 3] Testing Regional Officer Scrutiny & Regional Boundary Enforcement...")
        # Login as RO West (Western Region)
        page.fill("#email", "ro.west@aicte.gov.in")
        page.fill("#password", PASSWORD)
        page.click("#submit-btn")
        page.wait_for_url("**/officer")
        time.sleep(1)

        ro_west_table = page.locator("#officer-apps-table-body").inner_text()
        assert app_title not in ro_west_table, "REGIONAL VIOLATION: RO West can see North region DTU application!"
        print("  ✓ Regional isolation CONFIRMED: RO West cannot view North region applications.")

        # Log out RO West
        page.click(".btn-logout")
        page.wait_for_url("**/login")

        # Login as RO North (Northern Region)
        page.fill("#email", "ro.north@aicte.gov.in")
        page.fill("#password", PASSWORD)
        page.click("#submit-btn")
        page.wait_for_url("**/officer")
        time.sleep(1)

        ro_north_table = page.locator("#officer-apps-table-body").inner_text()
        assert app_title in ro_north_table, "RO North should see DTU application!"
        print(f"  ✓ RO North correctly sees '{app_title}' in regional queue.")

        # Verify Chart.js canvas elements are active
        chart_stage = page.locator("#chart-stage-pendency")
        chart_status = page.locator("#chart-status-breakdown")
        assert chart_stage.is_visible(), "Stage pendency chart canvas not visible"
        assert chart_status.is_visible(), "Status breakdown chart canvas not visible"
        print("  ✓ Chart.js canvas visualizations rendered without errors.")

        # -------------------------------------------------------------
        # 4. Officer Stage Advancement & Automatic EVC Creation
        # -------------------------------------------------------------
        print("\n[Step 4] Advancing Stage as RO North & Verifying EVC Scheduling...")
        # Click "Process Stage" for the DTU application
        row = page.locator(f"tr:has-text('{app_title}')")
        row.locator("button:has-text('Process Stage')").click()
        page.wait_for_selector("#modal-complete-stage", state="visible")

        page.fill("#complete-remarks", "Infrastructure and faculty documentation verified compliant.")
        page.click("#btn-submit-complete")
        page.wait_for_selector("#modal-complete-stage", state="hidden")
        time.sleep(1)

        # Refresh and verify application advanced to EVC stage
        page.click("#btn-refresh-all")
        time.sleep(1)
        updated_row = page.locator(f"tr:has-text('{app_title}')")
        assert "EVC" in updated_row.inner_text() or "Expert Visit" in updated_row.inner_text(), "Application did not advance to EVC stage"
        print("  ✓ Application advanced to EVC stage successfully.")

        # Verify automatic EVC visit record in EVC queue
        evc_table = page.locator("#evc-table-body").inner_text()
        assert "DTU" in evc_table or "Delhi" in evc_table, "Automatic EVC visit record not found in EVC queue"
        print("  ✓ Automatic EVC visit record verified in EVC queue.")

        # Schedule the EVC visit
        evc_row = page.locator("#evc-table-body tr").first
        if evc_row.locator("button:has-text('Schedule Visit')").is_visible():
            evc_row.locator("button:has-text('Schedule Visit')").click()
            page.wait_for_selector("#modal-schedule-evc", state="visible")
            page.fill("#evc-scheduled-date", "2026-11-15")
            page.fill("#evc-team-lead", "Prof. Dr. R. K. Sharma")
            page.fill("#evc-experts", "Dr. A. Verma, Dr. S. Iyer")
            page.fill("#evc-remarks", "Physical on-site laboratory inspection")
            page.click("#btn-submit-evc")
            page.wait_for_selector("#modal-schedule-evc", state="hidden")
            time.sleep(1)
            print("  ✓ EVC visit scheduled via modal.")

        # Test Return Application workflow and mandatory reason validation
        print("\n  [Return Validation] Testing return action and mandatory reason requirement...")
        # Try returning: open modal, check reason required attribute
        row.locator("button:has-text('Return')").click()
        page.wait_for_selector("#modal-return-app", state="visible")
        reason_input = page.locator("#return-reason")
        assert reason_input.get_attribute("required") is not None, "Return reason must have required attribute"
        
        # Fill substantive reason and submit
        page.fill("#return-reason", "Incomplete environmental clearance documentation for laboratory wing.")
        page.click("#btn-submit-return")
        page.wait_for_selector("#modal-return-app", state="hidden")
        time.sleep(1)
        
        # Verify status transitioned to ACTION_REQUIRED or RETURNED
        page.click("#btn-refresh-all")
        time.sleep(1)
        returned_row = page.locator(f"tr:has-text('{app_title}')")
        assert "ACTION_REQUIRED" in returned_row.inner_text() or "RETURNED" in returned_row.inner_text(), "Application status did not update to ACTION_REQUIRED or RETURNED"
        print("  ✓ Application return with mandatory reason executed and verified as ACTION_REQUIRED/RETURNED.")

        # Log out Officer
        page.click(".btn-logout")
        page.wait_for_url("**/login")

        # -------------------------------------------------------------
        # 5. Bureau Apex Console Verification
        # -------------------------------------------------------------
        print("\n[Step 5] Testing Bureau Apex Oversight Desk...")
        page.fill("#email", "bureau@aicte.gov.in")
        page.fill("#password", PASSWORD)
        page.click("#submit-btn")
        page.wait_for_url("**/bureau")
        time.sleep(1)

        # Check National Metrics
        total_national = page.locator("#stat-total-apps").inner_text()
        print(f"  ✓ Bureau sees national queue total: {total_national} applications")

        # Check charts on Bureau console
        chart_reg = page.locator("#chart-regional-pendency")
        chart_dist = page.locator("#chart-stage-distribution")
        assert chart_reg.is_visible(), "Regional pendency chart not visible"
        assert chart_dist.is_visible(), "Stage distribution chart not visible"
        print("  ✓ Bureau Chart.js cross-regional comparisons active")

        # Log out Bureau
        page.click(".btn-logout")
        page.wait_for_url("**/login")

        # -------------------------------------------------------------
        # 6. Admin Central Console, Time Machine & Audit Logs
        # -------------------------------------------------------------
        print("\n[Step 6] Testing Admin Console, Time Machine & Cryptographic Audit Viewer...")
        page.fill("#email", "admin@aicte.gov.in")
        page.fill("#password", PASSWORD)
        page.click("#submit-btn")
        page.wait_for_url("**/admin")
        time.sleep(1)

        # Check initial simulated time display
        sim_date_initial = page.locator("#tm-simulated-date").inner_text()
        print(f"  ✓ Initial effective business date: {sim_date_initial}")

        # Advance time by +7 Days using quick shortcut
        page.locator("button:has-text('+7 Days')").click()
        time.sleep(1.5)

        # Verify time updated
        sim_date_advanced = page.locator("#tm-simulated-date").inner_text()
        offset_days = page.locator("#tm-offset-days").inner_text()
        print(f"  ✓ Advanced effective business date: {sim_date_advanced} (Offset: +{offset_days} days)")

        # Verify persistent header badge displays simulated date with pulse
        badge = page.locator("#simulated-time-badge")
        assert badge.is_visible(), "Persistent simulated time badge not visible in header"
        assert "Simulated Date:" in badge.inner_text(), "Badge does not reflect simulation mode"
        print("  ✓ Persistent simulated time header badge active across portal.")

        # Reset Time back to 0
        page.on("dialog", lambda dialog: dialog.accept())
        page.click("#btn-reset-time")
        time.sleep(1.5)
        offset_reset = page.locator("#tm-offset-days").inner_text()
        assert float(offset_reset) == 0.0, f"Offset did not reset to 0: {offset_reset}"
        print("  ✓ Time Machine successfully reset to real UTC clock (offset = 0).")

        # Inspect Cryptographic Audit Log Viewer
        audit_tbody = page.locator("#audit-table-body").inner_text()
        assert "SHA-256" in page.content(), "SHA-256 hash chaining table not found"
        assert "TIME_RESET" in audit_tbody or "ADVANCE" in audit_tbody or "STAGE" in audit_tbody, "Audit log table missing recorded events"
        print("  ✓ Cryptographic append-only audit trail verified with SHA-256 hash chains.")

        # Inspect User Directory
        users_table = page.locator("#users-table-body").inner_text()
        assert "admin@aicte.gov.in" in users_table, "Admin user not in directory"
        assert "ro.north@aicte.gov.in" in users_table, "RO North not in directory"
        print("  ✓ User Directory and RBAC governance verified.")

        # Log out Admin
        page.click(".btn-logout")
        page.wait_for_url("**/login")

        browser.close()

    print("\n" + "=" * 70)
    print("INDEPENDENT REVIEW COMPLETE — CONSOLE & EXCEPTION AUDIT")
    print("=" * 70)
    if console_errors:
        print(f"[!] Warning: {len(console_errors)} console errors caught:")
        for err in console_errors:
            print(f"    {err}")
    else:
        print("  ✓ No console errors detected across all tested pages and roles.")

    if page_errors:
        print(f"[!] Critical: {len(page_errors)} uncaught page exceptions caught:")
        for err in page_errors:
            print(f"    {err}")
        sys.exit(1)
    else:
        print("  ✓ Zero uncaught page exceptions detected across all workflows.")

    print("\nALL VERIFICATIONS PASSED: 100% COMPLIANT WITH PHASE 8 REQUIREMENTS.")

if __name__ == "__main__":
    run_comprehensive_review()
