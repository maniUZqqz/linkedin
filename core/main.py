import asyncio
import json
import logging
import random
import time
from queue import Queue
from abc import ABC, abstractmethod
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import NoSuchElementException
import pyodbc
import datetime
import requests
import json
import pyodbc
import queue


# لاگین کردن تو لینکدین
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

database_project = "Driver={ODBC Driver 17 for SQL Server};Server=.;Database=LinkedInDB;UID=sa;PWD=mani1386;"


# ======================================================================
# مرحله ۱: تعریف کلاس پایه ExtractionStrategy و ۷ کلاس استخراج مورد نظر
# ======================================================================


# مدیریت اسکرول صفحه وب
class ScrollManager:
    def __init__(self, driver, max_retries=3, scroll_pause=1.5, timeout=30):
        self.driver = driver
        self.max_retries = max_retries
        self.scroll_pause = scroll_pause
        self.timeout = timeout
        self.last_height = 0

    def _scroll_step(self):
        """انجام یک مرحله اسکرول و بازگرداندن وضعیت تغییر ارتفاع"""
        new_height = self.driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);"
            "return document.body.scrollHeight;"
        )
        return new_height != self.last_height, new_height

    def _wait_for_content_load(self):
        """انتظار برای بارگذاری محتوا بعد از اسکرول"""
        try:
            WebDriverWait(self.driver, self.scroll_pause).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".feed-shared-update-v2"))
            )
        except TimeoutException:
            logging.warning("هیچ محتوای جدیدی پس از اسکرول یافت نشد")

    def smart_scroll(self, scroll_limit=None):
        """
        اسکرول هوشمند تا انتهای صفحه یا رسیدن به محدوده مشخص
        Args:
            scroll_limit (int): حداکثر تعداد اسکرول (None برای نامحدود)
        Returns:
            int: تعداد دفعات اسکرول انجام شده
        """
        scroll_count = 0
        retries = 0

        while True:
            if scroll_limit and scroll_count >= scroll_limit:
                break

            try:
                changed, new_height = self._scroll_step()
                if not changed:
                    retries += 1
                    if retries >= self.max_retries:
                        break
                    logging.info(f"تلاش مجدد اسکرول ({retries}/{self.max_retries})")
                    time.sleep(self.scroll_pause * 2)
                    continue

                self.last_height = new_height
                scroll_count += 1
                retries = 0

                logging.debug(f"اسکرول #{scroll_count} انجام شد. ارتفاع جدید: {new_height}")
                self._wait_for_content_load()
                time.sleep(self.scroll_pause)
            except Exception as e:
                logging.error(f"خطا در حین اسکرول: {str(e)}")
                break

        logging.info(f"اسکرول کامل شد. تعداد اسکرول‌ها: {scroll_count}")
        return scroll_count

    def scroll_to_element(self, element):
        """اسکرول به المان خاص با انیمیشن نرم"""
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                element
            )
            return True
        except Exception as e:
            logging.error(f"خطا در اسکرول به المان: {str(e)}")
            return False


# وظیفه: تحلیل داده‌های استخراج شده از LinkedIn.
class LinkedInAnalyzer:
    API_KEY = "tpsg-xuC2QiWGfKsZWcnTRhjLLtGRXPPias9"
    BASE_URL = "https://api.metisai.ir/openai/v1"
    CONNECTION_STRING = database_project

    # سیستم پرامپت اختصاصی برای هر بخش
    SECTION_SYSTEM_PROMPTS = {
        "profile": "You are an expert in analyzing LinkedIn profile data. Analyze the following profile information and provide improvement suggestions.",
        "activity": "You are an expert in analyzing LinkedIn activity data. Please analyze the activity details and provide at least 5 practical suggestions.",
        "education": "You are an expert in analyzing the education section of a LinkedIn profile. Provide constructive feedback and improvement ideas.",
        "skills": "You are an expert in analyzing LinkedIn skills. Review the provided skills data and suggest enhancements.",
        "publications": "You are an expert in analyzing publications. Analyze the publication details and offer improvement recommendations.",
        "honors": "You are an expert in analyzing honors and awards. Review the provided data and suggest ways to improve the presentation.",
        "languages": "You are an expert in analyzing language proficiency data. Analyze the language section and provide suggestions.",
        "projects": "You are an expert in analyzing project information on LinkedIn. Please review the project details and suggest improvements.",
        "volunteering": "You are an expert in analyzing volunteering experience. Analyze the volunteering data and provide actionable suggestions.",
        "certifications": "You are an expert in analyzing certification data. Please review the certifications and suggest enhancements.",
        "courses": "You are an expert in analyzing courses data. Analyze the course details and provide improvement recommendations.",
        "experience": "You are an expert in analyzing professional experience data. Please analyze the experience section and suggest improvements.",
        "organizations": "You are an expert in analyzing organizational affiliations. Review the provided data and offer suggestions for improvement."
    }

    def __init__(self, target):
        self.target = target
        self.data = None

    def get_linkedin_data(self):
        """
        استخراج داده‌های لینکدین از SQL Server برای تارگت مشخص.
        انتظار می‌رود جدول LinkedInUserData دارای ستون‌های زیر باشد:
          - ProfileData, ActivityData, EducationData, SkillsData, PublicationsData,
            HonorsData, LanguagesData, ProjectsData, VolunteeringData, CertificationsData,
            CoursesData, ExperienceData, OrganizationsData, CreatedAt, UpdatedAt
        """
        conn = None
        try:
            conn = pyodbc.connect(self.CONNECTION_STRING)
            cursor = conn.cursor()
            query = """
            SELECT 
                ProfileData, ActivityData, EducationData, SkillsData, PublicationsData,
                HonorsData, LanguagesData, ProjectsData, VolunteeringData, CertificationsData,
                CoursesData, ExperienceData, OrganizationsData, CreatedAt, UpdatedAt
            FROM LinkedInUserData
            WHERE Target = ?
            """
            cursor.execute(query, (self.target,))
            row = cursor.fetchone()
            if row:
                self.data = {}
                self.data['profile'] = json.loads(row.ProfileData) if row.ProfileData else {}
                self.data['activity'] = json.loads(row.ActivityData) if row.ActivityData else []
                self.data['education'] = json.loads(row.EducationData) if row.EducationData else []
                self.data['skills'] = json.loads(row.SkillsData) if row.SkillsData else []
                self.data['publications'] = json.loads(row.PublicationsData) if row.PublicationsData else []
                self.data['honors'] = json.loads(row.HonorsData) if row.HonorsData else []
                self.data['languages'] = json.loads(row.LanguagesData) if row.LanguagesData else []
                self.data['projects'] = json.loads(row.ProjectsData) if row.ProjectsData else {}
                self.data['volunteering'] = json.loads(row.VolunteeringData) if row.VolunteeringData else {}
                self.data['certifications'] = json.loads(row.CertificationsData) if row.CertificationsData else {}
                self.data['courses'] = json.loads(row.CoursesData) if row.CoursesData else []
                self.data['experience'] = json.loads(row.ExperienceData) if row.ExperienceData else []
                self.data['organizations'] = json.loads(row.OrganizationsData) if row.OrganizationsData else []
                self.data['created_at'] = str(row.CreatedAt)
                self.data['updated_at'] = str(row.UpdatedAt)
                return self.data
            else:
                raise RuntimeError("هیچ داده‌ای برای تارگت مورد نظر یافت نشد.")
        except Exception as e:
            raise RuntimeError(f"خطا در دریافت داده از SQL Server: {str(e)}")
        finally:
            if conn:
                conn.close()

    def build_full_prompt(self):
        """
        ساخت یک prompt جامع برای تحلیل کامل پروفایل.
        """
        if self.data is None:
            raise RuntimeError("داده‌ها هنوز استخراج نشده‌اند.")
        prompt = f"""
🔍 داده‌های تحلیل لینکدین:

▫️ پروفایل:
{json.dumps(self.data.get('profile', {}), indent=2, ensure_ascii=False)}

▫️ فعالیت‌ها:
{json.dumps(self.data.get('activity', []), indent=2, ensure_ascii=False)}

▫️ تحصیلات:
{json.dumps(self.data.get('education', []), indent=2, ensure_ascii=False)}

▫️ مهارت‌ها:
{json.dumps(self.data.get('skills', []), indent=2, ensure_ascii=False)}

▫️ انتشارات:
{json.dumps(self.data.get('publications', []), indent=2, ensure_ascii=False)}

▫️ افتخارات:
{json.dumps(self.data.get('honors', []), indent=2, ensure_ascii=False)}

▫️ زبان‌ها:
{json.dumps(self.data.get('languages', []), indent=2, ensure_ascii=False)}

▫️ پروژه‌ها:
{json.dumps(self.data.get('projects', {}), indent=2, ensure_ascii=False)}

▫️ فعالیت‌های داوطلبانه:
{json.dumps(self.data.get('volunteering', {}), indent=2, ensure_ascii=False)}

▫️ گواهینامه‌ها:
{json.dumps(self.data.get('certifications', {}), indent=2, ensure_ascii=False)}

▫️ دوره‌ها:
{json.dumps(self.data.get('courses', []), indent=2, ensure_ascii=False)}

▫️ تجربیات شغلی:
{json.dumps(self.data.get('experience', []), indent=2, ensure_ascii=False)}

▫️ سازمان‌ها:
{json.dumps(self.data.get('organizations', []), indent=2, ensure_ascii=False)}

Created At: {self.data.get('created_at')}
Updated At: {self.data.get('updated_at')}
"""
        return prompt

    def send_api_request(self, payload):
        """
        ارسال درخواست به API متیس و دریافت پاسخ.
        """
        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        response = requests.post(f"{self.BASE_URL}/chat/completions", json=payload, headers=headers)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"خطای API: {response.status_code} - {response.text}"

    def analyze_full(self):
        """
        تحلیل کامل پروفایل به صورت یکباره.
        """
        if self.data is None:
            self.get_linkedin_data()
        full_prompt = self.build_full_prompt()
        analysis_prompt = f"""
روبیکمپی عزیز من، لطفا این پروفایل لینکدین رو تحلیل کن و حداقل 5 پیشنهاد بهبود بدی:

{full_prompt}

معیارهای تحلیل:
1. بهینه‌سازی کلمات کلیدی (Keyword Optimization)
2. ساختار حرفه‌ای (Professional Structure)
3. جذابیت برای استخدام (Recruitment Appeal)
4. رعایت استانداردهای لینکدین (LinkedIn Standards)
5. نکات فنی و ظاهری (Technical Aspects)
"""
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": (
                    "You are 'Rubikamp', an intelligent assistant who communicates in Persian. "
                    "Always address the user warmly, provide 5-10 practical solutions, and explain technical terms in both English and Persian."
                )},
                {"role": "user", "content": analysis_prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.5
        }
        return self.send_api_request(payload)

    def analyze_section(self, section_name, content):
        """
        تحلیل یک بخش به صورت جداگانه با استفاده از سیستم پرامپت اختصاصی.
        """
        system_prompt = self.SECTION_SYSTEM_PROMPTS.get(
            section_name,
            "Please analyze the following data and provide improvement suggestions."
        )
        user_prompt = f"""
روبیکمپی عزیز من، لطفا بخش {section_name} لینکدین را تحلیل کن و حداقل 5 پیشنهاد بهبود ارائه بده:

{json.dumps(content, indent=2, ensure_ascii=False)}
"""
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.5
        }
        return self.send_api_request(payload)

    def analyze_sections_individually(self):
        """
        تحلیل هر بخش به صورت جداگانه: داده‌ها از SQL استخراج شده و هر بخش در یک صف قرار می‌گیرد.
        سپس هر تسک به صورت جداگانه به API متیس ارسال می‌شود.
        """
        if self.data is None:
            self.get_linkedin_data()
        results = {}
        task_queue = queue.Queue()
        for section in self.SECTION_SYSTEM_PROMPTS.keys():
            content = self.data.get(section)
            if content not in (None, {}, []):
                task_queue.put((section, content))
        while not task_queue.empty():
            section, content = task_queue.get()
            response = self.analyze_section(section, content)
            results[section] = response
            task_queue.task_done()
        return results



