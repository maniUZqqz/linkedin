import sys
import json
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# اگر با خطای encoding در ویندوز مواجه شدید، این دو خط رو فعال کنید:
# sys.stdout.reconfigure(encoding='utf-8')
# sys.stdin.reconfigure(encoding='utf-8')

BASE_URL = 'http://127.0.0.1:8000/'

def manual_linkedin_login_and_save_cookies():
    """
    1) Opens a visible Chrome window to LinkedIn login
    2) You log in manually in that window
    3) After you're logged in, press Enter in this terminal
    4) Saves all cookies to linkedin_cookies.json
    """
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    # must be visible:
    # options.add_argument('--headless')  # DO NOT enable
    driver = webdriver.Chrome(service=service, options=options)

    driver.get("https://www.linkedin.com/login")
    input("Once you have logged in to LinkedIn in the browser, press Enter here to continue...")

    cookies = driver.get_cookies()
    with open("linkedin_cookies.json", "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    print(f"Saved {len(cookies)} cookies to linkedin_cookies.json")
    driver.quit()

def load_cookies_to_session(session: requests.Session):
    """
    Loads cookies from linkedin_cookies.json into the requests.Session.
    """
    try:
        with open("linkedin_cookies.json", encoding="utf-8") as f:
            cookies = json.load(f)
    except FileNotFoundError:
        raise RuntimeError("linkedin_cookies.json not found. Run manual login first.")

    for ck in cookies:
        session.cookies.set(ck['name'], ck['value'], domain=ck.get('domain'))
    print("Loaded cookies into the session.")

def send_username(username: str):
    """
    Sends only the username to the backend (no email/password in payload).
    """
    session = requests.Session()
    load_cookies_to_session(session)

    resp = session.post(BASE_URL, json={'username': username})
    resp.raise_for_status()
    print('POST / →', resp.status_code, resp.json())
    return session

def fetch_analysis(session: requests.Session):
    """
    Calls GET /show/ to trigger the crawler and fetch the analysis.
    """
    resp = session.get(f"{BASE_URL}show/")
    if resp.status_code != 200:
        print(f"\nSERVER ERROR {resp.status_code}:\n{resp.text}")
        resp.raise_for_status()
    print('GET /show/ →', resp.status_code)
    return resp.json()

def main():
    username = input("Enter the LinkedIn username (e.g. 'saadatiparsa7'): ").strip()
    if not username:
        print("Username cannot be empty.")
        return

    # check if cookies file exists and non-empty
    need_login = True
    try:
        with open("linkedin_cookies.json", encoding="utf-8") as f:
            if json.load(f):
                need_login = False
    except Exception:
        need_login = True

    if need_login:
        print("=== MANUAL LOGIN REQUIRED ===")
        manual_linkedin_login_and_save_cookies()

    # send username to backend
    session = send_username(username)

    # give backend a moment
    time.sleep(1)

    # fetch analysis
    try:
        result = fetch_analysis(session)
    except requests.HTTPError:
        print("Backend returned 500—check server logs for details.")
        return

    # display
    print('\n=== Analysis Result ===')
    for k, v in result.get('analysis', {}).items():
        print(f"- {k}: {v}")

    if urls := result.get('urls'):
        print('\n=== Crawled URLs ===')
        for u in urls:
            print(f"- {u}")

if __name__ == '__main__':
    main()
