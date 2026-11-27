{
    'name': 'OdooClaw MCP',
    'summary': 'MCP endpoint whose tools are declared as server actions',
    'description': """
OdooClaw MCP exposes an MCP (Model Context Protocol) endpoint served by Odoo
itself. A tool is a data record: a name, a description, an input schema and a
server action. Nothing is exposed by default, write tools stay disabled unless
their record says otherwise, and the key carries its own MCP scope: a normal
Odoo API key does not open this endpoint.
    """,
    'version': '18.0.1.0.0',
    'category': 'Technical',
    'license': 'LGPL-3',
    'author': 'Nicolás Ramos',
    'website': 'https://nicolasramos.es',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/odooclaw_mcp_key_views.xml',
        'views/odooclaw_mcp_tool_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
}