# حذف داده های تکراری
class DuplicateRemover:
    @staticmethod
    def remove_duplicates(records: list, unique_key: str) -> list:
        """
        از روی یک لیست از دیکشنری‌ها، رکوردهایی که مقدار تکراری برای کلید unique_key دارند را حذف می‌کند.

        Args:
            records (list): لیست دیکشنری‌ها.
            unique_key (str): کلیدی که باید یکتا باشد (مثلاً "organization_name").

        Returns:
            list: لیستی از رکوردهای بدون تکرار.
        """
        seen = set()
        deduped_records = []
        for record in records:
            # دریافت مقدار کلید، حذف فضاهای اضافی و تبدیل به حروف کوچک برای مقایسه یکسان
            key_value = record.get(unique_key, "").strip().lower()
            # اگر مقدار کلید وجود داشته باشد و قبلاً دیده نشده باشد
            if key_value and key_value not in seen:
                seen.add(key_value)
                deduped_records.append(record)
        return deduped_records



class ExtractionStrategy(ABC):
    @abstractmethod
    def extract(self, driver):
        pass

    @abstractmethod
    def get_identifier(self):
        pass




class ProfileExtraction(ExtractionStrategy):
    def extract(self, driver):
        try:
            wait = WebDriverWait(driver, 15)
            # صبر تا زمانی که بخش پروفایل (top card) لود شود
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".ph5.pb5")))

            # استخراج عکس پروفایل
            profile_picture = ""
            try:
                profile_pic_elem = driver.find_element(
                    By.CSS_SELECTOR,
                    "div.pv-top-card__non-self-photo-wrapper button img"
                )
                profile_picture = profile_pic_elem.get_attribute("src")
            except Exception as e:
                logging.debug("عکس پروفایل یافت نشد: %s", e)

            # استخراج نام
            name = ""
            try:
                name_elem = driver.find_element(
                    By.CSS_SELECTOR,
                    "h1.uQioaVkRgsfWDoBSLjlSfqboaPcwugUOAnAo"
                )
                name = name_elem.text.strip()
            except Exception as e:
                logging.debug("نام یافت نشد: %s", e)

            # استخراج توضیحات اولیه (tagline)
            tagline = ""
            try:
                tagline_elem = driver.find_element(
                    By.CSS_SELECTOR,
                    "div.text-body-medium.break-words"
                )
                tagline = tagline_elem.text.strip()
            except Exception as e:
                logging.debug("توضیحات اولیه یافت نشد: %s", e)

            # استخراج اطلاعات شرکت فعلی (نام و لوگو)
            current_company = ""
            company_logo = ""
            try:
                # یافتن دکمه مربوط به شرکت فعلی از داخل ul با کلاس مشخص
                company_button = driver.find_element(
                    By.CSS_SELECTOR,
                    "ul.erRWcxhwyYllLRgdZRauLQBzZMdDNmhPoE li button"
                )
                # استخراج لوگوی شرکت
                try:
                    company_logo_elem = company_button.find_element(By.CSS_SELECTOR, "img")
                    company_logo = company_logo_elem.get_attribute("src")
                except Exception as e:
                    logging.debug("لوگوی شرکت یافت نشد: %s", e)
                # استخراج نام شرکت از متن داخل span (داخل یک div)
                try:
                    company_name_elem = company_button.find_element(
                        By.CSS_SELECTOR,
                        "span.BsvdPyOtOKNGGVYYQqtUElKbZGPnfpcuzcOc div"
                    )
                    current_company = company_name_elem.text.strip()
                except Exception as e:
                    logging.debug("نام شرکت فعلی یافت نشد: %s", e)
            except Exception as e:
                logging.debug("اطلاعات شرکت فعلی یافت نشد: %s", e)

            # استخراج موقعیت جغرافیایی (location)
            location = ""
            try:
                location_elem = driver.find_element(
                    By.CSS_SELECTOR,
                    "div.IOuUwFmttqBhtvZnhWkJNpdEtSloAmSnVqMA.mt2 span.text-body-small.inline.t-black--light.break-words"
                )
                location = location_elem.text.strip()
            except Exception as e:
                logging.debug("موقعیت جغرافیایی یافت نشد: %s", e)

            # استخراج تعداد ارتباطات
            connections = ""
            try:
                connections_elem = driver.find_element(
                    By.CSS_SELECTOR,
                    "ul.CRNhzCZvlJndiJjJyEOFuGmFrPhKyyjecU.NDxUENCcMFlOuVWFBEYHGASScFfhIJtKZbCg li span.t-bold"
                )
                connections = connections_elem.text.strip()
            except Exception as e:
                logging.debug("تعداد ارتباطات یافت نشد: %s", e)

            # ---------- بخش اضافه شده برای استخراج قسمت "about" ----------
            # اسکرول کردن صفحه تا قسمتی که درباره وجود دارد به نمایش درآید
            time.sleep(1)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(1)

            # بررسی وجود دکمه «…see more» و کلیک روی آن در صورت وجود
            try:
                more_button = driver.find_element(
                    By.CSS_SELECTOR,
                    "button.inline-show-more-text__button.inline-show-more-text__button--light.link"
                )
                # اگر دکمه موجود بود و هنوز باز نشده (aria-expanded برابر false است)
                if more_button and more_button.get_attribute("aria-expanded") == "false":
                    driver.execute_script("arguments[0].click();", more_button)
                    time.sleep(1)
            except Exception as e:
                logging.debug("دکمه 'see more' پیدا نشد یا قابل کلیک نبود: %s", e)

            # استخراج متن قسمت درباره (about)
            about = ""
            try:
                about_elem = driver.find_element(
                    By.CSS_SELECTOR,
                    "div.display-flex.ph5.pv3"
                )
                about = about_elem.text.strip()
            except Exception as e:
                logging.debug("متن درباره (about) یافت نشد: %s", e)
            # ----------------------------------------------------------------

            return {
                "profile_picture": profile_picture,
                "name": name,
                "tagline": tagline,
                "current_company": current_company,
                "company_logo": company_logo,
                "location": location,
                "connections": connections,
                "about": about
            }
        except Exception as e:
            logging.error(f"خطا در استخراج پروفایل: {str(e)}")
            return None

    def get_identifier(self):
        return "profile"

