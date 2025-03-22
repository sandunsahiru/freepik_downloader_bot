import os
import time
import re
import logging
import datetime
from playwright.sync_api import sync_playwright
from freepik_login import handle_cookie_consent

# Configure logging
logger = logging.getLogger(__name__)

def extract_search_terms_from_url(resource_url):
    """
    Extract meaningful search terms from a Freepik URL.
    Improved to handle hyphenated words properly.
    """
    search_terms = []
    
    # Method 1: Extract from query parameter if present
    if "query=" in resource_url:
        query_param = resource_url.split("query=")[1].split("&")[0]
        search_terms = query_param.replace("+", " ").split()
        logger.info(f"Extracted search terms from URL query: {search_terms}")
    
    # Method 2: Extract from URL path
    elif "_" in resource_url:
        # Get the filename part before the ID
        filename = resource_url.split("/")[-1].split("_")[0]
        
        # Use regex to find all alphabetical words, handling hyphenated words better
        words = re.findall(r'[a-zA-Z]+(?:-[a-zA-Z]+)*', filename)
        
        # Split any hyphenated words into individual terms
        for word in words:
            if "-" in word:
                parts = word.split("-")
                # Only add parts that are meaningful (longer than 3 chars)
                search_terms.extend([part for part in parts if len(part) > 3])
            elif len(word) > 3:  # Only add meaningful words
                search_terms.append(word)
                
        logger.info(f"Extracted keywords from URL path: {search_terms}")
    
    # Method 3: Extract from any part of URL
    else:
        # Try to find meaningful words in the entire URL
        words = re.findall(r'[a-zA-Z]{4,}', resource_url)  # Find words of 4+ chars
        search_terms = list(set(words))  # Remove duplicates
        logger.info(f"Extracted general keywords from URL: {search_terms}")
    
    # Remove common non-descriptive words
    common_words = ["www", "http", "https", "com", "free", "download", "image", "vector", "photo"]
    search_terms = [term for term in search_terms if term.lower() not in common_words]
    
    # Limit to top 5 most relevant terms to avoid over-specific searches
    if len(search_terms) > 5:
        search_terms = search_terms[:5]
    
    return search_terms

