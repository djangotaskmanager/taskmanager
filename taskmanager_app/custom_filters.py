from django import template

register = template.Library()


@register.tag
@register.filter
def get_key(dictionary, key):
    return dictionary.get(key, None)
