from django.db import models


class User(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField()


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField()
