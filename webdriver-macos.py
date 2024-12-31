import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time
import os
import re
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

# Expanded patterns for different formats of nutritional information
NUTRITION_PATTERNS = {
    'calories': [
        r'\d+\s*(?:calories|cals?|kcals?|cal\b)',
        r'(?:calories|cals?|kcals?|cal\b)[\s:]+\d+',
        r'energy[\s:]+\d+\s*(?:kcal|cal)',
        r'energy\s*\(kcal\)[\s:]+\d+'
    ],
    'protein': [
        r'\d+(?:\.\d+)?\s*(?:g\s+protein|g\s+prot|protein|prot)(?:\s*g)?',
        r'(?:protein|prot)[\s:]+\d+(?:\.\d+)?\s*g?',
        r'protein\s*content[\s:]+\d+(?:\.\d+)?\s*g?'
    ],
    'carbs': [
        r'\d+(?:\.\d+)?\s*(?:g\s+carbs?|carbs?|carbohydrates?|total\s+carbs?)(?:\s*g)?',
        r'(?:carbs?|carbohydrates?|total\s+carbs?)[\s:]+\d+(?:\.\d+)?\s*g?',
        r'total\s+carbohydrate[\s:]+\d+(?:\.\d+)?\s*g?'
    ],
    'fat': [
        r'\d+(?:\.\d+)?\s*(?:g\s+fat|fats?|total\s+fat)(?:\s*g)?',
        r'(?:fats?|total\s+fat)[\s:]+\d+(?:\.\d+)?\s*g?',
        r'total\s+fat\s+content[\s:]+\d+(?:\.\d+)?\s*g?'
    ],
    'serving_size': [
        r'serving\s+size[\s:]+[^,\n]+',
        r'per\s+serving[\s:]+[^,\n]+',
        r'portion\s+size[\s:]+[^,\n]+'
    ]
}


def wait_for_content(driver, timeout=20):
    """Wait for content to load on the page"""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.find_element(By.TAG_NAME, "body").text.strip()) > 0
        )
        # Wait for dynamic content and potential popups
        time.sleep(5)
        return True
    except TimeoutException:
        print(f"Timeout waiting for content after {timeout} seconds")
        return False


def setup_driver():
    try:
        print("Setting up Chrome driver...")
        chrome_options = uc.ChromeOptions()
        chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--disable-popup-blocking')
        # Add macOS-specific options
        # Helps prevent some crashes on macOS
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')

        driver = uc.Chrome(options=chrome_options)
        print("Chrome driver setup successful!")
        return driver
    except Exception as e:
        print(f"Error setting up Chrome driver: {str(e)}")
        raise


def extract_number(text, patterns):
    """Extract the first number found in text that matches any of the patterns"""
    if not text:
        return None
    text = text.lower()
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Find the first number in the matched text
            number = re.search(r'\d+(?:\.\d+)?', match.group())
            if number:
                return number.group()
    return None


def extract_serving_size(text, patterns):
    """Extract serving size information"""
    if not text:
        return None
    text = text.lower()
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Return the full match without the label
            serving_info = match.group()
            # Remove the label part
            serving_info = re.sub(
                r'^(serving size|per serving|portion size)[\s:]+', '', serving_info, flags=re.IGNORECASE)
            return serving_info.strip()
    return None


def find_product_name(lines, current_index, window_size=5):
    """Find the most likely product name by looking at surrounding lines"""
    potential_names = []

    # Look at previous lines
    start_idx = max(0, current_index - window_size)
    for line in lines[start_idx:current_index]:
        line = line.strip()
        if line and len(line) > 3 and not any(char.isdigit() for char in line):
            potential_names.append(line)

    # If no names found in previous lines, look at following lines
    if not potential_names and current_index + 1 < len(lines):
        end_idx = min(len(lines), current_index + window_size)
        for line in lines[current_index + 1:end_idx]:
            line = line.strip()
            if line and len(line) > 3 and not any(char.isdigit() for char in line):
                potential_names.append(line)

    return potential_names[-1] if potential_names else None


def load_existing_data():
    """Load existing data from CSV if it exists"""
    try:
        if os.path.exists('nutritional_info.csv'):
            df = pd.read_csv('nutritional_info.csv')
            return {row['name']: row.to_dict() for _, row in df.iterrows()}
        return {}
    except Exception as e:
        print(f"Error loading existing data: {str(e)}")
        return {}


def save_to_csv(products_data):
    """Save the current data to CSV"""
    try:
        df = pd.DataFrame(list(products_data.values()))
        df.to_csv('nutritional_info.csv', index=False)
        print(
            f"Data saved successfully! Total unique products: {len(products_data)}")
    except Exception as e:
        print(f"Error saving data: {str(e)}")