class ActivityExtraction(ExtractionStrategy):
    def get_identifier(self):
        return "activity"

    def __init__(self):
        self.scroll_manager = None

    def extract(self, driver):
        try:
            self.scroll_manager = ScrollManager(driver)
            self._scroll_to_load_posts()
            posts_data = self._process_posts(driver)
            return posts_data
        except Exception as e:
            logging.critical(f"خطای بحرانی در استخراج فعالیت‌ها: {e}", exc_info=True)
            return None
        finally:
            self.scroll_manager = None

    def _scroll_to_load_posts(self):
        """
        اسکرول صفحه تا زمانی که به انتها برسیم.
        فرض می‌شود متد smart_scroll در ScrollManager این منطق را مدیریت می‌کند.
        """
        logging.info("شروع فرآیند اسکرول برای بارگذاری پست‌ها")
        scroll_count = self.scroll_manager.smart_scroll()
        logging.info(f"تعداد دفعات اسکرول انجام شده: {scroll_count}")

    def _process_posts(self, driver):
        """
        یافتن تمامی پست‌های موجود در فید و پردازش هر کدام به صورت جداگانه.
        """
        try:
            post_elements = WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "div.feed-shared-update-v2:not(.comments-comment-item)")
                )
            )
        except Exception as e:
            logging.error(f"خطا در یافتن پست‌ها: {e}")
            return {"posts": [], "count": 0}

        posts = []
        for idx, post in enumerate(post_elements, 1):
            posts.append(self._extract_post_data(post, idx))
        return posts

    def _extract_post_data(self, post, index):
        """
        استخراج اطلاعات یک پست شامل عنوان، محتوا، تاریخ، تعاملات و مدیا.
        قبل از استخراج، صفحه به پست مورد نظر اسکرول می‌کند.
        """
        self.scroll_manager.scroll_to_element(post)
        return {
            "post_number": index,
            "title": self._extract_title(post),
            "content": self._extract_content(post),
            "date": self._extract_date(post),
            "engagement": self._extract_engagement(post),
            "media": self._extract_media(post)
        }

    def _safe_extract_text(self, element, by, selector, default=""):
        """
        تلاش برای استخراج متن از عنصری مشخص؛ در صورت بروز خطا، مقدار پیش‌فرض بازگردانده می‌شود.
        """
        try:
            return element.find_element(by, selector).text.strip()
        except Exception as e:
            logging.debug(f"خطا در استخراج متن با selector '{selector}': {e}")
            return default

    def _click_more_button(self, post):
        """
        در صورت وجود دکمه «نمایش بیشتر»، روی آن کلیک می‌کند تا متن کامل نمایش داده شود.
        """
        try:
            more_button = post.find_element(By.CSS_SELECTOR, 'button[aria-label="نمایش بیشتر"]')
            self.scroll_manager.driver.execute_script("arguments[0].click();", more_button)
            time.sleep(0.5)
        except Exception as e:
            logging.debug(f"دکمه 'نمایش بیشتر' یافت نشد یا قابل کلیک نبود: {e}")

    def _extract_title(self, post):
        return self._safe_extract_text(
            post, By.CSS_SELECTOR, 'span.update-components-text__break-words > strong'
        )

    def _extract_content(self, post):
        self._click_more_button(post)
        return self._safe_extract_text(
            post, By.CSS_SELECTOR, 'div.feed-shared-inline-show-more-text'
        )

    def _extract_date(self, post):
        return self._safe_extract_text(
            post, By.CSS_SELECTOR, 'span.update-components-actor__sub-description > span:not(.visually-hidden)'
        )

    def _extract_engagement(self, post):
        """
        استخراج تعاملات پست شامل لایک‌ها، کامنت‌ها و ریپست‌ها.
        """
        return {
            "likes": self._get_likes_count(post),
            "comments": self._get_comments_count(post),
            "reposts": self._get_reposts_count(post)
        }

    def _get_likes_count(self, post):
        """
        استخراج تعداد لایک‌ها از HTML ارائه شده:
        <li class="social-details-social-counts__item ...">
            <button ... aria-label="39 reactions" ...>
                ...
                <span class="social-details-social-counts__reactions-count">39</span>
            </button>
        </li>
        """
        try:
            element = post.find_element(
                By.XPATH,
                ".//li[contains(@class, 'social-details-social-counts__reactions')]//span[contains(@class, 'social-details-social-counts__reactions-count')]"
            )
            text = element.text.strip()
            num_text = text.replace(',', '')
            return int(num_text) if num_text.isdigit() else 0
        except Exception as e:
            logging.debug(f"خطا در استخراج لایک‌ها: {e}")
            return 0

    def _get_comments_count(self, post):
        """
        استخراج تعداد کامنت‌ها از HTML ارائه شده:
        <li class="social-details-social-counts__item social-details-social-counts__comments ...">
            <button aria-label="2 comments" ...>
                <span>2 comments</span>
            </button>
        </li>
        """
        try:
            element = post.find_element(
                By.XPATH,
                ".//li[contains(@class, 'social-details-social-counts__comments')]//button//span"
            )
            text = element.text.strip()  # مثلاً "2 comments"
            count_str = text.split()[0]
            num_text = count_str.replace(',', '')
            return int(num_text) if num_text.isdigit() else 0
        except Exception as e:
            logging.debug(f"خطا در استخراج کامنت‌ها: {e}")
            return 0

    def _get_reposts_count(self, post):
        """
        استخراج تعداد ریپست‌ها از HTML ارائه شده:
        <li class="social-details-social-counts__item ...">
            <button aria-label="2 reposts" ...>
                <span>2 reposts</span>
            </button>
        </li>
        """
        try:
            element = post.find_element(
                By.XPATH,
                ".//button[contains(@aria-label, 'reposts')]//span"
            )
            text = element.text.strip()  # مثلاً "2 reposts"
            count_str = text.split()[0]
            num_text = count_str.replace(',', '')
            return int(num_text) if num_text.isdigit() else 0
        except Exception as e:
            logging.debug(f"خطا در استخراج ریپست‌ها: {e}")
            return 0

    def _extract_media(self, post):
        """
        استخراج تمامی موارد مدیا (ویدئو، تصویر، سند) موجود در پست.
        """
        media = []
        media_selectors = [
            'div.feed-shared-linkedin-video',
            'img.feed-shared-image__image',
            'div.feed-shared-document__container'
        ]
        for selector in media_selectors:
            try:
                items = post.find_elements(By.CSS_SELECTOR, selector)
                for item in items:
                    media.append(self._process_media_item(item))
            except Exception as e:
                logging.debug(f"خطا در استخراج مدیا با selector '{selector}': {e}")
        return media

    def _process_media_item(self, item):
        """
        پردازش یک مورد مدیا و استخراج اطلاعات آن شامل نوع، URL و متن جایگزین (alt text).
        """
        media_type = self._detect_media_type(item)
        url = item.get_attribute("src") or item.get_attribute("href") or ""
        alt_text = (item.get_attribute("alt") or "")[:100]
        return {"type": media_type, "url": url, "alt_text": alt_text}

    def _detect_media_type(self, element):
        """
        تشخیص نوع مدیا بر اساس کلاس‌های موجود در عنصر.
        """
        class_list = element.get_attribute("class") or ""
        if "feed-shared-linkedin-video" in class_list:
            return "video"
        if "feed-shared-image__image" in class_list:
            return "image"
        if "feed-shared-document__container" in class_list:
            return "document"
        return "unknown"

class EducationExtraction(ExtractionStrategy):
    def extract(self, driver):
        try:
            # انتظار برای بارگذاری المان‌های بخش تحصیلات
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-view-name='profile-component-entity']"))
            )

            education_items = driver.find_elements(By.CSS_SELECTOR, "div[data-view-name='profile-component-entity']")
            results = []

            for item in education_items:
                try:
                    # استخراج «مقطع تحصیلی»:
                    # المانی که فقط شامل کلاس‌های t-14 و t-normal باشد (بدون t-black--light)
                    degree_element = item.find_element(
                        By.XPATH,
                        ".//span[contains(@class, 't-14') and contains(@class, 't-normal') and not(contains(@class, 't-black--light'))]"
                    )
                    degree = degree_element.text.strip()
                except Exception:
                    degree = ""

                try:
                    # استخراج «زمان»:
                    # المانی که شامل کلاس‌های t-14، t-normal و t-black--light است
                    date_element = item.find_element(
                        By.XPATH,
                        ".//span[contains(@class, 't-14') and contains(@class, 't-normal') and contains(@class, 't-black--light')]"
                    )
                    date = date_element.text.strip()
                except Exception:
                    date = ""

                results.append({
                    "degree": degree,
                    "date": date
                })

            return results

        except Exception as e:
            logging.error(f"خطا در استخراج تحصیلات: {str(e)}")
            return None

    def count_items(self, driver):
        """
        این تابع ابتدا اطلاعات تحصیلی را استخراج می‌کند و سپس تعداد آن‌ها را برمی‌گرداند.
        """
        results = self.extract(driver)
        return len(results) if results is not None else 0
    def get_identifier(self):
        return "education"

