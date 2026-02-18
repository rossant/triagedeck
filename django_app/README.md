# Django Adapter

Initial Django integration module for triagedeck.

## Files

- `django_app/models.py`
- `django_app/views.py`
- `django_app/urls.py`
- `django_app/permissions.py`

## Integration

Add to your Django project:

- `INSTALLED_APPS += ["django_app"]`
- `path("", include("django_app.urls"))`

This adapter expects authenticated Django users (`request.user`) and uses project membership for authorization.
