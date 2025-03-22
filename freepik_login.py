import os
import platform
import time
import re
import logging
import random
from playwright.sync_api import sync_playwright
from twocaptcha import TwoCaptcha, NetworkException, ApiException, TimeoutException, ValidationException

logger = logging.getLogger(__name__)

# Constants
AUTH_STATE_PATH = "auth_state.json"

# List of common user agents to rotate
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.58",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5.1 Safari/605.1.15"
]

def handle_cookie_consent(page):
    """
    Dismiss the cookie consent banner if it appears.
    Updated to handle multiple common cookie consent patterns.
    """
    try:
        # Method 1: Common cookie accept button patterns
        selectors = [
            "button:has-text('Accept all cookies')",
            "button:has-text('Accept All')",
            "button:has-text('Accept all')",
            "button:has-text('I Accept')",
            "button:has-text('Accept')",
            "button:has-text('Allow all')",
            "button:has-text('Allow cookies')",
            "button:has-text('Agree')",
            "button:has-text('I agree')",
            "button:has-text('Got it')",
            "button:has-text('I understand')",
            "button:has-text('I consent')",
            "button.cookie-accept-button",
            ".cookie-banner .accept",
            "[data-testid='cookie-accept']",
            "#onetrust-accept-btn-handler",
            "[aria-label='Accept cookies']",
            ".cookie-consent-accept"
        ]
        
        for selector in selectors:
            try:
                consent_button = page.locator(selector).first
                if consent_button.is_visible(timeout=2000):
                    consent_button.click(timeout=5000)
                    logger.info(f"Cookie consent dismissed using selector: {selector}")
                    return True
            except Exception as e:
                logger.debug(f"Failed to click cookie selector {selector}: {e}")
                continue
        
        # Method 2: Look for cookies in iframes
        try:
            cookie_frames = page.frame_locator("iframe[title*='Cookie'], iframe[src*='cookie'], iframe[id*='cookie']").all()
            for frame_idx, frame in enumerate(cookie_frames):
                for selector in selectors:
                    try:
                        btn = frame.locator(selector).first
                        if btn.is_visible(timeout=2000):
                            btn.click(timeout=5000)
                            logger.info(f"Cookie consent dismissed in iframe {frame_idx} using selector: {selector}")
                            return True
                    except:
                        continue
        except Exception as e:
            logger.debug(f"Error in cookie iframe handling: {e}")
        
        # Method 3: Try JavaScript approach to find and click cookie buttons
        try:
            # Use JavaScript to find and click cookie consent buttons
            page.evaluate("""() => {
                const buttonTexts = [
                    'accept all cookies', 'accept all', 'accept cookies', 
                    'i accept', 'accept', 'allow all', 'allow cookies',
                    'agree', 'i agree', 'got it', 'i understand'
                ];
                
                // Helper function to check if element's text contains any of the target phrases
                const hasMatchingText = (element) => {
                    const text = element.innerText.toLowerCase();
                    return buttonTexts.some(btnText => text.includes(btnText));
                };
                
                // First try to find buttons with the specific text
                const allButtons = Array.from(document.querySelectorAll('button'));
                const cookieButton = allButtons.find(hasMatchingText);
                
                if (cookieButton) {
                    cookieButton.click();
                    return true;
                }
                
                // Try to find links or other elements that might be cookie consent buttons
                const allLinks = Array.from(document.querySelectorAll('a'));
                const cookieLink = allLinks.find(hasMatchingText);
                
                if (cookieLink) {
                    cookieLink.click();
                    return true;
                }
                
                // Try common cookie consent IDs and classes
                const commonSelectors = [
                    '#onetrust-accept-btn-handler',
                    '.cc-accept',
                    '.cookie-accept',
                    '.consent-accept',
                    '#accept-cookies',
                    '.cookie-agree',
                    '[data-cookiebanner="accept_button"]'
                ];
                
                for (const selector of commonSelectors) {
                    const element = document.querySelector(selector);
                    if (element) {
                        element.click();
                        return true;
                    }
                }
                
                return false;
            }""")
            
            # Wait a moment for any animations to complete
            time.sleep(1)
            logger.info("Attempted cookie consent dismissal using JavaScript")
        except Exception as js_error:
            logger.debug(f"JavaScript cookie handling error: {js_error}")
        
        return False
        
    except Exception as e:
        logger.debug(f"Error in cookie consent handling: {e}")
        return False