class SkillsExtraction(ExtractionStrategy):
    def get_identifier(self):
        return "skills"

    def extract(self, driver):
        # مرحله ۱: اسکرول کامل صفحه
        try:
            self._scroll_page(driver)
        except Exception as e:
            logging.error(f"خطا در اسکرول صفحه: {str(e)}", exc_info=True)
            return None

        # مرحله ۲: استخراج عناصر مهارت
        try:
            skill_elements = self._extract_skill_elements(driver)
        except Exception as e:
            logging.error(f"خطا در استخراج عناصر مهارت: {str(e)}", exc_info=True)
            return None

        # مرحله ۳: پردازش نهایی مهارت‌ها
        try:
            skills = self._process_skills(skill_elements)
        except Exception as e:
            logging.error(f"خطا در پردازش مهارت‌ها: {str(e)}", exc_info=True)
            return None

        # نمایش تعداد مهارت‌های استخراج شده
        logging.info(f"تعداد مهارت‌های استخراج شده: {len(skills)}")
        return skills

    def _scroll_page(self, driver):
        """
        اسکرول کامل صفحه تا زمانی که دیگر محتوای جدیدی لود نشود.
        """
        # انتظار برای لود شدن عنصر body صفحه
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))

        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0

        while True:
            # اسکرول به پایین صفحه
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # تاخیر جهت لود شدن محتوای جدید

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts += 1
                if scroll_attempts >= 3:  # در صورت ۳ بار تلاش ناموفق، توقف می‌کنیم
                    break
            else:
                scroll_attempts = 0
                last_height = new_height

    def _extract_skill_elements(self, driver):
        """
        استخراج عناصر مربوط به مهارت‌ها بر اساس CSS Selector های مشخص.
        """
        css_selector = (
            ".pv-skill-category-entity__name-text, "
            "[data-field='skill_page_skill_topic'] .t-bold, "
            ".skill-category-entity__name"
        )
        return WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, css_selector))
        )

    def _process_skills(self, skill_elements):
        """
        پردازش عناصر استخراج شده برای ساخت یک لیست یکتا از مهارت‌ها.
        """
        unique_skills = set()
        for element in skill_elements:
            skill_text = element.text.strip()
            if skill_text:
                unique_skills.add(skill_text)
        return list(unique_skills)

class PublicationsExtraction(ExtractionStrategy):
    def get_identifier(self):
        # یک شناسه منحصر به فرد برای این استراتژی استخراج برگردانید
        return "publications"

    def extract(self, driver):
        try:
            # انتظار برای لود شدن بخش انتشارات با XPath اصلاح شده
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//section[contains(*,"Publications")]'))
            )

            # استفاده از ScrollManager برای اسکرول هوشمند
            scroll_manager = ScrollManager(driver)
            scroll_manager.smart_scroll()

            publications_data = []

            # پیدا کردن آیتم‌های انتشار
            publications = driver.find_elements(
                By.XPATH,
                '//section[contains(*,"Publications")]//div[contains(@class, "pvs-list__container")]//li'
            )

            for pub in publications:
                try:
                    # استخراج عنوان اصلی
                    title = pub.find_element(
                        By.XPATH,
                        './/div[contains(@class, "t-bold")]//span[contains(@aria-hidden, "true")]'
                    ).text.strip()

                    # استخراج جزئیات (مانند مجله و تاریخ)
                    details = pub.find_element(
                        By.XPATH,
                        './/span[contains(@class, "t-normal")]//span[contains(@aria-hidden, "true")]'
                    ).text.strip()

                    publications_data.append({
                        "title": title,
                        "details": details
                    })
                except Exception as e:
                    logging.error(f"خطا در استخراج آیتم: {str(e)}")

            logging.info(f"تعداد کل انتشارات: {len(publications_data)}")
            return publications_data

        except Exception as e:
            logging.error(f"خطا در استخراج انتشارات: {str(e)}")
            return None

class HonorsExtraction(ExtractionStrategy):
    def get_identifier(self):
        return "honors"

    def extract(self, driver):
        try:
            honors_container = WebDriverWait(driver, 15).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div[data-view-name="profile-component-entity"]'))
            )
            logging.info(f"تعداد کانتینرهای اصلی یافت شده: {len(honors_container)}")
        except Exception as e:
            logging.error(f"خطا در یافتن کانتینرهای اصلی: {str(e)}", exc_info=True)
            return None

        results = []

        for container in honors_container:
            try:
                # استخراج عنوان اصلی
                title = self._extract_with_fallback(
                    container,
                    [
                        'div.mr1.t-bold span[aria-hidden="true"]',
                        'div.t-bold span[aria-hidden="true"]:first-child'
                    ],
                    "عنوان"
                )

                # استخراج تاریخ و سازمان
                date_org = self._extract_with_fallback(
                    container,
                    [
                        'span.t-14.t-normal span[aria-hidden="true"]',
                        'div.t-14.t-normal:has(> span) span[aria-hidden="true"]'
                    ],
                    "تاریخ/سازمان"
                )

                # تفکیک تاریخ و سازمان
                date, organization = self._split_date_org(date_org)

                # استخراج توضیحات
                description = self._extract_with_fallback(
                    container,
                    [
                        'div.pvs-entity__sub-components span[aria-hidden="true"]:not(.visually-hidden)',
                        'div.ZrKmYbhRDKWCwyJWVTSwOKEpalqlqVLKjOM span[aria-hidden="true"]'
                    ],
                    "توضیحات"
                )

                # استخراج سازمان از طریق لوگو
                if not organization:
                    organization = self._extract_org_from_logo(container)

                if title:
                    results.append({
                        "title": title,
                        "date": date,
                        "organization": organization,
                        "description": description
                    })

            except Exception as e:
                logging.error(f"خطا در پردازش کانتینر: {str(e)}", exc_info=True)
                continue

        return results

    def _extract_with_fallback(self, parent, selectors, field_name):
        for selector in selectors:
            try:
                element = parent.find_element(By.CSS_SELECTOR, selector)
                text = element.text.strip()
                if text:
                    return text
            except Exception as e:
                continue
            except Exception as e:
                logging.error(f"خطا در استخراج {field_name}: {str(e)}")
        return ""

    def _split_date_org(self, text):
        try:
            if "·" in text:
                parts = [p.strip() for p in text.split("·")]
                return (parts[0], parts[1]) if len(parts) > 1 else (parts[0], "")
            return (text, "")
        except Exception:
            return ("", "")

    def _extract_org_from_logo(self, container):
        try:
            org_element = container.find_element(
                By.CSS_SELECTOR,
                'li.ivm-entity-pile__img-item--stacked + div span[aria-hidden="true"]'
            )
            return org_element.text.strip()
        except Exception:
            return ""

class LanguagesExtraction(ExtractionStrategy):
    def get_identifier(self):
        return "languages"

    def extract(self, driver):
        try:
            language_containers = self._wait_for_language_containers(driver)
        except Exception as e:
            logging.error(f"خطا در یافتن بخش زبان‌ها: {str(e)}", exc_info=True)
            return None

        try:
            languages = self._process_language_containers(language_containers)
        except Exception as e:
            logging.error(f"خطا در پردازش زبان‌ها: {str(e)}", exc_info=True)
            return None

        logging.info(f"تعداد زبان‌های استخراج شده: {len(languages)}")
        return languages

    def _wait_for_language_containers(self, driver):
        return WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div[data-view-name="profile-component-entity"]'))
        )

    def _process_language_containers(self, containers):
        results = []
        for container in containers:
            # استفاده از سلکتور دقیقتر برای نام زبان
            try:
                language_element = container.find_element(
                    By.CSS_SELECTOR,
                    "div.display-flex.align-items-center.mr1.t-bold span[aria-hidden='true']"
                )
                language = language_element.text.strip()
            except Exception as e:
                # اگر المنت مورد نظر یافت نشد، این container مربوط به زبان نیست
                continue
            except Exception as e :
                logging.error(f"خطا در استخراج نام زبان: {str(e)}", exc_info=True)
                language = ""

            # استخراج سطح زبان
            try:
                level_element = container.find_element(
                    By.CSS_SELECTOR,
                    "span.pvs-entity__caption-wrapper[aria-hidden='true']"
                )
                level = level_element.text.strip()
            except Exception as e:
                level = ""

            if language:

                results.append({"language": language, "level": level})

        return results

class ProjectsExtraction(ExtractionStrategy):
    def extract(self, driver):
        projects_data = []

        # پیدا کردن تمامی المان‌هایی که مربوط به پروژه هستند.
        project_components = driver.find_elements(By.XPATH, "//div[@data-view-name='profile-component-entity']")

        # اگر هیچ المانی پیدا نشد، یک لیست خالی برگردانیم.
        if not project_components:
            return {"projects_data": projects_data}

        # حلقه برای پردازش هر پروژه
        for project_component in project_components:
            # استخراج عنوان پروژه (مثلاً "Mr. Musa Movie")
            try:
                title_element = project_component.find_element(By.CSS_SELECTOR, "div.t-bold span[aria-hidden='true']")
                project_title = title_element.text.strip()
            except Exception:
                project_title = ""

            # استخراج بازه زمانی پروژه (مثلاً "Oct 2023 - Present")
            try:
                timeline_element = project_component.find_element(By.CSS_SELECTOR,
                                                                  "span.t-14.t-normal span[aria-hidden='true']")
                project_timeline = timeline_element.text.strip()
            except Exception:
                project_timeline = ""

            # استخراج توضیحات پروژه
            try:
                description_element = project_component.find_element(By.CSS_SELECTOR,
                                                                     "div.t-14.t-normal.t-black span[aria-hidden='true']")
                project_description = description_element.text.strip()
            except Exception:
                project_description = ""

            projects_data.append({
                "title": project_title,
                "timeline": project_timeline,
                "description": project_description,
            })

        return projects_data

    def get_identifier(self):
        return "projects"

