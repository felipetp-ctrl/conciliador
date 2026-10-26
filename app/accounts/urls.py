from django.urls import path

from . import views

urlpatterns = [
    path("entrar/", views.login_view, name="login"),
    path("entrar/mfa/", views.mfa_verify, name="mfa_verify"),
    path("entrar/recuperacao/", views.recovery_verify, name="recovery_verify"),
    path("sair/", views.logout_view, name="logout"),
    path("comecar/", views.signup, name="signup"),
    path("entrar-convite/<str:token>/", views.invite_accept, name="invite_accept"),
    path("seguranca/mfa/", views.mfa_setup, name="mfa_setup"),
    path("empresa/", views.empresa, name="empresa"),
    path("convites/", views.convites, name="convites"),
    path("conta/exportar/", views.exportar_dados, name="exportar_dados"),
    path("conta/excluir/", views.excluir_conta, name="excluir_conta"),
    path("trocar-empresa/", views.trocar_empresa, name="trocar_empresa"),
]
