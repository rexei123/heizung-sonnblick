"""Celery-Task-Module.

Engine-Tasks werden in ``engine_tasks.py`` definiert. Modul-Import passiert
ueber ``celery_app.include`` — das stellt sicher, dass die Tasks beim
Worker-Start registriert sind, ohne dass ``main.py`` sie laden muss.
"""
