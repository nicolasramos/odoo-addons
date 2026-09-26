# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'OdooClaw AI Bot - Sales',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Sales areas and counters for OdooClaw proactive assistance',
    'author': 'Nicolás Ramos',
    'license': 'AGPL-3',
    'depends': ['mail_bot_odooclaw',
    'sale_management',
    'crm'],
    'data': ['data/odooclaw_proactive_sale_data.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'maintainer': 'nicolasramos',
    'development_status': 'Beta'}