def process_page_content(driver, products_data, current_url):
    """Process the content of the current page"""
    try:
        # First try to find nutrition tables or specific nutrition sections
        nutrition_elements = driver.find_elements(By.XPATH,
                                                  "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'nutrition') or "
                                                  "contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'nutritional')]")

        page_text = driver.find_element(By.TAG_NAME, "body").text
        lines = page_text.split('\n')
        current_product = None
        products_found_on_page = 0

        # Process each line
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            # Extract nutritional information
            calories = extract_number(line, NUTRITION_PATTERNS['calories'])
            protein = extract_number(line, NUTRITION_PATTERNS['protein'])
            carbs = extract_number(line, NUTRITION_PATTERNS['carbs'])
            fat = extract_number(line, NUTRITION_PATTERNS['fat'])
            serving_size = extract_serving_size(
                line, NUTRITION_PATTERNS['serving_size'])

            # If we found any nutritional info
            if any([calories, protein, carbs, fat, serving_size]):
                if not current_product:
                    current_product = find_product_name(lines, i)

                if current_product:
                    # Create a nutritional values string for comparison
                    current_values = f"cal{calories or 'NA'}_p{protein or 'NA'}_c{carbs or 'NA'}_f{fat or 'NA'}"
                    base_name = current_product

                    # Check if this product name exists with different nutritional values
                    if base_name in products_data:
                        existing_data = products_data[base_name]
                        existing_values = f"cal{existing_data.get('calories', 'NA')}_p{existing_data.get('protein', 'NA')}_c{existing_data.get('carbs', 'NA')}_f{existing_data.get('fat', 'NA')}"

                        if existing_values != current_values:
                            # Find a unique name by adding a suffix
                            suffix = 1
                            while f"{base_name} (Variant {suffix})" in products_data:
                                variant_data = products_data[f"{base_name} (Variant {suffix})"]
                                variant_values = f"cal{variant_data.get('calories', 'NA')}_p{variant_data.get('protein', 'NA')}_c{variant_data.get('carbs', 'NA')}_f{variant_data.get('fat', 'NA')}"

                                if variant_values == current_values:
                                    # Found matching variant, use this name
                                    current_product = f"{base_name} (Variant {suffix})"
                                    break
                                suffix += 1
                            else:
                                # No matching variant found, create new one
                                current_product = f"{base_name} (Variant {suffix})"

                    # Update or create product entry
                    products_data[current_product] = {
                        'name': current_product,
                        'calories': calories or 'N/A',
                        'protein': protein or 'N/A',
                        'carbs': carbs or 'N/A',
                        'fat': fat or 'N/A',
                        'serving_size': serving_size or 'N/A',
                        'last_updated': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'source_url': current_url
                    }
                    products_found_on_page += 1
                    print(f"\nFound/Updated product: {current_product}")
                    print(
                        f"Values - Calories: {calories}, Protein: {protein}, Carbs: {carbs}, Fat: {fat}")
                    print(f"Serving Size: {serving_size}")
            else:
                # Reset product context if we've moved past nutritional information
                current_product = None

        if products_found_on_page > 0:
            print(f"\nFound {products_found_on_page} products on this page")
            save_to_csv(products_data)
        else:
            print("\nNo nutritional information found on this page")

        return products_found_on_page
    except Exception as e:
        print(f"Error processing page: {str(e)}")
        return 0


def continuous_scraping():
    """Continuously monitor and scrape data from pages as they are visited"""
    driver = None
    products_data = load_existing_data()
    last_url = None

    try:
        driver = setup_driver()
        print("\nStarting continuous monitoring...")
        print("Navigate to any page in the browser, and I'll automatically scrape nutritional information.")
        print("Press Ctrl+C to stop the script.")

        while True:
            try:
                current_url = driver.current_url

                # Only process if we've navigated to a new URL
                if current_url != last_url:
                    print(f"\nNew page detected: {current_url}")
                    if wait_for_content(driver):
                        process_page_content(
                            driver, products_data, current_url)
                    last_url = current_url

                time.sleep(2)  # Check for new URLs every 2 seconds

            except Exception as e:
                print(f"Error during monitoring: {str(e)}")
                time.sleep(2)  # Wait before retrying

    except KeyboardInterrupt:
        print("\nStopping the scraper...")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        if driver:
            print("Saving page source for debugging...")
            with open('error_page.html', 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    print("Starting the continuous scraping process...")
    continuous_scraping()
