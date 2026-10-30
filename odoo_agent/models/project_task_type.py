# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    agent_auto_dispatch = fields.Boolean(
        string='Dispatch AI Agent On Entry',
        help='When a task enters this stage, queue an execution for its assigned '
             'agent if there is no active execution already running.',
    )