def detect_recaptcha(page):
    """Detect if reCAPTCHA is present on the page and return the site key."""
    # Try multiple ways to find the reCAPTCHA site key
    site_key = None
    
    # Method 1: Check for the standard g-recaptcha div
    try:
        recaptcha_element = page.locator("div.g-recaptcha").first
        if recaptcha_element.is_visible(timeout=2000):
            site_key = recaptcha_element.get_attribute("data-sitekey")
            if site_key:
                logger.info(f"Method 1: Found standard reCAPTCHA element with site key: {site_key}")
                return site_key, "checkbox"
    except Exception as e:
        logger.debug(f"Method 1 recaptcha detection error: {e}")
    
    # Method 2: Check for invisible reCAPTCHA
    try:
        invisible_recaptcha = page.locator(".grecaptcha-badge")
        if invisible_recaptcha.is_visible(timeout=2000):
            # For invisible reCAPTCHA we need to extract the site key from the script
            site_key = page.evaluate("""() => {
                const scripts = document.querySelectorAll('script');
                for (let script of scripts) {
                    const match = script.innerHTML.match(/sitekey=['"]([^'"]+)['"]/);
                    if (match) return match[1];
                }
                return null;
            }""")
            if site_key:
                logger.info(f"Method 2: Found invisible reCAPTCHA with site key: {site_key}")
                return site_key, "invisible"
    except Exception as e:
        logger.debug(f"Method 2 recaptcha detection error: {e}")
    
    # Method 3: Check for reCAPTCHA iframe
    try:
        iframe = page.frame_locator("iframe[src*='recaptcha']").first
        if iframe:
            src = page.locator("iframe[src*='recaptcha']").first.get_attribute("src")
            key_match = src and src.split("k=")[1].split("&")[0]
            if key_match:
                logger.info(f"Method 3: Found reCAPTCHA iframe with site key: {key_match}")
                return key_match, "iframe"
    except Exception as e:
        logger.debug(f"Method 3 recaptcha detection error: {e}")
    
    # Method 4: Check for recaptcha error message
    try:
        if page.locator("text=Recaptcha validation failed").is_visible(timeout=2000):
            # If we see an error but couldn't find the site key, try to extract it from the page content
            site_key = page.evaluate("""() => {
                return document.body.innerHTML.match(/['"](6L[a-zA-Z0-9_-]{38})['"]/)?.[1] || null;
            }""")
            if site_key:
                logger.info(f"Method 4: Found reCAPTCHA from error message with site key: {site_key}")
                return site_key, "error_detected"
    except Exception as e:
        logger.debug(f"Method 4 recaptcha detection error: {e}")
    
    # Method 5: Look for captcha in the page source code
    try:
        site_key = page.evaluate("""() => {
            // Common patterns for reCAPTCHA site keys in HTML
            const patterns = [
                /['"]?sitekey['"]?\\s*:\\s*['"]([0-9A-Za-z_-]{40})['"]/, // JSON config
                /data-sitekey=['"]([0-9A-Za-z_-]{40})['"]/, // HTML attribute
                /render=['"]([0-9A-Za-z_-]{40})['"]/, // V3 reCAPTCHA
                /['"]?key['"]?\\s*:\\s*['"]([0-9A-Za-z_-]{40})['"]/ // Another JSON pattern
            ];
            
            const html = document.documentElement.outerHTML;
            
            for (const pattern of patterns) {
                const match = html.match(pattern);
                if (match && match[1]) return match[1];
            }
            
            return null;
        }""")
        
        if site_key:
            logger.info(f"Method 5: Found reCAPTCHA site key in page source: {site_key}")
            return site_key, "source_code"
    except Exception as e:
        logger.debug(f"Method 5 recaptcha detection error: {e}")
    
    # Method 6: Look for any recaptcha-related elements
    try:
        has_recaptcha_elements = page.evaluate("""() => {
            // Check for common reCAPTCHA elements
            const recaptchaElements = 
                document.querySelector('.g-recaptcha') ||
                document.querySelector('.grecaptcha-badge') ||
                document.querySelector('iframe[src*="recaptcha"]') ||
                document.querySelector('[data-sitekey]') ||
                document.querySelector('[data-recaptcha-key]') ||
                document.querySelector('#g-recaptcha-response');
                
            return !!recaptchaElements;
        }""")
        
        if has_recaptcha_elements:
            logger.info("Method 6: Detected reCAPTCHA elements but couldn't find site key")
    except Exception as e:
        logger.debug(f"Method 6 recaptcha detection error: {e}")
    
    logger.info("No reCAPTCHA detected on the page")
    return None, None

