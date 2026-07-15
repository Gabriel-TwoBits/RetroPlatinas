from django.shortcuts import render

from .fake_home import fake_home_context


def home(request):
    return render(request, "home.html", fake_home_context())
