# forms.py
from django import forms


class LinkedInUsernameForm(forms.Form):
    username = forms.CharField(
        label="نام کاربری لینکدین",
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "linkedin-username"})
    )







