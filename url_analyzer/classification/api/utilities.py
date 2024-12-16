import secrets
import string


def generate_jwt_secret_key():
  characters = string.ascii_letters + string.digits + string.punctuation
  return ''.join(secrets.choice(characters) for _ in range(32))

