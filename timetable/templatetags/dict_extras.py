# timetable/templatetags/dict_extras.py

from django import template

register = template.Library()

@register.filter
def get(dictionary, key):
    """Safely get a value from a dictionary in Django templates."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None