class VolunteeringExtraction(ExtractionStrategy):
    def extract(self, driver):
        volunteering_data = []

        # ایجاد یک شی WebDriverWait به مدت 10 ثانیه
        wait = WebDriverWait(driver, 10)

        try:
            # صبر می‌کنیم تا اولین المان فعالیت ولنتری ظاهر شود.
            wait.until(EC.presence_of_element_located((By.XPATH, "//div[@data-view-name='profile-component-entity']")))
        except Exception as e:
            print("Timeout waiting for volunteering components:", e)
            return volunteering_data

        # یافتن تمامی المان‌های مربوط به فعالیت‌های ولنتری
        volunteering_components = driver.find_elements(By.XPATH, "//div[@data-view-name='profile-component-entity']")

        for vol in volunteering_components:
            # استخراج نقش/عنوان فعالیت (Role)
            try:
                role_element = vol.find_element(By.CSS_SELECTOR, "div.t-bold span[aria-hidden='true']")
                role = role_element.text.strip()
            except Exception:
                role = ""

            # استخراج نام سازمان (Organization)
            try:
                organization_element = vol.find_element(By.CSS_SELECTOR, "span.t-14.t-normal:not(.t-black--light)")
                organization = organization_element.text.strip()
            except Exception:
                organization = ""

            # استخراج بازه زمانی (Timeline) و حوزه فعالیت (Cause)
            timeline = ""
            cause = ""
            try:
                # پیدا کردن تمام المان‌هایی که کلاس t-14 t-normal t-black--light را دارند
                black_light_spans = vol.find_elements(By.CSS_SELECTOR, "span.t-14.t-normal.t-black--light")
                if black_light_spans:
                    # اولین المان معمولاً شامل بازه زمانی است.
                    try:
                        timeline_element = black_light_spans[0].find_element(By.CSS_SELECTOR,
                                                                             "span.pvs-entity__caption-wrapper")
                        timeline = timeline_element.text.strip()
                    except Exception:
                        timeline = black_light_spans[0].text.strip()

                    # دومین المان اگر موجود باشد، حوزه یا دلیل فعالیت را نمایش می‌دهد.
                    if len(black_light_spans) > 1:
                        cause = black_light_spans[1].text.strip()
            except Exception:
                pass

            volunteering_data.append({
                "role": role,
                "organization": organization,
                "timeline": timeline,
                "cause": cause,
            })

        return {"volunteering_data": volunteering_data}

    def get_identifier(self):
        return "volunteering"

class CertificationsExtraction(ExtractionStrategy):
    def extract(self, driver):
        certifications_data = []

        # اطمینان از بارگذاری کامل صفحه
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # اسکرول به پایین صفحه جهت بارگذاری المان‌های lazy-loaded
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)  # وقفه برای بارگذاری المان‌های اضافه

        # انتظار تا زمانی که حداقل یک المان گواهینامه ظاهر شود
        wait = WebDriverWait(driver, 10)
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//div[@data-view-name='profile-component-entity']")
            ))
        except Exception as e:
            logging.error("Timeout waiting for certifications components: %s", e)
            return certifications_data

        # یافتن تمامی المان‌های گواهینامه
        cert_elements = driver.find_elements(By.XPATH, "//div[@data-view-name='profile-component-entity']")

        for cert in cert_elements:
            # بررسی اینکه آیا المان مربوط به More Profiles for you است یا خیر
            try:
                cert.find_element(By.XPATH, ".//a[@data-field='browsemap_card_click']")
                # در صورت وجود این تگ، بلوک مربوطه از پردازش حذف می‌شود
                continue
            except NoSuchElementException:
                pass

            # استخراج عنوان گواهینامه
            try:
                title_element = cert.find_element(By.CSS_SELECTOR, "div.t-bold span[aria-hidden='true']")
                cert_title = title_element.text.strip()
            except Exception:
                cert_title = ""

            # استخراج نام سازمان صادرکننده
            try:
                # در این نمونه، اولین المان با کلاس t-14 t-normal معمولاً نام سازمان است.
                org_element = cert.find_element(By.CSS_SELECTOR, "span.t-14.t-normal")
                issuing_org = org_element.text.strip()
            except Exception:
                issuing_org = ""

            # استخراج تاریخ صدور گواهینامه
            try:
                # تاریخ صدور در داخل span با کلاس t-14 t-normal t-black--light قرار دارد
                issued_date_element = cert.find_element(By.CSS_SELECTOR,
                                                        "span.t-14.t-normal.t-black--light span.pvs-entity__caption-wrapper")
                issued_date = issued_date_element.text.strip()
            except Exception:
                issued_date = ""

            # استخراج لوگوی گواهینامه
            try:
                logo_element = cert.find_element(By.CSS_SELECTOR, "div.ivm-view-attr__img-wrapper img")
                logo_url = logo_element.get_attribute("src")
            except Exception:
                logo_url = ""

            # افزودن اطلاعات گواهینامه در صورتی که عنوان موجود باشد
            if cert_title:
                certifications_data.append({
                    "title": cert_title,
                    "issuing_organization": issuing_org,
                    "issued_date": issued_date,
                    "logo_url": logo_url,
                })

        return {"certifications_data": certifications_data}

    def get_identifier(self):
        return "certifications"

class CoursesExtraction(ExtractionStrategy):
    def extract(self, driver):
        courses_data = []

        # صبر تا زمانی که صفحه کامل بارگذاری شود
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # اسکرول به پایین صفحه جهت بارگذاری المان‌های lazy-loaded
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)  # وقفه به مدت ۲ ثانیه برای اطمینان از بارگذاری محتوا

        # صبر برای ظاهر شدن حداقل یک المان دوره آموزشی
        wait = WebDriverWait(driver, 10)
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//div[@data-view-name='profile-component-entity']")
            ))
        except Exception as e:
            logging.error("Timeout waiting for courses components: %s", e)
            return {"courses_data": courses_data}

        # یافتن تمامی المان‌های دوره آموزشی (courses)
        course_elements = driver.find_elements(By.XPATH, "//div[@data-view-name='profile-component-entity']")

        for course in course_elements:
            # بررسی می‌کنیم که آیا المان مربوط به More Profiles for you است یا خیر
            try:
                course.find_element(By.XPATH, ".//a[@data-field='browsemap_card_click']")
                # اگر عنصر فوق یافت شد، این بلوک متعلق به بخش More Profiles for you است؛ پس از پردازش آن رد می‌شویم
                continue
            except NoSuchElementException:
                pass

            # استخراج عنوان دوره آموزشی
            try:
                title_element = course.find_element(By.CSS_SELECTOR, "div.t-bold span[aria-hidden='true']")
                course_title = title_element.text.strip()
            except Exception:
                course_title = ""

            # استخراج نام سازمان یا مرجع مرتبط (در صورت وجود)
            try:
                associated_org_element = course.find_element(
                    By.CSS_SELECTOR, "div.t-14.t-normal.t-black span[aria-hidden='true']"
                )
                associated_org = associated_org_element.text.strip()
            except Exception:
                associated_org = ""

            # استخراج لوگوی دوره (در صورت وجود)
            try:
                logo_element = course.find_element(By.CSS_SELECTOR, "div.ivm-view-attr__img-wrapper img")
                logo_url = logo_element.get_attribute("src")
            except Exception:
                logo_url = ""

            courses_data.append({
                "title": course_title,
                "associated_organization": associated_org,
                "logo_url": logo_url,
            })

        return courses_data

    def get_identifier(self):
        return "courses"

