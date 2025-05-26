# views.py
from django.shortcuts import render, redirect
from django.conf import settings
from .forms import LinkedInUsernameForm
import asyncio
from app.controller import LinkedinAutomation, LinkedInAnalyzer
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import asyncio
from django.views.decorators.csrf import csrf_exempt


# ساخت رشته اتصال از تنظیمات Django
connection_string = (
    f"Driver={{ODBC Driver 17 for SQL Server}};"
    f"Server={settings.DATABASES['default']['HOST']};"
    f"Database={settings.DATABASES['default']['NAME']};"
    f"UID={settings.DATABASES['default']['USER']};"
    f"PWD={settings.DATABASES['default']['PASSWORD']};"
)


# تابع آسنکرون کرولر
async def async_run_crawler(username, connection_string):
    automation = LinkedinAutomation(cookie_file="linkedin_cookies.json", headless=True)
    await automation.async_configure_driver()
    await automation.async_login()

    target_exists = automation.check_target_in_database(connection_string, username)

    if not target_exists:
        base_url = f"https://www.linkedin.com/in/{username}/"
        target_urls = [
            base_url, f"{base_url}recent-activity/all/",
            f"{base_url}details/education/", f"{base_url}details/skills/",
            f"{base_url}details/publications/", f"{base_url}details/honors/",
            f"{base_url}details/languages/", f"{base_url}details/projects/",
            f"{base_url}details/volunteering-experiences/",
            f"{base_url}details/certifications/", f"{base_url}details/courses/",
            f"{base_url}details/experience/", f"{base_url}details/organizations/"
        ]
        automation.add_urls_to_queue(target_urls)
        automation.process_queue(connection_string, username)

    automation.shutdown()



@api_view(['POST'])
@csrf_exempt
def home(request):
    username = request.data.get('username')

    if not username:
        return Response({'error': 'Username is required.'}, status=status.HTTP_400_BAD_REQUEST)

    request.session['username'] = username
    return Response({'message': 'Username saved successfully.'}, status=status.HTTP_200_OK)


@api_view(['GET'])
def show(request):
    username = request.session.get('username', '')

    if not username:
        return Response({'error': 'No username found in session.'}, status=status.HTTP_400_BAD_REQUEST)

    automation = LinkedinAutomation(cookie_file="linkedin_cookies.json", headless=True)

    try:
        # اجرای کرولر
        asyncio.run(async_run_crawler(username, connection_string))

        target_exists = automation.check_target_in_database(connection_string, username)

        if not target_exists:
            base_url = f"https://www.linkedin.com/in/{username}/"
            target_urls = [
                base_url, f"{base_url}recent-activity/all/",
                f"{base_url}details/education/", f"{base_url}details/skills/",
                f"{base_url}details/publications/", f"{base_url}details/honors/",
                f"{base_url}details/languages/", f"{base_url}details/projects/",
                f"{base_url}details/volunteering-experiences/",
                f"{base_url}details/certifications/", f"{base_url}details/courses/",
                f"{base_url}details/experience/", f"{base_url}details/organizations/"
            ]
            automation.add_urls_to_queue(target_urls)
            automation.process_queue(connection_string, username)

        analyzer = LinkedInAnalyzer(username)
        data = analyzer.get_linkedin_data()
        analysis = analyzer.analyze_full()

        return Response({'username': username, 'analysis': analysis}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        automation.shutdown()




