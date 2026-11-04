from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Platform user; defined before the first database migration."""