def download_resource(page, resource_url, user_id, download_dir, send_user_message, chat_id):
    """Download a resource from Freepik and return the file path."""
    logger.info(f"Downloading resource: {resource_url}")
    resource_file = ""
    
    # Create user directory for downloads
    user_download_dir = os.path.join(download_dir, f"user_{user_id}")
    os.makedirs(user_download_dir, exist_ok=True)
    
    try:
        # First navigate to the homepage
        logger.info("Navigating to Freepik homepage first...")
        page.goto("https://www.freepik.com/", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)
        logger.info("Successfully loaded Freepik homepage")
        
        # Now navigate to the resource URL
        logger.info(f"Navigating to resource: {resource_url}")
        page.goto(resource_url, timeout=60000)
        logger.info(f"Navigation complete. Current URL: {page.url}")
        page.wait_for_load_state("networkidle", timeout=60000)
        
        # Check for Access Denied error
        if page.locator("text=Access Denied").is_visible(timeout=3000) or "Access Denied" in page.title():
            logger.error(f"Access Denied for URL: {resource_url}")
            
            # Try refreshing the page (sometimes resolves access denied)
            logger.info("Access denied detected. Trying to refresh the page...")
            page.reload(timeout=60000)
            page.wait_for_load_state("networkidle", timeout=60000)
            
            # Wait longer after refresh
            time.sleep(5)
            
            # Check if refresh solved the issue
            if page.locator("text=Access Denied").is_visible(timeout=3000) or "Access Denied" in page.title():
                logger.info("Still access denied after refresh. Trying alternate methods...")
                
                # Try a different approach - go back to homepage and then search
                page.goto("https://www.freepik.com/", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
                time.sleep(3)
            
                # Try extracting search terms from the URL
                if "query=" in resource_url:
                    query_param = resource_url.split("query=")[1].split("&")[0]
                    search_terms = query_param.replace("+", " ").split()
                    logger.info(f"Extracted search terms from URL query: {search_terms}")
                else:
                    # Use enhanced search term extraction
                    search_terms = extract_search_terms_from_url(resource_url)
                
                # If we have search terms, try searching for the resource
                if search_terms:
                    try:
                        # Try to find and use the search box
                        search_selectors = [
                            "input[type='search']", 
                            "input[placeholder*='search' i]",
                            "input[name='search']",
                            "input[id*='search' i]",
                            "input[class*='search' i]",
                            ".search-input",
                            "#search-box",
                            "form[role='search'] input"
                        ]
                        
                        search_box = None
                        for selector in search_selectors:
                            try:
                                potential_box = page.locator(selector).first
                                if potential_box.is_visible(timeout=2000):
                                    search_box = potential_box
                                    logger.info(f"Found search box using selector: {selector}")
                                    break
                            except:
                                continue
                                
                        if search_box:
                            # Fill and submit search with the extracted terms
                            search_query = " ".join(search_terms)
                            logger.info(f"Searching for: {search_query}")
                            
                            # First try the normal approach
                            search_box.fill(search_query)
                            time.sleep(1)
                            search_box.press("Enter")
                            
                            # Wait for search results
                            page.wait_for_load_state("networkidle", timeout=30000)
                            
                            # If the above doesn't work, try to find and click a search button
                            if "search" not in page.url.lower():
                                logger.info("Search Enter key didn't work, trying to find search button...")
                                search_button_selectors = [
                                    "button[type='submit']",
                                    "button.search-button",
                                    "button[aria-label*='search' i]",
                                    "button svg[path*='search']",
                                    ".search-submit",
                                    "form[role='search'] button"
                                ]
                                
                                for btn_selector in search_button_selectors:
                                    try:
                                        btn = page.locator(btn_selector).first
                                        if btn.is_visible(timeout=2000):
                                            btn.click(timeout=5000)
                                            page.wait_for_load_state("networkidle", timeout=30000)
                                            logger.info(f"Clicked search button with selector: {btn_selector}")
                                            break
                                    except:
                                        continue
                            
                            # Check if we successfully searched
                            if "search" in page.url.lower() or "query" in page.url.lower():
                                logger.info("Successfully performed search. Current URL: " + page.url)
                                
                                # Try to find the first result that might match what we're looking for
                                result_links = page.locator("a[href*='freepik.com']").all()
                                for link in result_links:
                                    try:
                                        href = link.get_attribute("href")
                                        # Skip navigation links or non-resource links
                                        if not href or "vector" not in href and "photo" not in href and "premium" not in href:
                                            continue
                                            
                                        link_text = link.inner_text()
                                        logger.info(f"Found search result: {link_text} - {href}")
                                        
                                        # Send message to user about the issue and our attempt to find an alternative
                                        send_user_message(chat_id, 
                                            "⚠️ The direct link to this resource returned an 'Access Denied' error.\n\n"
                                            "I've searched for similar resources based on keywords from your link. "
                                            "Please try sending me a different URL from the search results for similar resources."
                                        )
                                        
                                        # Found at least one result, so break
                                        break
                                    except:
                                        continue
                            else:
                                logger.error("Search didn't work, no search results page detected.")
                        else:
                            logger.error("Search box not found on Freepik homepage")
                            
                            # Try a JavaScript approach as last resort
                            try:
                                logger.info("Trying direct JavaScript search as last resort...")
                                page.evaluate(f"""() => {{
                                    // Try to find any search input
                                    const inputs = Array.from(document.querySelectorAll('input'));
                                    const searchInput = inputs.find(i => 
                                        i.type === 'search' || 
                                        i.placeholder?.toLowerCase().includes('search') ||
                                        i.name?.toLowerCase().includes('search') ||
                                        i.id?.toLowerCase().includes('search')
                                    );
                                    
                                    if (searchInput) {{
                                        searchInput.value = "{' '.join(search_terms)}";
                                        searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        
                                        // Create and dispatch an enter key event
                                        const enterEvent = new KeyboardEvent('keydown', {{
                                            key: 'Enter',
                                            code: 'Enter',
                                            keyCode: 13,
                                            which: 13,
                                            bubbles: true
                                        }});
                                        searchInput.dispatchEvent(enterEvent);
                                        
                                        // Also try to find and click a search button
                                        setTimeout(() => {{
                                            const buttons = Array.from(document.querySelectorAll('button'));
                                            const searchButton = buttons.find(b => 
                                                b.textContent?.toLowerCase().includes('search') ||
                                                b.getAttribute('aria-label')?.toLowerCase().includes('search')
                                            );
                                            if (searchButton) searchButton.click();
                                        }}, 500);
                                    }}
                                }}""")
                                
                                # Wait for navigation
                                page.wait_for_load_state("networkidle", timeout=30000)
                                
                                # Check if this worked
                                if "search" in page.url.lower() or "query" in page.url.lower():
                                    logger.info("JavaScript search was successful!")
                                    
                                    # Send to user
                                    send_user_message(chat_id, 
                                        "⚠️ The direct link to this resource returned an 'Access Denied' error.\n\n"
                                        "I've searched for similar resources based on keywords from your link. "
                                        "Please try sending me a different URL for a similar resource."
                                    )
                                else:
                                    logger.error("JavaScript search approach also failed.")
                            except Exception as js_error:
                                logger.error(f"JavaScript search error: {js_error}")
                    except Exception as search_error:
                        logger.error(f"Error during search attempt: {search_error}")
                
                # Check if we can extract the specific error message
                error_message = "You don't have permission to access this resource."
                try:
                    error_text = page.locator("p:has-text('You don't have permission')").text_content()
                    if error_text:
                        error_message = error_text
                except:
                    pass
                
                # If we didn't try to search already, send the access denied message
                if not search_terms:
                    send_user_message(chat_id, 
                        f"❌ Access Denied: {error_message}\n\n"
                        "This might happen if:\n"
                        "- The resource requires a higher-tier premium account\n"
                        "- The resource has geographic restrictions\n"
                        "- The URL is incorrect or the resource was removed\n\n"
                        "Please try with a different resource URL."
                    )
                
                return "", False  # Failed to download
        
        logger.info("Successfully loaded resource page")
        
        # Handle any cookie consent banners
        handle_cookie_consent(page)
        
        # Try to find and click the download button
        download_button = None
        found_download_button = False
        
        # Method 1: Look for the download button in the main content area
        try:
            # This is the most common pattern for modern Freepik pages
            download_btn = page.locator("a[data-cy='download-button'], button:has-text('Download')").first
            if download_btn.is_visible(timeout=5000):
                download_button = download_btn
                found_download_button = True
                logger.info("Found main download button")
        except Exception as e:
            logger.error(f"Method 1 for finding download button failed: {e}")
        
        # Method 2: Check for any element with download in its attributes
        if not found_download_button:
            try:
                selectors = [
                    "a:has-text('Download')", 
                    "a[href*='download']",
                    "button:has-text('Download')",
                    "[data-testid*='download']",
                    "[aria-label*='download' i]",
                    "[data-tooltip*='download' i]"
                ]
                
                for selector in selectors:
                    download_btn = page.locator(selector).first
                    if download_btn.is_visible(timeout=2000):
                        download_button = download_btn
                        found_download_button = True
                        logger.info(f"Found download button using selector: {selector}")
                        break
            except Exception as e:
                logger.error(f"Method 2 for finding download button failed: {e}")
        
        # Method 3: Try to find the download button in a table or grid view
        if not found_download_button:
            try:
                # If we're on a search results or downloads page, try to find download buttons in rows
                download_btns = page.locator("tr button:has-text('Download'), div[role='row'] button:has-text('Download')").all()
                if download_btns and len(download_btns) > 0:
                    download_button = download_btns[0]
                    found_download_button = True
                    logger.info("Found download button in table/grid row")
            except Exception as e:
                logger.error(f"Method 3 for finding download button failed: {e}")
        
        # Method 4: Last resort - try to find ANY element that might be a download button
        if not found_download_button:
            try:
                # Look for SVG icons typically used for download
                icon_btn = page.locator("button svg[path*='download'], a svg[path*='download']").first
                if icon_btn:
                    # Try to click the parent element (button containing the SVG)
                    parent = icon_btn.locator("xpath=..")
                    if parent.is_visible(timeout=2000):
                        download_button = parent
                        found_download_button = True
                        logger.info("Found download button via SVG icon")
            except Exception as e:
                logger.error(f"Method 4 for finding download button failed: {e}")
        
        if not found_download_button:
            logger.error("Could not find any download button")
            
            # Send informative message to user
            send_user_message(chat_id, "❌ Could not find a download button for this resource. This might happen if:\n\n1. The resource requires a higher-tier premium account\n2. The resource is not available for download\n3. The website layout has changed")
            
            return "", False  # Failed to download
        
        # Click the download button
        try:
            logger.info("Attempting to click download button")
            download_button.click(timeout=10000)
            logger.info("Clicked download button successfully")
            
            # Wait a moment for dropdown or download to start
            time.sleep(2)
        except Exception as e:
            logger.error(f"Error clicking download button: {e}")
            send_user_message(chat_id, "❌ Found the download button but couldn't click it. Please try again later.")
            return "", False  # Failed to download
        
        # Check for dropdown menu or direct download
        try:
            download_info = None
            download_option_found = False
            dropdown_visible = False
            
            # First check if a dropdown menu appeared
            menu_options = page.locator("[role='menuitem'], .dropdown-menu a, .menu a").all()
            
            if len(menu_options) > 0:
                dropdown_visible = True
                logger.info(f"Found dropdown menu with {len(menu_options)} options")
                
                # Look for zip download option first
                for option in menu_options:
                    try:
                        option_text = option.inner_text()
                        if "zip" in option_text.lower() or "download zip" in option_text.lower():
                            with page.expect_download(timeout=60000) as download_info:
                                option.click(timeout=10000)
                                logger.info(f"Clicked '{option_text}' option")
                                download_option_found = True
                                break
                    except:
                        continue
                
                # If no zip option, try any download option
                if not download_option_found:
                    for option in menu_options:
                        try:
                            option_text = option.inner_text()
                            if "download" in option_text.lower():
                                with page.expect_download(timeout=60000) as download_info:
                                    option.click(timeout=10000)
                                    logger.info(f"Clicked '{option_text}' option")
                                    download_option_found = True
                                    break
                        except:
                            continue
            
            # If no dropdown or no option selected, check if download started directly
            if not dropdown_visible or not download_option_found:
                try:
                    # The initial button click might have already started the download
                    logger.info("No dropdown menu or no option selected, checking if download started directly...")
                    download_info = page.wait_for_download(timeout=5000)
                    download_option_found = True
                except Exception as e:
                    logger.error(f"No direct download detected: {e}")
            
            # If still no download, try to click the main button again
            if not download_option_found and download_button:
                try:
                    logger.info("Trying to click the main download button again...")
                    with page.expect_download(timeout=60000) as download_info:
                        download_button.click(force=True, timeout=10000)
                        download_option_found = True
                except Exception as e:
                    logger.error(f"Failed to click main button again: {e}")
            
            # If download still not started, try one more approach with direct JS click
            if not download_option_found and download_button:
                try:
                    logger.info("Trying JavaScript click as last resort...")
                    download_button.evaluate("el => el.click()")
                    download_info = page.wait_for_download(timeout=5000)
                    download_option_found = True
                except Exception as e:
                    logger.error(f"JavaScript click failed: {e}")
            
            if not download_option_found:
                logger.error("Could not find or click any download option")
                
                send_user_message(chat_id, "❌ Found the download button but couldn't initiate the download. The resource might not be available with the current account.")
                return "", False  # Failed to download
            
            # Process the downloaded file
            download = download_info.value
            original_filename = download.suggested_filename
            
            # Add timestamp and user ID to filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename_parts = os.path.splitext(original_filename)
            unique_filename = f"{filename_parts[0]}_{user_id}_{timestamp}{filename_parts[1]}"
            
            resource_file = os.path.join(user_download_dir, unique_filename)
            download.save_as(resource_file)
            
            logger.info(f"Resource downloaded: {unique_filename}")
            return resource_file, True  # Successfully downloaded
            
        except Exception as e:
            logger.error(f"Error during download process: {e}")
            send_user_message(chat_id, f"❌ Error downloading: {str(e)[:100]}")
            return "", False  # Failed to download
            
    except Exception as e:
        logger.error(f"Error accessing resource: {e}")
        send_user_message(chat_id, f"❌ Error loading resource page: {str(e)[:100]}")
        return "", False  # Failed to download

def download_license(page, resource_file_path, user_id, download_dir):
    """
    Download the license file from Freepik and return the local file path.
    
    Args:
        page: The Playwright page object
        resource_file_path: The path to the resource file that was downloaded
        user_id: Telegram user ID for filename identification
        download_dir: Base download directory
    
    Returns:
        str: Path to the downloaded license file, or empty string if download failed
    """
    logger.info("Downloading license file from Freepik...")
    
    # Create unique subdirectory for this user
    user_download_dir = os.path.join(download_dir, f"user_{user_id}")
    os.makedirs(user_download_dir, exist_ok=True)
    
    # Extract the file name from the resource path
    resource_file_name = os.path.basename(resource_file_path)
    file_name_without_ext = os.path.splitext(resource_file_name)[0]
    
    logger.info(f"Looking for license for file: {resource_file_name}")
    
    try:
        # Go to downloads page
        page.goto("https://www.freepik.com/user/downloads?page=1&type=regular", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        
        # Extract file links from the downloads page
        file_rows = page.locator("tr").all()
        logger.info(f"Found {len(file_rows)} rows in the downloads table")
        
        # Method 1: Try to find the exact file by name in the table
        license_found = False
        for i, row in enumerate(file_rows):
            try:
                row_html = row.evaluate("el => el.innerHTML")
                
                # Check if this row contains our file name
                if file_name_without_ext.lower() in row_html.lower():
                    logger.info(f"Found matching file in row {i+1}")
                    
                    # Find and click the license button in this row
                    license_button = row.locator("button:has-text('Download license')").first
                    if license_button.is_visible(timeout=5000):
                        with page.expect_download(timeout=30000) as download_info:
                            license_button.click(timeout=10000)
                            logger.info("Clicked license button for matching file")
                        
                        # Process the download
                        download = download_info.value
                        original_filename = download.suggested_filename
                        
                        # Add timestamp and user ID to filename
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename_parts = os.path.splitext(original_filename)
                        unique_filename = f"{filename_parts[0]}_{user_id}_{timestamp}{filename_parts[1]}"
                        
                        license_path = os.path.join(user_download_dir, unique_filename)
                        download.save_as(license_path)
                        logger.info(f"License file downloaded: {unique_filename}")
                        license_found = True
                        return license_path
                    else:
                        logger.error("License button not visible for matching file")
            except Exception as e:
                logger.error(f"Error processing row {i+1}: {e}")
        
        # Method 2: Try to match based on file URL
        if not license_found:
            logger.info("Trying to match file based on URL pattern...")
            
            # Get the file ID or distinctive part from the downloaded file name
            # Typically files are named based on their URL/ID
            file_parts = file_name_without_ext.split('-')
            
            # Try with different parts of the file name to find a match
            for row in file_rows:
                try:
                    row_html = row.evaluate("el => el.innerHTML")
                    
                    # Check for matching URL parts in HTML
                    match_found = False
                    for part in file_parts:
                        if len(part) > 3 and part in row_html:  # Skip very short parts
                            match_found = True
                            break
                    
                    if match_found:
                        logger.info(f"Found possible match using URL pattern")
                        
                        # Find and click the license button in this row
                        license_buttons = row.locator("button").all()
                        for button in license_buttons:
                            try:
                                button_html = button.evaluate("el => el.innerHTML")
                                if "license" in button_html.lower():
                                    with page.expect_download(timeout=30000) as download_info:
                                        button.click(timeout=10000)
                                        logger.info("Clicked license button for matching URL pattern")
                                    
                                    # Process the download
                                    download = download_info.value
                                    original_filename = download.suggested_filename
                                    
                                    # Add timestamp and user ID to filename
                                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                                    filename_parts = os.path.splitext(original_filename)
                                    unique_filename = f"{filename_parts[0]}_{user_id}_{timestamp}{filename_parts[1]}"
                                    
                                    license_path = os.path.join(user_download_dir, unique_filename)
                                    download.save_as(license_path)
                                    logger.info(f"License file downloaded: {unique_filename}")
                                    license_found = True
                                    return license_path
                            except Exception as e:
                                logger.error(f"Error clicking license button: {e}")
                except Exception as e:
                    continue  # Try next row
        
        # Method 3: If still not found, try with the first row (most recent download)
        if not license_found:
            logger.info("Trying with most recent download...")
            try:
                # Click the first license button in the first row
                with page.expect_download(timeout=30000) as download_info:
                    # Try to specifically target the license button based on its SVG icon and text
                    first_row = page.locator("tr").first
                    # This selector looks for a button with "Download license" text
                    license_button = first_row.locator("button").filter(has_text=re.compile("Download license", re.IGNORECASE)).first
                    license_button.click(timeout=10000)
                    logger.info("Clicked license button for most recent download")
                
                download = download_info.value
                original_filename = download.suggested_filename
                
                # Add timestamp and user ID to filename
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename_parts = os.path.splitext(original_filename)
                unique_filename = f"{filename_parts[0]}_{user_id}_{timestamp}{filename_parts[1]}"
                
                license_path = os.path.join(user_download_dir, unique_filename)
                download.save_as(license_path)
                logger.info(f"License file downloaded: {unique_filename}")
                return license_path
            except Exception as e:
                logger.error(f"Error downloading license from most recent download: {e}")
                
                # Try a final approach by simply finding any license button on the page
                try:
                    license_btn_selector = "button:has-text('Download license'), button:has-text('License')"
                    with page.expect_download(timeout=30000) as download_info:
                        page.locator(license_btn_selector).first.click(timeout=10000)
                        logger.info("Clicked first available license button on the page")
                    
                    download = download_info.value
                    original_filename = download.suggested_filename
                    
                    # Add timestamp and user ID to filename
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename_parts = os.path.splitext(original_filename)
                    unique_filename = f"{filename_parts[0]}_{user_id}_{timestamp}{filename_parts[1]}"
                    
                    license_path = os.path.join(user_download_dir, unique_filename)
                    download.save_as(license_path)
                    logger.info(f"License file downloaded using alternative method: {unique_filename}")
                    return license_path
                except Exception as e2:
                    logger.error(f"Failed to download license using all methods: {e2}")
                    return ""
    except Exception as e:
        logger.error(f"Error navigating to downloads page: {e}")
        return ""

def cleanup_files(file_paths):
    """Remove temporary files from the local system."""
    for file_path in file_paths:
        if not file_path or not os.path.exists(file_path):
            continue
            
        try:
            os.remove(file_path)
            logger.info(f"Deleted temporary file: {os.path.basename(file_path)}")
        except OSError as e:
            logger.error(f"Could not delete {os.path.basename(file_path)}: {e}")