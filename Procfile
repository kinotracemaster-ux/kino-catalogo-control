release: python manage.py migrate --noinput && python manage.py setup_roles
web: gunicorn kino.wsgi --log-file -
worker: python manage.py run_worker --drive-every 15