def solve_recaptcha(page, api_key):
    """Solve reCAPTCHA if detected using 2Captcha."""
    logger.info("Checking for reCAPTCHA...")
    
    # Allow time for the CAPTCHA to fully load
    time.sleep(3)
    
    # Detect if there's a reCAPTCHA on the page
    site_key, captcha_type = detect_recaptcha(page)
    
    if not site_key:
        logger.info("No reCAPTCHA detected or site key not found.")
        return False
    
    logger.info(f"reCAPTCHA detected (type: {captcha_type}, sitekey: {site_key}). Sending to 2Captcha...")
    
    # Use 2Captcha service to solve
    solver = TwoCaptcha(api_key)
    try:
        # Use the proper method for solving reCAPTCHA as described in the documentation
        is_invisible = captcha_type == "invisible" or captcha_type == "iframe"
        
        # This is the proper way to solve reCAPTCHA using the 2captcha-python library
        result = solver.recaptcha(
            sitekey=site_key,
            url=page.url,
            invisible=1 if is_invisible else 0,
            version='v2'
        )
        
        # Extract the token from the result
        if isinstance(result, dict) and 'code' in result:
            token = result['code']
        else:
            token = result
            
        if not token:
            raise Exception("No token received from 2Captcha.")
        
    except (NetworkException, ApiException, TimeoutException, ValidationException) as e:
        logger.error(f"reCAPTCHA solving failed: {e}")
        return False
    except Exception as e:
        logger.error(f"reCAPTCHA solving failed: {e}")
        return False
    
    logger.info("CAPTCHA solved. Injecting token into page...")
    
    # Inject the token in multiple potential locations
    try:
        # Method 1: Set the g-recaptcha-response textarea value
        page.evaluate("""(token) => {
            // Handle standard reCAPTCHA response
            let textarea = document.getElementById('g-recaptcha-response');
            if (!textarea) {
                // Create it if it doesn't exist
                textarea = document.createElement('textarea');
                textarea.id = 'g-recaptcha-response';
                textarea.name = 'g-recaptcha-response';
                textarea.style.display = 'none';
                document.body.appendChild(textarea);
            }
            textarea.value = token;
            
            // Handle invisible reCAPTCHA responses (there might be multiple)
            document.querySelectorAll('textarea[id^="g-recaptcha-response-"]').forEach(el => {
                el.value = token;
            });
            
            // Trigger reCAPTCHA callback if it exists
            if (typeof ___grecaptcha_cfg !== 'undefined') {
                // Attempt to trigger the callback
                document.dispatchEvent(new Event('recaptcha-verified'));
                
                // Try to trigger the reCAPTCHA callback functions
                try {
                    // Find any callback names from the reCAPTCHA config
                    const callbackNames = [];
                    Object.entries(___grecaptcha_cfg.clients).forEach(([_, client]) => {
                        if (client && typeof client === 'object') {
                            // Search for callback names in the client properties
                            Object.values(client).forEach(value => {
                                if (typeof value === 'object' && value !== null && 'callback' in value) {
                                    // Found a callback function name, save it
                                    if (typeof value.callback === 'string') {
                                        callbackNames.push(value.callback);
                                    }
                                }
                            });
                        }
                    });
                    
                    // Execute each callback function found
                    callbackNames.forEach(callbackName => {
                        if (typeof window[callbackName] === 'function') {
                            console.log('Executing callback function: ' + callbackName);
                            window[callbackName](token);
                        }
                    });
                } catch (e) {
                    console.error('Error finding or executing reCAPTCHA callbacks:', e);
                }
            }
        }""", token)
        
        # Wait a moment for the token to be processed
        time.sleep(2)
        
        # Method 2: Try to find and click a submit button if the form didn't auto-submit
        try:
            # Try multiple selectors for submit buttons
            submit_selectors = [
                "button[type='submit']", 
                "input[type='submit']",
                "button.submit-button",
                "button:has-text('Submit')",
                "button:has-text('Continue')",
                "button.form-submit",
                "button.g-recaptcha-submit"
            ]
            
            for selector in submit_selectors:
                try:
                    submit_button = page.locator(selector).first
                    if submit_button.is_visible(timeout=2000):
                        submit_button.click(timeout=5000)
                        logger.info(f"Clicked submit button using selector: {selector}")
                        break
                except:
                    continue
        except:
            # If no submit button, the form might auto-submit with the token
            logger.info("No submit button found or clicked")
        
        # Method 3: For specific contexts like login, try clicking the login button
        try:
            login_selectors = [
                "button:has-text('Log in')",
                "button:has-text('Login')",
                "button:has-text('Sign in')",
                "button[data-testid*='login']",
                "button.login-button"
            ]
            
            for selector in login_selectors:
                try:
                    login_btn = page.locator(selector).first
                    if login_btn.is_visible(timeout=2000):
                        login_btn.click(timeout=5000)
                        logger.info(f"Clicked login button using selector: {selector}")
                        break
                except:
                    continue
        except:
            logger.info("No login button found or clicked")
        
        # Wait for navigation or response after submitting
        page.wait_for_load_state("networkidle", timeout=15000)
        
        # Verify CAPTCHA was accepted by checking for reCAPTCHA error or success indicators
        if page.locator("text=Recaptcha validation failed").is_visible(timeout=2000):
            logger.error("CAPTCHA validation still failed after submission.")
            return False
            
        logger.info("CAPTCHA appears to be successfully solved.")
        return True
    
    except Exception as e:
        logger.error(f"Error injecting CAPTCHA solution: {e}")
        return False

