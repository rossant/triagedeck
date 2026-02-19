from django.urls import path

from django_app import views

urlpatterns = [
    path("metrics", views.metrics_view, name="metrics"),
    path("api/v1/projects", views.projects_list, name="projects_list"),
    path("api/v1/projects/<uuid:project_id>/config", views.project_config, name="project_config"),
    path("api/v1/projects/<uuid:project_id>/items", views.items_list, name="items_list"),
    path(
        "api/v1/projects/<uuid:project_id>/items/<uuid:item_id>",
        views.item_get,
        name="item_get",
    ),
    path(
        "api/v1/projects/<uuid:project_id>/items/<uuid:item_id>/url",
        views.item_url,
        name="item_url",
    ),
    path("api/v1/projects/<uuid:project_id>/events", views.events_post, name="events_post"),
    path(
        "api/v1/projects/<uuid:project_id>/decisions",
        views.decisions_list,
        name="decisions_list",
    ),
    path(
        "api/v1/projects/<uuid:project_id>/exports",
        views.exports_collection,
        name="exports_collection",
    ),
    path(
        "api/v1/projects/<uuid:project_id>/exports/<uuid:export_id>",
        views.exports_detail,
        name="exports_detail",
    ),
]