class ExperienceExtraction(ExtractionStrategy):
    def extract(self, driver):
        # اسکرول کردن تا پایان صفحه جهت بارگذاری محتوای lazy‑loaded
        self.scroll_to_end(driver)

        try:
            wait = WebDriverWait(driver, 10)
            # یافتن تمامی بلوک‌های اصلی تجربه که در آن‌ها والدینی با کلاس pvs-entity__sub-components وجود ندارد
            outer_experiences = wait.until(
                EC.presence_of_all_elements_located((
                    By.XPATH,
                    "//div[@data-view-name='profile-component-entity' and not(ancestor::div[contains(@class, 'pvs-entity__sub-components')])]"
                ))
            )
        except TimeoutException:
            logging.error("Timeout waiting for outer experience containers.")
            return {"experience_data": []}

        experiences = []
        for outer in outer_experiences:
            # در اینجا ابتدا چک می‌کنیم که آیا بلوک مربوط به «More Profiles for you» است یا خیر
            try:
                outer.find_element(By.XPATH, ".//a[@data-field='browsemap_card_click']")
                # اگر این تگ یافت شد، این بلوک مربوط به More Profiles بوده و از پردازش رد می‌شود
                continue
            except NoSuchElementException:
                pass

            # استخراج اطلاعات شرکت از بلوک اصلی
            company = ""
            try:
                company_elem = outer.find_element(
                    By.XPATH,
                    ".//div[contains(@class, 't-bold')]/span[@aria-hidden='true']"
                )
                company = company_elem.text.strip()
            except Exception as e:
                logging.debug("Company name not found: %s", e)

            company_duration = ""
            try:
                duration_elem = outer.find_element(
                    By.XPATH,
                    ".//span[contains(@class, 't-14 t-normal') and not(contains(@class, 't-black--light'))]//span[@aria-hidden='true']"
                )
                company_duration = duration_elem.text.strip()
            except Exception as e:
                logging.debug("Company duration not found: %s", e)

            location = ""
            try:
                loc_elem = outer.find_element(
                    By.XPATH,
                    ".//span[contains(@class, 't-14 t-normal t-black--light')]//span[@aria-hidden='true']"
                )
                location = loc_elem.text.strip()
            except Exception as e:
                logging.debug("Location not found: %s", e)

            # جستجوی موقعیت‌های شغلی (تودرتو) در بلوک اصلی
            nested_positions = []
            try:
                sub_components = outer.find_element(
                    By.XPATH,
                    ".//div[contains(@class, 'pvs-entity__sub-components')]"
                )
                position_items = sub_components.find_elements(
                    By.XPATH,
                    ".//li[contains(@class, 'pvs-list__paged-list-item')]"
                )
                for pos in position_items:
                    title = ""
                    pos_duration = ""
                    description = ""
                    try:
                        title_elem = pos.find_element(
                            By.XPATH,
                            ".//div[contains(@class, 't-bold')]/span[@aria-hidden='true']"
                        )
                        title = title_elem.text.strip()
                    except Exception as e:
                        logging.debug("Position title not found: %s", e)

                    try:
                        duration_elem = pos.find_element(
                            By.XPATH,
                            ".//span[contains(@class, 't-14 t-normal t-black--light')]//span[@aria-hidden='true']"
                        )
                        pos_duration = duration_elem.text.strip()
                    except Exception as e:
                        logging.debug("Position duration not found: %s", e)

                    try:
                        # توضیحات ممکن است در یک بخش با کلاس "t-14 t-normal t-black" موجود باشد
                        desc_elem = pos.find_element(
                            By.XPATH,
                            ".//div[contains(@class, 't-14 t-normal t-black')]//span[@aria-hidden='true']"
                        )
                        description = desc_elem.text.strip()
                    except Exception as e:
                        logging.debug("Position description not found: %s", e)

                    nested_positions.append({
                        "title": title,
                        "duration": pos_duration,
                        "description": description
                    })
            except Exception as e:
                logging.debug("No nested positions found: %s", e)

            # اگر موقعیت‌های شغلی تودرتو یافت شدند، برای هر کدام یک رکورد ایجاد می‌کنیم
            if nested_positions:
                for pos in nested_positions:
                    experiences.append({
                        "company": company,
                        "company_duration": company_duration,
                        "location": location,
                        "title": pos.get("title", ""),
                        "duration": pos.get("duration", ""),
                        "description": pos.get("description", "")
                    })
            else:
                # در صورت عدم وجود موقعیت‌های جداگانه، بلوک اصلی به عنوان یک تجربه ثبت می‌شود.
                experiences.append({
                    "company": company,
                    "company_duration": company_duration,
                    "location": location,
                    "title": company,  # در این حالت عنوان همان نام شرکت است
                    "duration": company_duration,
                    "description": ""
                })

        return experiences

    def get_identifier(self):
        return "experience"

    def scroll_to_end(self, driver, max_retries=3, scroll_pause=1.5):
        """
        اسکرول کردن صفحه تا پایان به منظور بارگذاری محتوای lazy‑loaded
        """
        last_height = driver.execute_script("return document.body.scrollHeight")
        retries = 0
        while retries < max_retries:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                retries += 1
            else:
                retries = 0
                last_height = new_height

class OrganizationsExtraction(ExtractionStrategy):
    def extract(self, driver):
        # اسکرول کردن تا پایان صفحه جهت بارگذاری محتوای lazy‑loaded
        self.scroll_to_end(driver)

        try:
            wait = WebDriverWait(driver, 10)
            # یافتن تمامی بلوک‌هایی که دارای data-view-name="profile-component-entity" هستند
            org_blocks = wait.until(
                EC.presence_of_all_elements_located(
                    (By.XPATH, "//div[@data-view-name='profile-component-entity']")
                )
            )
        except TimeoutException:
            logging.error("Timeout waiting for organizations components.")
            return {"organizations_data": []}

        organizations = []
        for org in org_blocks:
            # اگر بلوک حاوی تگ <a data-field="browsemap_card_click"> باشد، آن را رد می‌کنیم.
            try:
                org.find_element(By.XPATH, ".//a[@data-field='browsemap_card_click']")
                # در صورت یافتن عنصر فوق، این بلوک متعلق به بخش More Profiles است
                continue
            except NoSuchElementException:
                pass

            # استخراج نام سازمان از دایوی که حتماً کلاس‌های مورد نظر را داشته باشد
            org_name = ""
            try:
                name_elem = org.find_element(
                    By.XPATH, ".//div[contains(@class, 'display-flex') and contains(@class, 'align-items-center') and contains(@class, 'mr1') and contains(@class, 't-bold')]/span[@aria-hidden='true']"
                )
                org_name = name_elem.text.strip()
            except Exception as e:
                logging.debug("Organization name not found: %s", e)
                continue  # اگر نام سازمان یافت نشد، ادامه‌ی این بلوک پردازش نشود

            # استخراج نقش و بازه زمانی (role & date)
            role_date = ""
            try:
                role_date_elem = org.find_element(
                    By.XPATH, ".//span[contains(@class, 't-14 t-normal')]/span[@aria-hidden='true']"
                )
                role_date = role_date_elem.text.strip()
            except Exception as e:
                logging.debug("Role and date not found: %s", e)

            # استخراج اطلاعات زیر‌بخش (لوگو، association و توضیحات)
            logo_url = ""
            association = ""
            description = ""
            try:
                sub_components = org.find_element(
                    By.XPATH, ".//div[contains(@class, 'pvs-entity__sub-components')]"
                )
                # دریافت تمامی آیتم‌های موجود در زیر‌بخش
                li_items = sub_components.find_elements(By.XPATH, ".//li")
                for li in li_items:
                    li_text = li.text.strip()
                    # استخراج لوگو (در صورتی که آیتم شامل تگ img باشد)
                    try:
                        img = li.find_element(By.XPATH, ".//img")
                        logo_url = img.get_attribute("src")
                    except Exception:
                        pass
                    # بررسی متن آیتم: در صورت وجود "Associated with" آن را در association قرار می‌دهیم
                    if "Associated with" in li_text:
                        association = li_text
                    # در صورتی که متن با علامت "•" شروع شود، آن را به عنوان توضیحات در نظر می‌گیریم
                    if li_text.startswith("•"):
                        if description:
                            description += "\n" + li_text
                        else:
                            description = li_text
            except Exception as e:
                logging.debug("Sub-components not found for organization: %s", e)

            organizations.append({
                "organization_name": org_name,
                "role_date": role_date,
                "logo_url": logo_url,
                "association": association,
                "description": description
            })

        return organizations

    def get_identifier(self):
        return "organizations"

    def scroll_to_end(self, driver, max_retries=3, scroll_pause=1.5):
        """
        اسکرول کردن صفحه تا پایان به منظور بارگذاری محتوای lazy‑loaded
        """
        last_height = driver.execute_script("return document.body.scrollHeight")
        retries = 0
        while retries < max_retries:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                retries += 1
            else:
                retries = 0
                last_height = new_height


# ======================================================================
# مرحله ۲: تنظیم فکتوری استراتژی استخراج (با ۷ استراتژی مورد نظر)
# ======================================================================

class ExtractionStrategyFactory:
    @staticmethod
    def get_strategy(url):
        if "recent-activity" in url:
            return ActivityExtraction()
        elif "details/education" in url:
            return EducationExtraction()
        elif "details/skills" in url:
            return SkillsExtraction()
        elif "details/publications" in url:
            return PublicationsExtraction()
        elif "details/honors" in url:
            return HonorsExtraction()
        elif "details/languages" in url:
            return LanguagesExtraction()
        elif "details/projects" in url:
            return ProjectsExtraction()
        elif "details/volunteering-experiences" in url:
            return VolunteeringExtraction()
        elif "details/certifications" in url:
            return CertificationsExtraction()
        elif "details/courses" in url:
            return CoursesExtraction()
        elif "details/experience" in url:
            return ExperienceExtraction()
        elif "details/organizations" in url:
            return OrganizationsExtraction()
        elif "in/" in url:
            return ProfileExtraction()
        else:
            return ProfileExtraction()


