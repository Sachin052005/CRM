from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

urlpatterns = [
    # Default root redirect
    path('', lambda request: redirect('login'), name='root'),

    # Django Admin Site
    path('django-admin/', admin.site.urls),

    # Application Modules
    path('', include('accounts.urls')),
    path('', include('reports.urls')),
    path('', include('managers.urls')),
    path('', include('branch_heads.urls')),
    path('', include('counselors.urls')),
    path('', include('telecallers.urls')),
    path('', include('leads.urls')),
    path('', include('channels.urls')),
    path('', include('products.urls')),
    path('', include('branches.urls')),
    path('', include('calls.urls')),
    path('', include('followups.urls')),
    path('', include('activities.urls')),
    path('drive/', include('drive.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
