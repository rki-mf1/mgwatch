from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(str(key), "")


@register.filter
def get_min(dictionary, key):
    return dictionary.get(str(key), ("", ""))[0]


@register.filter
def get_max(dictionary, key):
    return dictionary.get(str(key), ("", ""))[1]


@register.filter
def is_numeric(column_index, rows):
    for row in rows:
        try:
            float(row[column_index])
        except (ValueError, IndexError):
            return False
    return True


@register.filter
def in_list(value, the_list):
    return value in the_list


@register.filter
def last_part_of_url(value):
    if value and isinstance(value, str):
        return value.rstrip("/").split("/")[-1]
    return value


@register.filter
def zip_lists(a, b):
    return zip(a, b)


@register.filter
def lat_lon_for_osm(lat_lon):
    return lat_lon.replace(", ", "/")
