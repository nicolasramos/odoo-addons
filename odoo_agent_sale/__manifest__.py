{
    'name': 'AI Agent System: Sales',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Assign sales orders and quotations to AI agents',
    'description': """
Extends the AI Agent System to quotations and sales orders.

- Assign an agent to a quotation and run it on the external runtime.
- Mention an agent in the order chatter (@handle) and get the answer posted
  back in the same thread.
- The runtime receives the order header and its lines as structured context.
""",
    'author': 'Nicolas Ramos',
    'website': 'https://github.com/nicolasramos',
    'depends': ['odoo_agent', 'sale'],
    'data': [
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
