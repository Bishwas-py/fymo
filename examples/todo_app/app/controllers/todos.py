"""
Todos controller - Provides dynamic data for the todo app
"""

def getContext():
    """Dynamic context function called from server to populate props"""
    print("getContext called")
    return {
        'todos': [
            {'id': 1, 'text': 'Learn Fymo framework', 'completed': True},
            {'id': 2, 'text': 'Build an awesome app with Python + Svelte 5', 'completed': False},
            {'id': 3, 'text': 'Master Svelte 5 runes ($state, $derived, $effect)', 'completed': False},
            {'id': 4, 'text': 'Deploy to production', 'completed': False},
        ],
        'user': {
            'name': 'Fymo Developer',
            'theme': 'dark'
        },
        'stats': {
            'total_projects': 42,
            'active_todos': 3
        }
    }

def getDoc():
    """Dynamic document metadata function called from server"""
    return {
        'title': 'Fymo Todo App - Dynamic SSR',
        'head': {
            'meta': [
                {'name': 'description', 'content': 'A powerful todo app built with Fymo and Svelte 5'},
                {'name': 'keywords', 'content': 'fymo, svelte, todo, ssr, python'},
                {'name': 'author', 'content': 'Fymo Framework'},
                {'property': 'og:title', 'content': 'Fymo Todo App'},
                {'property': 'og:description', 'content': 'Dynamic SSR with Svelte 5'}
            ],
            'script': {
                'analyticsID': 'GA-FYMO-123456',
                'hotjar': '3234567',
                'custom': [
                    'console.log("Analytics loaded for Todo App");',
                    'console.log("Custom tracking initialized");'
                ]
            }
        }
    }
