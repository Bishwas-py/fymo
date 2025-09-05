"""Route configuration"""

routes = {
    '/': {
        'controller': 'todos',
        'action': 'index',
        'template': 'todos/index.svelte'
    }
}

resources = ['todos']
