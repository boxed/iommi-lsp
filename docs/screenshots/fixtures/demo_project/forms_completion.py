from django import forms

from myapp.models import User


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        pass
