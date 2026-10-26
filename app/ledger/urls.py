from django.urls import path

from . import views

urlpatterns = [
    path("", lambda request: views.fechamento(request, "atual"), name="home"),
    path("fechamento/<slug:periodo_slug>/", views.fechamento, name="fechamento"),
    path(
        "fechamento/<slug:periodo_slug>/totais/", views.fechamento_totais, name="fechamento_totais"
    ),
    path("fechamento/<slug:periodo_slug>/lista/", views.fechamento_lista, name="fechamento_lista"),
    path(
        "demonstrativo/<slug:periodo_slug>/lista/",
        views.demonstrativo_lista,
        name="demonstrativo_lista",
    ),
    path(
        "demonstrativo/<slug:periodo_slug>/csv/", views.demonstrativo_csv, name="demonstrativo_csv"
    ),
    path(
        "demonstrativo/<slug:periodo_slug>/pdf/", views.demonstrativo_pdf, name="demonstrativo_pdf"
    ),
    path("item/<str:item_id>/", views.item_detalhe, name="item_detalhe"),
    path("auditoria/", views.auditoria, name="auditoria"),
    path("item/<str:item_id>/confirmar/", views.item_confirmar, name="item_confirmar"),
    path("item/<str:item_id>/recusar/", views.item_recusar, name="item_recusar"),
    path("item/<str:item_id>/desfazer/", views.item_desfazer, name="item_desfazer"),
    path("item/<str:item_id>/classificar/", views.item_classificar, name="item_classificar"),
    path(
        "item/<str:item_id>/desclassificar/", views.item_desclassificar, name="item_desclassificar"
    ),
    path("aprovar-lote/", views.aprovar_lote, name="aprovar_lote"),
    path("abrir-periodo/", views.abrir_periodo, name="abrir_periodo"),
    path("fechar-periodo/", views.fechar_periodo, name="fechar_periodo"),
    path("vinculo-manual/", views.vinculo_manual, name="vinculo_manual"),
    path("importacao/", views.importacao, name="importacao"),
    path("importacao/enviar/<str:kind>/", views.importacao_enviar, name="importacao_enviar"),
    path("importacao/duplicatas/", views.importacao_duplicatas, name="importacao_duplicatas"),
    path("importacao/modelo-csv/", views.modelo_csv, name="modelo_csv"),
    path("importacao/duplicatas/revisar/", views.duplicatas_revisar, name="duplicatas_revisar"),
    path("landing/", views.landing, name="landing"),
    path("privacidade/", views.privacy, name="privacy"),
    path("termos/", views.terms, name="terms"),
    path("health", views.health, name="health"),
    path("health/", views.health, name="health_slash"),
]
