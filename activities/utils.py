from .models import Activity

def get_client_ip(request):
    if not request:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def log_activity(user, action, description, object_type='', object_id='', request=None):
    if not user or not user.is_authenticated:
        return None
    ip = get_client_ip(request)
    return Activity.objects.create(
        user=user,
        action=action,
        description=description,
        object_type=object_type,
        object_id=str(object_id) if object_id else '',
        ip_address=ip
    )
