from django.db.models.signals import post_save
from django.dispatch import receiver

from myapp.models import User, Profile
