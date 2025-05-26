# app/serializers.py
from rest_framework import serializers

class LinkedInUsernameSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=100)
