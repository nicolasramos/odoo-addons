# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'AI Agent System',
    'version': '18.0.1.8.0',
    'category': 'Productivity',
    'summary': 'AI Agent management: runtimes, agents, executions, logs, chat, MCP, and stage mapping',
    'description': """
Provides a native multi-agent execution architecture inside Odoo.
- Agent Runtimes: external machines (N100, Mac Mini, etc.) connected via API
- AI Agents: configurable entities with instructions, skills, and runtime assignment
- Agent Skills: reusable instruction packs
- Agent Executions: repeatable runtime work units linked to project.task
- Execution Logs: detailed command history with streaming support
- Agent Chat: direct messaging between users and AI agents
- Stage Mapping: configurable agent status to project stage mapping
- REST API: bidirectional communication with external runtimes
- Live updates: form and list views subscribe to odoo_agent bus.bus channels
""",
    'author': 'Nicolas Ramos',
    'website': 'https://github.com/nicolasramos',
    'depends': ['project', 'mail', 'base', 'bus'],
    'assets': {
        'web.assets_backend': [
            'odoo_agent/static/src/scss/agent_task_communications.scss',
            'odoo_agent/static/src/js/agent_live_update_service.js',
            'odoo_agent/static/src/js/agent_live_update_form_patch.js',
            'odoo_agent/static/src/js/agent_live_update_list_patch.js',
        ],
        'web.assets_unit_tests': [
            'odoo_agent/static/tests/agent_live_update_service_tests.js',
        ],
    },
    'data': [
        'security/agent_security.xml',
        'security/ir.model.access.csv',
        'views/actions_views.xml',
        'views/menu_views.xml',
        'views/agent_runtime_views.xml',
        'views/agent_views.xml',
        'views/agent_skill_views.xml',
        'views/agent_mcp_server_views.xml',
        'views/agent_execution_views.xml',
        'views/agent_task_views.xml',
        'views/agent_log_views.xml',
        'views/agent_chat_views.xml',
        'views/agent_stage_map_views.xml',
        'views/project_task_inherit_views.xml',
        'data/agent_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
