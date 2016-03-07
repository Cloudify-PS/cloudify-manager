#########
# Copyright (c) 2013 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#  * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  * See the License for the specific language governing permissions and
#  * limitations under the License.


from flask import current_app

from manager_rest import config
from manager_rest import celery_client


class WorkflowClient(object):

    def __init__(self):
        ssl_enabled = False
        verify_certificate = False
        cloudify_username = None
        cloudify_password = None
        cfy_config = config.instance()

        security_enabled = cfy_config.security_enabled
        if security_enabled:
            cloudify_username = cfy_config.security_admin_username
            cloudify_password = cfy_config.security_admin_password
            ssl_enabled = cfy_config.security_ssl.get('enabled', True)
            if ssl_enabled:
                verify_certificate = cfy_config.security_ssl.get(
                    'verify_certificate', True)

        self.security_context = {
            'security_enabled': security_enabled,
            'ssl_enabled': ssl_enabled,
            'verify_ssl_certificate': verify_certificate,
            'cloudify_username': cloudify_username,
            'cloudify_password': cloudify_password
        }

    def execute_workflow(self,
                         name,
                         workflow,
                         workflow_plugins,
                         blueprint_id,
                         deployment_id,
                         execution_id,
                         execution_parameters=None):
        execution_parameters = execution_parameters or {}
        task_name = workflow['operation']
        task_queue = 'cloudify.management'

        plugin_name = workflow['plugin']
        plugin = [p for p in workflow_plugins if p['name'] == plugin_name][0]
        execution_parameters['__cloudify_context'] = {
            'type': 'workflow',
            'task_name': task_name,
            'task_id': execution_id,
            'task_target': task_queue,
            'workflow_id': name,
            'blueprint_id': blueprint_id,
            'deployment_id': deployment_id,
            'execution_id': execution_id,
            'security_context': self.security_context,
            'plugin': {
                'name': plugin_name,
                'package_name': plugin.get('package_name'),
                'package_version': plugin.get('package_version')
            }
        }
        return execute_task(task_queue=task_queue,
                            execution_id=execution_id,
                            execution_parameters=execution_parameters)

    def execute_system_workflow(self, wf_id, task_id, task_mapping,
                                deployment=None, execution_parameters=None):
        execution_parameters = execution_parameters or {}
        # task_id is not generated here since for system workflows,
        # the task id is equivalent to the execution id
        task_queue = 'cloudify.management'
        context = {
            'type': 'workflow',
            'task_id': task_id,
            'task_name': task_mapping,
            'task_target': task_queue,
            'execution_id': task_id,
            'workflow_id': wf_id,
            'security_context': self.security_context
        }

        if deployment:
            context['blueprint_id'] = deployment.blueprint_id
            context['deployment_id'] = deployment.id

        execution_parameters['__cloudify_context'] = context

        return execute_task(task_queue=task_queue,
                            execution_id=context['task_id'],
                            execution_parameters=execution_parameters)


# What we need to access this manager in Flask
def get_workflow_client():
    """
    Get the current app's workflow client, create if necessary
    """
    wf_client = current_app.config.get('workflow_client')
    if not wf_client:
        current_app.config['workflow_client'] = WorkflowClient()
        wf_client = current_app.config.get('workflow_client')
    return wf_client


def execute_task(task_queue, execution_id, execution_parameters):
    celery = celery_client.get_client()
    try:
        return celery.execute_task(task_queue=task_queue,
                                   task_id=execution_id,
                                   kwargs=execution_parameters)
    finally:
        celery.close()
