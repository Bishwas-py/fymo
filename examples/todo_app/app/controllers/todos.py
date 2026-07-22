"""Controller for the todos resource.

One controller serves the whole resource: /todos (index)
and /todos/<id> (show) both land here through the resources
entry in fymo.yml, and `id` arrives as the route param, empty on the
index. The template branches on item_id: the list, or one row's detail.
"""


def getContext(id: str = ''):
    # Returned keys arrive in the template as props, server-rendered.
    return {
        'name': 'todos',
        'item_id': id,
    }