# =============================================================================
# کلاس مدیریت تب‌ها (TabHandler)
# =============================================================================
class TabHandler:
    def __init__(self, driver, handle, url, extraction_strategy):
        self.driver = driver
        self.handle = handle
        self.url = url
        self.extraction_strategy = extraction_strategy

    def switch_to(self):
        self.driver.switch_to.window(self.handle)

    def extract_data(self):
        try:
            self.switch_to()
            logging.info(f"📊 استخراج داده از تب: {self.url}")
            data = {
                "url": self.url,
                "data": self.extraction_strategy.extract(self.driver),
                "strategy": self.extraction_strategy.get_identifier()
            }
            return data
        except Exception as e:
            logging.error(f"⚠️ خطا در استخراج از {self.url}: {str(e)}")
            return None
        finally:
            self._close_tab()

    def _close_tab(self):
        try:
            if self.handle in self.driver.window_handles:
                self.driver.switch_to.window(self.handle)
                self.driver.close()
        except Exception as e:
            logging.warning(f"خطا در بستن تب: {str(e)}")

# ---------------------------------------------------------------------
# کلاس LinkedinAutomation جهت مدیریت مرورگر، ورود، صف URLها و استخراج
# ---------------------------------------------------------------------
class LinkedinAutomation:
    def __init__(self, cookie_file="linkedin_cookies.json", headless=False):
        self.cookie_file = cookie_file
        self.headless = headless
        self.driver = None
        self.wait = None
        self.tab_queue = Queue()
        self.main_handle = None

    def configure_driver(self):
        try:
            options = uc.ChromeOptions()
            if self.headless:
                options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1280,720")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--mute-audio")
            options.add_argument("--disable-popup-blocking")
            options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
            )
            driver = uc.Chrome(options=options)
            driver.set_page_load_timeout(45)
            driver.set_script_timeout(30)
            logging.info("✅ مرورگر با موفقیت پیکربندی شد")
            return driver
        except Exception as e:
            logging.exception(f"خطا در راه‌اندازی مرورگر: {str(e)}")
            raise RuntimeError(f"خطا در راه‌اندازی مرورگر: {str(e)}")

    async def async_configure_driver(self):
        loop = asyncio.get_running_loop()
        self.driver = await loop.run_in_executor(None, self.configure_driver)
        self.wait = WebDriverWait(self.driver, 45 if self.headless else 25)
        self.main_handle = self.driver.current_window_handle

    def human_like_interaction(self, element=None):
        try:
            actions = ActionChains(self.driver)
            if element:
                actions.move_to_element(element).perform()
            else:
                x_offset = random.randint(-50, 50)
                y_offset = random.randint(-50, 50)
                actions.move_by_offset(x_offset, y_offset).perform()
            time.sleep(random.uniform(0.5, 3))
        except Exception as e:
            logging.warning(f"خطا در شبیه‌سازی رفتار: {str(e)}")

    def handle_cookies(self, action: str):
        try:
            if action == "load":
                self.driver.get("https://www.linkedin.com/")
                time.sleep(2)
                with open(self.cookie_file, 'r', encoding='utf-8') as file:
                    cookies = json.load(file)
                for cookie in cookies:
                    if 'sameSite' in cookie and cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                        cookie['sameSite'] = 'Lax'
                    if cookie.get("name", "").startswith("__Host-"):
                        cookie.pop("domain", None)
                    self.driver.add_cookie(cookie)
                logging.info("✅ کوکی‌ها با موفقیت بارگذاری شدند.")
                return True
            elif action == "save":
                cookies = self.driver.get_cookies()
                with open(self.cookie_file, 'w', encoding='utf-8') as file:
                    json.dump(cookies, file, indent=2, ensure_ascii=False)
                logging.info("🔒 کوکی‌ها با موفقیت ذخیره شدند.")
                return True
        except FileNotFoundError:
            logging.warning("⚠️ فایل کوکی یافت نشد.")
            return False
        except json.JSONDecodeError:
            logging.warning("⚠️ خطا در فرمت فایل کوکی.")
            return False
        except Exception as e:
            logging.exception(f"⚠️ خطای ناشناخته: {str(e)}")
            return False

    def check_cloudflare_challenge(self):
        try:
            self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#cf-challenge-running, .ray_id, .attack-box")
            ))
            logging.info("⏳ در حال پردازش چالش Cloudflare...")
            for _ in range(5):
                self.human_like_interaction()
                time.sleep(random.uniform(2, 5))
            return True
        except TimeoutException:
            return False
        except Exception as e:
            logging.exception(f"⚠️ خطا در مدیریت چالش: {str(e)}")
            return False

    def login(self):
        try:
            self.driver.get("https://www.linkedin.com/")
            if self.check_cloudflare_challenge():
                logging.info("✅ چالش Cloudflare با موفقیت پشت سر گذاشته شد.")
            if self.handle_cookies("load"):
                self.driver.refresh()
                if self.is_logged_in():
                    logging.info("✅ ورود با کوکی موفقیت‌آمیز بود.")
                    return
            if self.headless:
                logging.info("🔑 کوکی‌ها کار نکردند. تغییر حالت headless به False و راه‌اندازی مجدد مرورگر.")
                self.headless = False
                self.shutdown()
                self.driver = self.configure_driver()
                self.wait = WebDriverWait(self.driver, 25)
            logging.info("🔑 نیاز به ورود دستی دارید.")
            self.driver.get("https://www.linkedin.com/login")
            input("پس از تکمیل ورود در مرورگر، Enter را فشار دهید...")
            if self.is_logged_in():
                self.handle_cookies("save")
                logging.info("✅ احراز هویت تکمیل شد.")
            else:
                logging.error("⚠️ ورود انجام نشد. لطفا اطلاعات ورود را بررسی کنید.")
                raise Exception("ورود ناموفق.")
        except Exception as e:
            logging.exception(f"⚠️ خطای بحرانی در ورود: {str(e)}")
            raise

    async def async_login(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.login)

    def is_logged_in(self):
        try:
            self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "nav[aria-label='Primary Navigation']")
            ))
            self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "img.global-nav__me-photo")
            ))
            return True
        except TimeoutException:
            logging.warning("⚠️ زمان‌بندی المان‌های ورود به پایان رسید.")
            return False
        except Exception as e:
            logging.exception(f"⚠️ خطا در بررسی وضعیت ورود: {str(e)}")
            return False

    # متدهای مدیریت صف برای پردازش تب‌ها
    def add_urls_to_queue(self, urls):
        for url in urls:
            # فرض کنید که ExtractionStrategyFactory از قبل تعریف شده و به استراتژی‌های استخراج ارجاع می‌دهد.
            strategy = ExtractionStrategyFactory.get_strategy(url)
            self.tab_queue.put((url, strategy))
        logging.info(f"✅ {self.tab_queue.qsize()} آدرس به صف اضافه شدند.")

    def check_target_in_database(self, connection_string, target):
        """بررسی وجود تارگت در دیتابیس"""
        try:
            conn = pyodbc.connect(connection_string)
            cursor = conn.cursor()
            query = "SELECT COUNT(*) FROM LinkedInUserData WHERE Target = ?"
            cursor.execute(query, (target,))
            count = cursor.fetchone()[0]
            return count > 0
        except Exception as e:
            logging.error(f"خطا در بررسی وجود تارگت در دیتابیس: {str(e)}")
            return False
        finally:
            if conn:
                conn.close()

    def update_data_in_database(self, data, connection_string, target, update_fields=None):
        try:
            conn = pyodbc.connect(connection_string)
            cursor = conn.cursor()
            current_time = datetime.datetime.now()

            # اگر تمام فیلدها باید آپدیت شوند
            if update_fields is None:
                update_fields = data.keys()

            set_clauses = []
            params = []
            for field in update_fields:
                field_key = field
                json_data = json.dumps(data.get(field_key, []), ensure_ascii=False)
                column_name = f"{field_key.capitalize()}Data"
                set_clauses.append(f"{column_name} = ?")
                params.append(json_data)

            set_clauses.append("UpdatedAt = ?")
            params.append(current_time)
            params.append(target)

            set_clause_str = ", ".join(set_clauses)
            query = f"""
                UPDATE [dbo].[LinkedInUserData]
                SET {set_clause_str}
                WHERE Target = ?
            """
            cursor.execute(query, params)
            conn.commit()
            logging.info("✅ داده‌ها با موفقیت در دیتابیس به‌روز شدند.")
        except Exception as e:
            logging.error(f"⚠️ خطا در به‌روزرسانی داده‌ها: {str(e)}")
        finally:
            if conn:
                conn.close()

    def insert_data_into_database(self, data, connection_string, target):
        try:
            conn = pyodbc.connect(connection_string)
            cursor = conn.cursor()
            current_time = datetime.datetime.now()

            # آماده‌سازی داده‌ها برای اینسرت
            profile_data = json.dumps(data.get("profile", []), ensure_ascii=False)
            activity_data = json.dumps(data.get("activity", []), ensure_ascii=False)
            education_data = json.dumps(data.get("education", []), ensure_ascii=False)
            skills_data = json.dumps(data.get("skills", []), ensure_ascii=False)
            publications_data = json.dumps(data.get("publications", []), ensure_ascii=False)
            honors_data = json.dumps(data.get("honors", []), ensure_ascii=False)
            languages_data = json.dumps(data.get("languages", []), ensure_ascii=False)
            projects_data = json.dumps(data.get("projects", []), ensure_ascii=False)
            volunteering_data = json.dumps(data.get("volunteering", []), ensure_ascii=False)
            certifications_data = json.dumps(data.get("certifications", []), ensure_ascii=False)
            courses_data = json.dumps(data.get("courses", []), ensure_ascii=False)
            experience_data = json.dumps(data.get("experience", []), ensure_ascii=False)
            organizations_data = json.dumps(data.get("organizations", []), ensure_ascii=False)

            query = """
                INSERT INTO [dbo].[LinkedInUserData] (
                    ProfileData, ActivityData, EducationData, SkillsData, PublicationsData,
                    HonorsData, LanguagesData, ProjectsData, VolunteeringData, CertificationsData,
                    CoursesData, ExperienceData, OrganizationsData, CreatedAt, UpdatedAt, Target
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(query, (
                profile_data, activity_data, education_data, skills_data, publications_data,
                honors_data, languages_data, projects_data, volunteering_data, certifications_data,
                courses_data, experience_data, organizations_data, current_time, current_time, target
            ))
            conn.commit()
            logging.info("داده با موفقیت به دیتابیس اضافه شد.")
        except Exception as e:
            logging.error(f"خطا در وارد کردن داده به دیتابیس: {str(e)}")
        finally:
            if conn:
                conn.close()

    def process_queue(self, connection_string, target, update_mode=False, update_fields=None):
        results = {}
        while not self.tab_queue.empty():
            url, strategy = self.tab_queue.get()
            try:
                result = self._process_single_tab(url, strategy)
                if result:
                    results[result["strategy"]] = result["data"]
            except Exception as e:
                logging.error(f"⚠️ خطا در پردازش تب {url}: {str(e)}")
            finally:
                self._switch_to_main_window()
                self.tab_queue.task_done()

        if update_mode:
            self.update_data_in_database(results, connection_string, target, update_fields)
        else:
            self.insert_data_into_database(results, connection_string, target)
        return results

    def _process_single_tab(self, url, strategy):
        self._open_new_tab(url)
        new_handle = self._get_new_tab_handle()
        tab = TabHandler(self.driver, new_handle, url, strategy)
        return tab.extract_data()

    def _open_new_tab(self, url):
        self.driver.execute_script(f"window.open('{url}');")
        time.sleep(1)

    def _get_new_tab_handle(self):
        handles = self.driver.window_handles
        new_handles = [h for h in handles if h != self.main_handle]
        if new_handles:
            return new_handles[-1]
        else:
            raise Exception("هیچ تب جدیدی پیدا نشد.")

    def _switch_to_main_window(self):
        try:
            self.driver.switch_to.window(self.main_handle)
        except Exception as e:
            logging.warning(f"خطا در بازگشت به پنجره اصلی: {str(e)}")


    def shutdown(self):
        try:
            if self.driver:
                self.driver.quit()
                logging.info("مرورگر به درستی بسته شد.")
        except Exception as e:
            logging.exception(f"خطا در بستن مرورگر: {str(e)}")

# ---------------------------------------------------------------------
# تابع اصلی async
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# تابع اصلی async
# ---------------------------------------------------------------------



async def main():
    enabled_features = {
        "profile": True, "activity": True, "education": True, "skills": True,
        "publications": True, "honors": True, "languages": True, "projects": True,
        "volunteering": True, "certifications": True, "courses": True, "experience": True,
        "organizations": True
    }
    connection_string = database_project
    automation = LinkedinAutomation(cookie_file="linkedin_cookies.json", headless=False)

    try:
        await automation.async_configure_driver()
        await automation.async_login()

        target = input("لطفاً نام کاربری لینکدین هدف را وارد کنید: ").strip()

        # بررسی وجود تارگت در دیتابیس
        target_exists = automation.check_target_in_database(connection_string, target)

        if target_exists:
            print("✅ تارگت در دیتابیس موجود است. شروع فرآیند تحلیل...")

            # تحلیل داده‌های موجود
            analyzer = LinkedInAnalyzer(target)
            try:
                # دریافت داده از دیتابیس
                data = analyzer.get_linkedin_data()

                # تحلیل کامل
                print("\n" + "=" * 50 + " تحلیل کامل پروفایل " + "=" * 50)
                full_analysis = analyzer.analyze_full()
                print(full_analysis)

                # تحلیل بخش به بخش
                print("\n" + "=" * 50 + " تحلیل بخش‌های جداگانه " + "=" * 50)
                section_analysis = analyzer.analyze_sections_individually()
                for section, result in section_analysis.items():
                    print(f"\n{'-' * 30} {section.upper()} {'-' * 30}")
                    print(result)

            except RuntimeError as e:
                print(f"⚠️ خطا در تحلیل داده‌ها: {str(e)}")
                return

            # پرسش برای آپدیت داده‌ها
            update_choice = input("\nآیا می‌خواهید داده‌ها را به‌روزرسانی کنید؟ (بله/خیر): ").strip().lower()
            if update_choice == 'بله':
                # دریافت فیلدهای مورد نظر برای آپدیت
                print("\nلطفاً شماره فیلدهایی را که می‌خواهید به‌روزرسانی شوند وارد کنید (با کاما جدا کنید):")
                fields = [
                    ("profile", "پروفایل"), ("activity", "فعالیت‌ها"), ("education", "تحصیلات"),
                    ("skills", "مهارت‌ها"), ("publications", "انتشارات"), ("honors", "افتخارات"),
                    ("languages", "زبان‌ها"), ("projects", "پروژه‌ها"), ("volunteering", "داوطلبانه"),
                    ("certifications", "گواهینامه‌ها"), ("courses", "دوره‌ها"), ("experience", "تجربه"),
                    ("organizations", "سازمان‌ها")
                ]
                for idx, (key, name) in enumerate(fields, 1):
                    print(f"{idx}. {name}")
                selected = input("شماره‌ها: ").strip().split(',')
                update_fields = [fields[int(i.strip()) - 1][0] for i in selected if i.strip().isdigit()]

                # آپدیت داده‌ها
                base_url = f"https://www.linkedin.com/in/{target}/"
                urls_config = {
                    "profile": base_url, "activity": f"{base_url}recent-activity/all/",
                    "education": f"{base_url}details/education/", "skills": f"{base_url}details/skills/",
                    "publications": f"{base_url}details/publications/", "honors": f"{base_url}details/honors/",
                    "languages": f"{base_url}details/languages/", "projects": f"{base_url}details/projects/",
                    "volunteering": f"{base_url}details/volunteering-experiences/",
                    "certifications": f"{base_url}details/certifications/", "courses": f"{base_url}details/courses/",
                    "experience": f"{base_url}details/experience/", "organizations": f"{base_url}details/organizations/"
                }
                target_urls = [urls_config[key] for key in urls_config if key in update_fields]
                automation.add_urls_to_queue(target_urls)
                automation.process_queue(connection_string, target, update_mode=True, update_fields=update_fields)

                # تحلیل مجدد پس از آپدیت
                print("\n" + "=" * 50 + " تحلیل داده‌های به‌روز شده " + "=" * 50)
                try:
                    analyzer = LinkedInAnalyzer(target)
                    data = analyzer.get_linkedin_data()
                    full_analysis = analyzer.analyze_full()
                    print(full_analysis)
                except RuntimeError as e:
                    print(f"⚠️ خطا در تحلیل داده‌های به‌روز شده: {str(e)}")

        else:
            print("🔍 تارگت در دیتابیس یافت نشد. شروع فرآیند کرول...")

            # تنظیم URLها بر اساس ویژگی‌های فعال
            base_url = f"https://www.linkedin.com/in/{target}/"
            urls_config = {
                "profile": base_url, "activity": f"{base_url}recent-activity/all/",
                "education": f"{base_url}details/education/", "skills": f"{base_url}details/skills/",
                "publications": f"{base_url}details/publications/", "honors": f"{base_url}details/honors/",
                "languages": f"{base_url}details/languages/", "projects": f"{base_url}details/projects/",
                "volunteering": f"{base_url}details/volunteering-experiences/",
                "certifications": f"{base_url}details/certifications/", "courses": f"{base_url}details/courses/",
                "experience": f"{base_url}details/experience/", "organizations": f"{base_url}details/organizations/"
            }
            target_urls = [urls_config[key] for key in urls_config if enabled_features.get(key, False)]
            automation.add_urls_to_queue(target_urls)

            # انجام کرول و ذخیره داده‌ها
            automation.process_queue(connection_string, target)

            # تحلیل داده‌های جدید
            print("\n" + "=" * 50 + " تحلیل داده‌های جدید " + "=" * 50)
            analyzer = LinkedInAnalyzer(target)
            try:
                data = analyzer.get_linkedin_data()
                full_analysis = analyzer.analyze_full()
                print(full_analysis)

                print("\n" + "=" * 50 + " تحلیل بخش‌های جداگانه " + "=" * 50)
                section_analysis = analyzer.analyze_sections_individually()
                for section, result in section_analysis.items():
                    print(f"\n{'-' * 30} {section.upper()} {'-' * 30}")
                    print(result)

            except RuntimeError as e:
                print(f"⚠️ خطا در تحلیل داده‌های جدید: {str(e)}")

    except Exception as e:
        logging.error(f"⚠️ خطا در اجرای برنامه: {str(e)}")
    finally:
        automation.shutdown()


# ---------------------------------------------------------------------
# اجرای برنامه اصلی
# ---------------------------------------------------------------------


if __name__ == '__main__':
    asyncio.run(main())


