from .models import Notification

def create_notification(recipient, title, message, notification_type='info', link=''):
    """
    Helper function to dispatch a database-backed notification to a specific user.
    """
    if not recipient:
        return None
    return Notification.objects.create(
        recipient=recipient,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link
    )