def check_login_status(page):
    """Check if we're logged in by looking for various indicators."""
    # Method 1: Check for traditional user menu/icons
    try:
        if page.locator(".user-menu, .user-avatar, .profile-icon, .user-account, .account-menu").is_visible(timeout=5000):
            logger.info("Login detected via user menu/avatar")
            return True
    except:
        pass
    
    # Method 2: Check for "Start creating" button
    try:
        if page.locator("button:has-text('Start creating')").is_visible(timeout=5000):
            logger.info("Login detected via 'Start creating' button")
            return True
    except:
        pass
    
    # Method 3: Check for a profile picture in the top-right corner
    try:
        profile_pic = page.locator("img[alt*='profile'], .profile-image, header img:last-child, .avatar-image").last
        if profile_pic.is_visible(timeout=5000):
            logger.info("Login detected via profile picture")
            return True
    except:
        pass
    
    # Method 4: Check for URL indicating logged-in state
    if any(x in page.url for x in ['/editor', '/dashboard', '/projects', '/collections', '/profile']):
        logger.info("Login detected via URL pattern")
        return True
    
    # Method 5: Check for "Here's where you left off" text
    try:
        if page.locator("text=Here's where you left off").is_visible(timeout=5000):
            logger.info("Login detected via 'Here's where you left off' text")
            return True
    except:
        pass
    
    # Method 6: Check for "My downloads" or similar text that only appears when logged in
    try:
        if page.locator("text=My downloads, text=My collections, text=My account").is_visible(timeout=5000):
            logger.info("Login detected via user-specific text")
            return True
    except:
        pass
    
    # Method 7: Check if the login form is no longer visible
    try:
        if not page.locator("input[name='email'], input[name='password'], input[type='password']").is_visible(timeout=3000):
            # Additional check: Make sure we're not on a login/registration page
            if not any(x in page.url for x in ['/log-in', '/register', '/signup']):
                logger.info("Login detected via absence of login form")
                return True
    except:
        pass
    
    # Method 8: Try to detect login status via JavaScript
    try:
        is_logged_in = page.evaluate("""() => {
            // Check for common auth-related cookies
            const hasCookies = document.cookie.includes('auth') || document.cookie.includes('token') || document.cookie.includes('session');
            
            // Check for common auth-related localStorage items
            const hasLocalStorage = localStorage.getItem('token') || localStorage.getItem('user') || localStorage.getItem('auth');
            
            // Check for login/user elements in the DOM
            const userElements = document.querySelector('.user-menu') || 
                document.querySelector('.avatar') || 
                document.querySelector('.profile-pic') ||
                document.querySelector('[data-testid="user-menu"]');
                
            // Check for login button absence - if we're logged in, there shouldn't be login buttons
            const loginButtons = document.querySelectorAll('a[href*="login"], a[href*="log-in"], button:contains("Log in")');
            const noLoginButtons = loginButtons.length === 0;
            
            return !!(hasCookies || hasLocalStorage || userElements || noLoginButtons);
        }""")
        
        if is_logged_in:
            logger.info("Login detected via JavaScript checks")
            return True
    except Exception as e:
        logger.error(f"JavaScript login detection failed: {e}")
    
    # If we get here, no login indicators were found
    logger.info("No login indicators detected - user is not logged in")
    return False

