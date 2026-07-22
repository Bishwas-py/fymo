"""Controller for the posts resource.

One controller serves the whole resource: /posts (index)
and /posts/<id> (show) both land here through the resources
entry in fymo.yml, and `id` arrives as the route param, empty on the
index. The template branches on item_id: the list, or one row's detail.
"""


def getContext(id: str = ''):
    # Returned keys arrive in the template as props, server-rendered.
    return {
        'name': 'posts',
        'item_id': id,
    }
