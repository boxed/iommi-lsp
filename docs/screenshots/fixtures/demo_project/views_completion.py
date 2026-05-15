from django.views.generic import UpdateView

from myapp.models import User


class UserUpdate(UpdateView):
    model = User
    pass
