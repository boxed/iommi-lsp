from django.urls import path


def view(*a, **kw):
    return None


urlpatterns = [
    path("", view, name="index"),
    path("about/", view, name="about"),
    path("contact/", view, name="contact"),
]
