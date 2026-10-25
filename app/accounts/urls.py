from django.urls import path

from . import views

urlpatterns = [
    path("entrar/", views.login_view, name="login"),
    path("entrar/mfa/", views.mfa_verify, name="mfa_verify"),
    path("sair/", views.logout_view, name="logout"),
    path("comecar/", views.signup, name="signup"),
    path("entrar-convite/<str:token>/", views.invite_accept, name="invite_accept"),
    path("seguranca/mfa/", views.mfa_setup, name="mfa_setup"),
    path("empresa/", views.empresa, name="empresa"),
    path("convites/", views.convites, name="convites"),
    path("trocar-empresa/", views.trocar_empresa, name="trocar_empresa"),
]