def login_to_freepik(browser, page, email: str, password: str, apikey_2captcha: str):
    """Log in to Freepik using provided credentials. Returns tuple of (success, page)."""
    logger.info("Logging in to Freepik...")
    try:
        # Select a random user agent
        user_agent = random.choice(USER_AGENTS)
        logger.info(f"Using User-Agent: {user_agent}")
        
        # Use saved auth state if available
        if os.path.exists(AUTH_STATE_PATH):
            logger.info("Using saved authentication state.")
            current_context = page.context
            context = browser.new_context(
                storage_state=AUTH_STATE_PATH,
                accept_downloads=True,
                user_agent=user_agent,
                viewport={"width": 1920, "height": 1080}
            )
            new_page = context.new_page()
            new_page.set_default_timeout(60000)
            
            # First go to homepage instead of directly checking login
            new_page.goto("https://www.freepik.com")
            new_page.wait_for_load_state("networkidle", timeout=30000)
            handle_cookie_consent(new_page)
            time.sleep(3)  # Give it a moment to settle
            
            # Check if we're already logged in
            if check_login_status(new_page):
                logger.info("Already logged in with saved authentication state.")
                # Close the old context and page
                if current_context:
                    current_context.close()
                # Return success and the new page
                return True, new_page
            else:
                logger.info("Saved authentication state is expired. Proceeding with fresh login.")
                # Close the new context and continue with the original page
                context.close()
                # Delete invalid auth state
                os.remove(AUTH_STATE_PATH)
        
        # Fresh login process - first clear all cookies
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1920, "height": 1080},
            user_agent=user_agent
        )
        page = context.new_page()
        page.set_default_timeout(60000)
            
        # First go to homepage to establish a session
        page.goto("https://www.freepik.com")
        page.wait_for_load_state("networkidle")
        handle_cookie_consent(page)
        time.sleep(2)
            
        # Now navigate directly to the login page
        page.goto("https://www.freepik.com/log-in?client_id=freepik&lang=en")
        page.wait_for_load_state("networkidle")
        time.sleep(3)  # Wait for dynamic content

        # Handle any cookie banner that might block the button
        handle_cookie_consent(page)
        
        # Check if we need to click "Continue with email" or if we're already at email/password form
        email_input_visible = False
        try:
            if page.locator("input[name='email']").is_visible(timeout=5000):
                email_input_visible = True
                logger.info("Email input is already visible")
        except Exception as e:
            logger.error(f"Error checking for email input: {e}")
        
        if not email_input_visible:
            # Try multiple ways to find the "Continue with email" button
            email_button_selectors = [
                "button:has-text('Continue with email')",
                "button:has-text('Sign in with email')",
                "button:has-text('Email')",
                "[data-testid='email-login']",
                ".email-login-button"
            ]
            
            button_clicked = False
            for selector in email_button_selectors:
                try:
                    login_btn = page.locator(selector).first
                    if login_btn.is_visible(timeout=3000):
                        login_btn.scroll_into_view_if_needed()
                        login_btn.click(force=True, timeout=10000)
                        logger.info(f"Clicked email button using selector: {selector}")
                        button_clicked = True
                        break
                except Exception as e:
                    logger.error(f"Failed to click using selector {selector}: {e}")
            
            if not button_clicked:
                logger.error("Could not find or click any email login button. Trying JavaScript click...")
                
                try:
                    # Try direct JavaScript approach
                    page.evaluate("""() => {
                        // Find buttons with text containing "email"
                        const buttons = Array.from(document.querySelectorAll('button'));
                        const emailButton = buttons.find(btn => 
                            btn.innerText.toLowerCase().includes('email') || 
                            btn.innerText.toLowerCase().includes('continue with email')
                        );
                        
                        if (emailButton) {
                            emailButton.click();
                            console.log('JS clicked email button');
                        } else {
                            console.log('No email button found via JS');
                        }
                    }""")
                    
                    time.sleep(3)  # Wait for potential navigation
                except Exception as js_error:
                    logger.error(f"JavaScript email button click failed: {js_error}")
            
            # Wait a moment for the form to appear after clicking
            time.sleep(3)

        # Look for email input field with multiple selectors
        email_selectors = [
            "input[name='email']", 
            "input[type='email']", 
            "input[placeholder*='email' i]",
            "input#email",
            "[data-testid='email-input']"
        ]
        
        email_input = None
        for selector in email_selectors:
            try:
                potential_input = page.locator(selector).first
                if potential_input.is_visible(timeout=3000):
                    email_input = potential_input
                    logger.info(f"Found email input using selector: {selector}")
                    break
            except Exception as e:
                logger.error(f"Selector {selector} failed: {e}")
                
        if not email_input:
            logger.error("Could not find visible email input field after multiple attempts")
            return False, page
            
        # Now wait for email/password fields (using the found email_input)
        email_input.wait_for(state="visible", timeout=10000)
        
        # Check if email is already filled
        current_email = email_input.input_value()
        logger.info(f"Current email value: '{current_email}'")
        
        if not current_email or current_email != email:
            # Fill email only if it's not already filled with the correct email
            email_input.fill("")  # Clear it first
            time.sleep(0.5)
            email_input.type(email, delay=100)  # Type it character by character
            logger.info(f"Filled email field with: {email}")
        
        # Find password field with multiple selectors
        password_selectors = [
            "input[name='password']",
            "input[type='password']",
            "input[placeholder*='password' i]",
            "input#password",
            "[data-testid='password-input']"
        ]
        
        password_input = None
        for selector in password_selectors:
            try:
                potential_input = page.locator(selector).first
                if potential_input.is_visible(timeout=3000):
                    password_input = potential_input
                    logger.info(f"Found password input using selector: {selector}")
                    break
            except:
                continue
                
        if not password_input:
            logger.error("Could not find visible password input field")
            return False, page
            
        # Fill password field
        password_input.fill("")  # Clear it first
        time.sleep(0.5)
        password_input.type(password, delay=100)  # Type it character by character
        logger.info("Filled password field")

        # Attempt to check "Stay logged in" if present
        try:
            page.get_by_role("checkbox", name="Stay logged in").check(timeout=5000)
            logger.info("Checked 'Stay logged in' box")
        except Exception as e:
            logger.error(f"Could not check 'Stay logged in' box: {e}")
            try:
                # Try alternative selectors for the checkbox
                checkbox_selectors = [
                    "input[type='checkbox']",
                    "input.remember-me",
                    "[data-testid='remember-me']"
                ]
                
                for selector in checkbox_selectors:
                    try:
                        checkbox = page.locator(selector).first
                        if checkbox.is_visible(timeout=2000):
                            if not checkbox.is_checked():
                                checkbox.check(timeout=5000)
                                logger.info(f"Checked remember me box using selector: {selector}")
                            break
                    except:
                        continue
            except Exception as e2:
                logger.error(f"Alternative checkbox checking failed: {e2}")

        # Check for CAPTCHA BEFORE clicking login button
        site_key, captcha_type = detect_recaptcha(page)
        if site_key:
            logger.info(f"CAPTCHA detected before login submission. Type: {captcha_type}, Site key: {site_key}")
            captcha_solved = solve_recaptcha(page, apikey_2captcha)
            if not captcha_solved:
                logger.error("Failed to solve CAPTCHA before login.")
                return False, page
            logger.info("CAPTCHA solved successfully before login submission")

        # Find and click the "Log in" button using multiple selectors
        login_button_selectors = [
            "button:has-text('Log in')",
            "button:has-text('Login')",
            "button:has-text('Sign in')",
            "button[type='submit']",
            "[data-testid='login-button']",
            "button.login-button",
            "button.signin-button"
        ]
        
        login_button_clicked = False
        for selector in login_button_selectors:
            try:
                login_btn = page.locator(selector).first
                if login_btn.is_visible(timeout=3000):
                    login_btn.click(timeout=10000)
                    logger.info(f"Clicked login button using selector: {selector}")
                    login_button_clicked = True
                    break
            except Exception as e:
                logger.error(f"Failed to click login button with selector {selector}: {e}")
        
        if not login_button_clicked:
            logger.error("Could not find or click any login button. Trying JavaScript click...")
            
            try:
                # Try direct JavaScript approach
                page.evaluate("""() => {
                    // Find buttons with text related to login
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const loginButton = buttons.find(btn => 
                        btn.innerText.toLowerCase().includes('log in') || 
                        btn.innerText.toLowerCase().includes('login') ||
                        btn.innerText.toLowerCase().includes('sign in') ||
                        btn.type === 'submit'
                    );
                    
                    if (loginButton) {
                        loginButton.click();
                        console.log('JS clicked login button');
                    } else {
                        console.log('No login button found via JS');
                    }
                }""")
                
                login_button_clicked = True
                logger.info("Attempted login via JavaScript")
            except Exception as js_error:
                logger.error(f"JavaScript login button click failed: {js_error}")
                
        if not login_button_clicked:
            logger.error("Could not click any login button after multiple attempts")
            return False, page
            
        # Wait for navigation to complete
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as nav_error:
            logger.error(f"Error waiting for navigation after login: {nav_error}")
            
        # Check if we need to solve CAPTCHA after clicking login
        if page.locator("text=Recaptcha validation failed").is_visible(timeout=5000):
            logger.info("CAPTCHA challenge appeared after login click.")
            captcha_solved = solve_recaptcha(page, apikey_2captcha)
            if not captcha_solved:
                logger.error("Failed to solve CAPTCHA after login click.")
                return False, page
            
            # After solving, try clicking login again
            try:
                # Try again with each selector
                for selector in login_button_selectors:
                    try:
                        login_btn = page.locator(selector).first
                        if login_btn.is_visible(timeout=3000):
                            login_btn.click(timeout=10000)
                            logger.info(f"Clicked login button after CAPTCHA using selector: {selector}")
                            break
                    except:
                        continue
                        
                # Wait for navigation after re-click
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                logger.error(f"Error clicking login button after CAPTCHA: {e}")
                # It might have auto-submitted, so continue

        # Give the page time to fully load and potentially redirect
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(5)  # Additional wait to ensure all redirects complete
        
        # Verify login success with our improved check
        if check_login_status(page):
            logger.info("Login verified successfully!")
            
            # Save authentication state for future runs ONLY if login was successful
            page.context.storage_state(path=AUTH_STATE_PATH)
            logger.info("Authentication state saved.")
            return True, page
        else:
            logger.error("Login failed: Could not verify logged-in state.")
            
            # Check for common error messages
            error_selectors = [
                "text=Invalid email or password",
                "text=Incorrect credentials",
                "text=The credentials are incorrect",
                ".error-message",
                "[data-testid='login-error']"
            ]
            
            for selector in error_selectors:
                try:
                    error_element = page.locator(selector).first
                    if error_element.is_visible(timeout=2000):
                        error_message = error_element.text_content()
                        logger.error(f"Login error message: {error_message}")
                        break
                except:
                    continue
            
            return False, page

    except Exception as e:
        logger.error(f"Login step error: {e}")
        return False, page

def create_browser_context(headless=True):
    """Create and return a browser instance with configured context."""
    try:
        browser_launch_options = {
            "headless": headless,
            "args": [
                "--start-maximized",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
                "--window-size=1920,1080"
            ]
        }
        
        p = sync_playwright().start()
        browser = p.chromium.launch(**browser_launch_options)
        
        # Select a random user agent
        user_agent = random.choice(USER_AGENTS)
        
        # Enhanced browser context options
        context_options = {
            "accept_downloads": True,
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": user_agent,
            "permissions": ["clipboard-read", "clipboard-write"],
            "device_scale_factor": 1.0,
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "color_scheme": "light"
        }
        
        context = browser.new_context(**context_options)
        page = context.new_page()
        page.set_default_timeout(60000)
        
        # Set extra HTTP headers to mimic a real browser better
        page.set_extra_http_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })
        
        return p, browser, context, page
    except Exception as e:
        logger.error(f"Error creating browser context: {e}")
        raise